# //// Neoffice — added file (no upstream equivalent).
"""A reseller's product feed: their products, with photos, at their prices, at an address a script can read.

It stands in for an API for the reseller who has a shop and no developer (note 04 of the study): a CSV or a
JSON file, the selling price of the reseller included (what they pay plus their markup, never what they pay),
the pictures as whole public addresses, read from a shop's importer or a one-line script.

- **One feed a customer**, made of a selection and a markup like a catalogue. It is a file, written by a job
  (`refresh`), never computed while somebody reads it: the prices of a few hundred products take seconds.
  A file is written when the feed is saved, by the button, and each night for the feeds that are being read.
- **The address is the secret**: `/feeds/reseller/<token>/products.csv` (or `.json`). The token is 32
  characters from 24 random bytes; the database keeps its SHA-256 (to find the feed) and the token encrypted
  (so that the page can show the address again), never in the clear. A new address closes the old one at
  once. An address that does not lead to a feed, one that leads to a reseller the shop no longer allows and
  one with no file yet all answer the same 404, and a connection that asks for many wrong ones is slowed.
- **The files are in the site's private folder**, not File records: two resellers can hold the same bytes and
  File shares the file on disk between records with the same content, so the refresh of one would have
  deleted the other's. Written beside the old one and moved over it: a reader never sees half a file.
- **A failed refresh leaves the last good file in service.** The status says Failed, the address keeps
  answering with the file of the previous run.
- **Only `customers` or `none` as the price mode**: the address is a secret that can leak, and what a reseller
  pays is worth more to a competitor than what they sell at.
"""

import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timezone

import frappe
from frappe.utils import add_days, add_to_date, get_datetime, getdate, now_datetime, nowdate
from frappe.website.page_renderers.base_renderer import BaseRenderer
from werkzeug.wrappers import Response

from webshop.webshop.catalogue import access, book, jobs, rows, selection, tables
from webshop.webshop.catalogue import api as brand_api
from webshop.webshop.catalogue.refusals import catalogue_message, feed_message, options_message, selection_message
from webshop.webshop.doctype.reseller_feed.reseller_feed import FAILED, QUEUED, READY, RUNNING
from webshop.webshop.multi_site import get_current_profile_name, site_url
from webshop.webshop.utils import throttle

DOCTYPE = "Reseller Feed"
ADDRESS = re.compile(r"^feeds/reseller/([A-Za-z0-9_-]{20,64})/products\.(csv|json)$")
KINDS = {"csv": "text/csv", "json": "application/json"}
ACTIVE_DAYS = 14  # a feed nobody has read for this long is no longer refreshed each night
REFRESHES_PER_DAY = 6  # saves and refreshes a reseller may ask for in 24 hours
FETCH_RECORDED_MINUTES = 60  # the last read is written at most this often
READS_PER_MINUTE = 120  # per connection
MISSES_PER_TEN_MINUTES = 30  # wrong addresses per connection


def refused(field, message):
	return {"ok": False, "field": field, "message": message}


# ---------------------------------------------------------------------------------------------
# The record and its address


def get_feed(customer, lock=False):
	"""The feed of `customer`, or None. `lock` reads the row FOR UPDATE, so that a request that waited for the
	customer's row works on what the request before it committed, not on the snapshot it took earlier."""
	if not customer or not frappe.db.exists(DOCTYPE, customer):
		return None
	return frappe.get_doc(DOCTYPE, customer, for_update=True) if lock else frappe.get_doc(DOCTYPE, customer)


def new_token():
	return secrets.token_urlsafe(24)


def digest(token):
	return hashlib.sha256(token.encode()).hexdigest()


def address(token, kind):
	return site_url(f"/feeds/reseller/{token}/products.{kind}")


def feed_path(customer, kind):
	"""Where the file is. The name is a hash of the customer: no customer name ever reaches a path."""
	key = hashlib.sha256(customer.encode()).hexdigest()[:32]
	return frappe.get_site_path("private", "feeds", "reseller", f"{key}.{kind}")


def write_file(customer, kind, content):
	"""Write the file beside its place and move it over: a reader sees the old file or the new one."""
	path = feed_path(customer, kind)
	os.makedirs(os.path.dirname(path), exist_ok=True)
	temporary = f"{path}.{secrets.token_hex(4)}.tmp"
	with open(temporary, "wb") as handle:
		handle.write(content)
	os.replace(temporary, path)


def read_file(customer, kind):
	"""The file's bytes, or None when there is none."""
	path = feed_path(customer, kind)
	if not os.path.exists(path):
		return None
	# the path is feed_path() of a customer found in the database: nothing in the request names it
	with open(path, "rb") as handle:  # nosemgrep: frappe-semgrep-rules.rules.security.frappe-security-file-traversal
		return handle.read()


def remove_files(customer):
	for kind in KINDS:
		path = feed_path(customer, kind)
		if os.path.exists(path):
			os.remove(path)


def is_refreshing(customer, lock=False):
	"""Whether a refresh is waiting or running. One that has been for too long lost its worker and is not counted.
	`lock`: see get_feed."""
	since = add_to_date(now_datetime(), minutes=-jobs.STALLED_MINUTES)
	filters = {"name": customer, "status": ["in", [QUEUED, RUNNING]], "modified": [">", since]}
	if lock:
		return bool(frappe.db.get_value(DOCTYPE, filters, "name", for_update=True))
	return bool(frappe.db.exists(DOCTYPE, filters))


def describe(customer):
	"""The feed as its owner's page shows it, or None. The addresses carry the secret: they go to its owner only."""
	doc = get_feed(customer)
	if not doc:
		return None
	token = doc.get_password("token", raise_exception=False)
	try:
		clean = json.loads(doc.selection or "{}")
		options = json.loads(doc.options or "{}")
	except ValueError:
		clean, options = {}, {}
	return {
		"status": doc.status,
		"stage": doc.stage,
		"progress": doc.progress,
		"error": doc.error,
		"active": is_refreshing(customer),
		"lines": doc.item_count,
		"generated_on": str(doc.generated_on or ""),
		"prices_as_of": str(doc.prices_as_of or ""),
		"last_fetched": str(doc.last_fetched or ""),
		"served": os.path.exists(feed_path(customer, "csv")),
		"markup_percent": options.get("markup_percent"),
		"prices": options.get("prices"),
		"groups": len(clean.get("item_groups") or []),
		"brands": len(clean.get("brands") or []),
		"products": len(clean.get("items") or []),
		"addresses": {kind: address(token, kind) for kind in KINDS} if token else {},
	}


# ---------------------------------------------------------------------------------------------
# Asking for a feed


def _spend_refresh(customer):
	"""Count one save or refresh of this customer; False when the day's allowance is spent."""
	return throttle.hit("feed-refresh", customer, 86400) <= REFRESHES_PER_DAY


def _queue(customer):
	frappe.db.set_value(DOCTYPE, customer, {"status": QUEUED, "progress": 0, "stage": "", "error": ""})
	frappe.enqueue(
		"webshop.webshop.catalogue.feed.refresh",
		queue="long",
		timeout=jobs.JOB_TIMEOUT,
		enqueue_after_commit=True,
		customer=customer,
	)


def save(customer, payload, picked, options):
	"""Make the feed of `customer`, or change what it is made from (its address stays). Returns None once the
	refresh is queued, else a refusal {"ok": False, "field", "message"} in the reseller's words."""
	try:
		clean_options = rows.clean_options(
			options, payload["values"]["default_markup_percent"], modes=rows.FEED_PRICE_MODES
		)
	except book.OptionsRefused as refusal:
		return refused(refusal.field, options_message(refusal.field, refusal.reason))
	if not payload["saved"] and clean_options["prices"] == "customers":
		return refused(None, feed_message("no_brand"))
	try:
		clean = selection.clean_selection(picked)
	except selection.SelectionRefused as refusal:
		return refused("selection", selection_message(refusal.reason))
	count = rows.count_lines(clean)
	if count > rows.MAX_ROWS:
		return refused("selection", catalogue_message("too_many_rows", rows.MAX_ROWS))
	if not count:
		return refused("selection", catalogue_message("empty"))
	# two clicks at once: the second waits here for the first to commit, then sees it
	frappe.db.get_value("Customer", customer, "name", for_update=True)
	if is_refreshing(customer, lock=True):
		return refused(None, feed_message("busy"))
	if not _spend_refresh(customer):
		return refused(None, feed_message("refresh_limit", REFRESHES_PER_DAY))
	doc = get_feed(customer, lock=True)
	if not doc:
		# a feed stopped while its refresh was still running can leave a file behind: a new feed starts with none
		remove_files(customer)
		doc = frappe.new_doc(DOCTYPE)
		doc.customer = customer
		token = new_token()
		doc.token = token
		doc.token_hash = digest(token)
	doc.selection = json.dumps(clean)
	doc.options = json.dumps(clean_options)
	doc.website_profile = get_current_profile_name() or ""
	doc.flags.ignore_permissions = True
	doc.save()
	_queue(customer)
	return None


def refresh_now(customer):
	"""The button: make the file again from the same choices, prices computed again. None, or a refusal."""
	if not get_feed(customer):
		return refused(None, feed_message("none"))
	frappe.db.get_value("Customer", customer, "name", for_update=True)
	if is_refreshing(customer, lock=True):
		return refused(None, feed_message("busy"))
	if not _spend_refresh(customer):
		return refused(None, feed_message("refresh_limit", REFRESHES_PER_DAY))
	_queue(customer)
	return None


def rotate(customer):
	"""A new secret address; the old one answers 404 from this moment. None, or a refusal."""
	doc = get_feed(customer)
	if not doc:
		return refused(None, feed_message("none"))
	token = new_token()
	doc.token = token
	doc.token_hash = digest(token)
	doc.flags.ignore_permissions = True
	doc.save()
	return None


def delete(customer):
	if frappe.db.exists(DOCTYPE, customer):
		frappe.delete_doc(DOCTYPE, customer, ignore_permissions=True, force=True)


# ---------------------------------------------------------------------------------------------
# The refresh


def _set(customer, **values):
	"""Write fields of the record without touching `modified`, and commit: the page reads them as they come."""
	frappe.db.set_value(DOCTYPE, customer, values, update_modified=False)
	frappe.db.commit()


def _stopped(customer):
	"""Whether the feed was stopped while its refresh ran. The job reads in one long transaction: ending it first
	is what lets the next read see a deletion committed since."""
	frappe.db.commit()
	return not frappe.db.exists(DOCTYPE, customer)


def refresh(customer):
	"""Write the files of the feed of `customer`. Does nothing for a feed that is not waiting for it."""
	doc = get_feed(customer)
	if not doc or doc.status != QUEUED:
		return
	_set(customer, status=RUNNING, progress=1, stage="start", error="")
	try:
		# a job starts in English, whatever the site speaks: the sentence a failure leaves reads in its owner's language
		frappe.set_user_lang(doc.owner)
		if not access.offered_to(customer):
			_set(customer, status=FAILED, error=feed_message("not_offered"))
			return
		jobs.pin_site(doc)
		payload = brand_api._payload(customer)
		clean = selection.clean_selection(doc.selection)
		options = rows.clean_options(
			json.loads(doc.options or "{}"), payload["values"]["default_markup_percent"], modes=rows.FEED_PRICE_MODES
		)
		report = jobs.reporter(customer, jobs.TABLE_STAGES, _set)
		data = rows.build_rows(customer, payload, clean, options, report)
		report("file", 0, 1)
		if _stopped(customer):
			return
		stamp = now_datetime()
		# the JSON says when it was made with its offset: the site's clock is not the reader's
		made_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
		write_file(customer, "csv", tables.csv_bytes(data))
		write_file(customer, "json", tables.json_bytes(data, generated_on=made_at))
		if _stopped(customer):
			remove_files(customer)
			return
		_set(
			customer,
			status=READY,
			progress=100,
			stage="",
			item_count=len(data.rows),
			generated_on=stamp,
			prices_as_of=data.prices_as_of,
		)
	except book.CatalogueRefused as refusal:
		frappe.db.rollback()
		_set(customer, status=FAILED, error=catalogue_message(refusal.reason, jobs.NUMBERS.get(refusal.reason)))
	except Exception:
		frappe.db.rollback()
		frappe.log_error("Reseller feed failed", frappe.get_traceback())
		_set(customer, status=FAILED, error=feed_message("failed"))


def refresh_all():
	"""Each night: queue a refresh for the feeds that are being read (or are new), whoever the shop still allows.
	A feed nobody has read for ACTIVE_DAYS keeps its last file and costs nothing. Also closes a refresh that lost
	its worker."""
	since = add_to_date(now_datetime(), minutes=-jobs.STALLED_MINUTES)
	for name in frappe.get_all(
		DOCTYPE, filters={"status": ["in", [QUEUED, RUNNING]], "modified": ["<", since]}, pluck="name"
	):
		frappe.set_user_lang(frappe.db.get_value(DOCTYPE, name, "owner"))
		frappe.db.set_value(
			DOCTYPE, name, {"status": FAILED, "error": feed_message("stalled"), "stage": ""}, update_modified=False
		)
	frappe.db.commit()
	cutoff = getdate(add_days(nowdate(), -ACTIVE_DAYS))
	for row in frappe.get_all(DOCTYPE, fields=["name", "creation", "last_fetched", "status"]):
		read = row.last_fetched and getdate(row.last_fetched) >= cutoff
		new = getdate(row.creation) >= cutoff
		if row.status in (QUEUED, RUNNING) or not (read or new) or not access.offered_to(row.name):
			continue
		_queue(row.name)
		frappe.db.commit()


# ---------------------------------------------------------------------------------------------
# The route


class FeedRenderer(BaseRenderer):
	"""/feeds/reseller/<token>/products.csv|json: the file the last refresh wrote for the feed behind the token."""

	def can_render(self):
		return bool(ADDRESS.match(self.path))

	def render(self):
		counted = bool(getattr(frappe.local, "request", None))
		if counted and throttle.hit("feed-read", throttle.peer_ip(), 60) > READS_PER_MINUTE:
			return Response(status=429)
		token, kind = ADDRESS.match(self.path).groups()
		customer = frappe.db.get_value(DOCTYPE, {"token_hash": digest(token)}, "name")
		content = read_file(customer, kind) if customer and access.offered_to(customer) else None
		if content is None:
			if counted and throttle.hit("feed-miss", throttle.peer_ip(), 600) > MISSES_PER_TEN_MINUTES:
				return Response(status=429)
			return Response(status=404)
		etag = '"' + hashlib.sha256(content).hexdigest()[:32] + '"'
		if self.header("If-None-Match") == etag:
			response = Response(status=304)
		else:
			response = Response(content, content_type=f"{KINDS[kind]}; charset=utf-8")
			response.headers["Content-Disposition"] = f'inline; filename="products.{kind}"'
		response.headers["ETag"] = etag
		response.headers["Cache-Control"] = "private, max-age=300"
		response.headers["X-Robots-Tag"] = "noindex, nofollow"
		self.record_read(customer)
		return response

	@staticmethod
	def header(name):
		return frappe.get_request_header(name) if getattr(frappe.local, "request", None) else None

	@staticmethod
	def record_read(customer):
		"""Write when the feed was last read, to the hour: a GET is never committed by Frappe, and a write for every
		read would be a lock for every importer."""
		last = frappe.db.get_value(DOCTYPE, customer, "last_fetched")
		if last and get_datetime(last) > add_to_date(now_datetime(), minutes=-FETCH_RECORDED_MINUTES):
			return
		frappe.db.set_value(DOCTYPE, customer, "last_fetched", now_datetime(), update_modified=False)
		frappe.db.commit()
