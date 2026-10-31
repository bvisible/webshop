# //// Neoffice — added file (no upstream equivalent).
"""A finished catalogue, handed to somebody without a login: a link that expires, and an e-mail that carries it.

A reseller sends their catalogue to a customer who has no account here. Two ways, both started by the reseller and never
by the shop: a link (`/shared-catalogue/<secret>`, the file served as it was made, for a few days) and an e-mail that
holds the link (never the file: a PDF of 3 MB is a bad attachment, and a link can be stopped).

What a link may serve is what the catalogue is made for: a PDF, which carries the reseller's selling prices, or a file
without the price they pay. **A file that carries what the reseller pays (`tariff`, `both`) is never shared**: the address is
a secret that gets forwarded, and what a reseller pays is worth more to a competitor than what they sell at (the feed
refuses the same modes, for the same reason).

The secret is 24 random bytes. The table keeps its SHA-256 (to find the catalogue) and, encrypted, the secret itself, so
that the page can show the link again; stopping the share deletes both. A wrong, expired, stopped or deleted link is the same
404, and a connection that asks for many wrong ones is slowed.
"""

import hashlib
import json
import re
from html import escape

import frappe
from frappe import _
from frappe.utils import add_days, add_to_date, get_datetime, getdate, nowdate, now_datetime
from frappe.utils.password import delete_all_passwords_for
from frappe.website.page_renderers.base_renderer import BaseRenderer
from werkzeug.wrappers import Response

from webshop.webshop.assistant.escalation import single_email
from webshop.webshop.catalogue import access, feed, jobs
from webshop.webshop.doctype.reseller_catalogue.reseller_catalogue import CSV, PDF, READY, SHOPIFY, XLSX
from webshop.webshop.multi_site import site_url
from webshop.webshop.utils import throttle

DOCTYPE = jobs.DOCTYPE
ADDRESS = re.compile(r"^shared-catalogue/([A-Za-z0-9_-]{20,64})$")
SHARE_DAYS = (7, 14, 30)
DEFAULT_DAYS = 14
READS_PER_MINUTE = 60  # per connection
MISSES_PER_TEN_MINUTES = 30  # wrong links per connection
OPENED_RECORDED_MINUTES = 60
MAILS_PER_DAY = 20  # e-mails a reseller may send in 24 hours
MAILS_PER_RECIPIENT = 3  # to one address, in 24 hours
MESSAGE_MAX = 500
SHAREABLE_PRICES = ("customers", "none")
MIMETYPES = {
	PDF: "application/pdf",
	XLSX: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
	CSV: "text/csv",
	SHOPIFY: "text/csv",
}


class ShareRefused(ValueError):
	"""Why a share or a mail was refused: a code the caller words (`refusals.share_message`)."""

	def __init__(self, reason, number=None):
		super().__init__(reason)
		self.reason = reason
		self.number = number


def digest(token):
	return hashlib.sha256(token.encode()).hexdigest()


def _prices(doc):
	try:
		return (json.loads(doc.options or "{}")).get("prices")
	except ValueError:
		return None


def sharable(doc):
	"""Whether this catalogue may have a link: finished, and carrying no price the reseller pays."""
	if doc.status != READY:
		return False
	return (doc.get("format") or PDF) == PDF or _prices(doc) in SHAREABLE_PRICES


def _lock(customer, name):
	"""The catalogue of `customer`, read FOR UPDATE (two clicks at once work on what the first committed)."""
	found = frappe.db.get_value(DOCTYPE, {"name": name or "", "customer": customer}, "name", for_update=True) if isinstance(name, str) else None
	if not found:
		raise frappe.DoesNotExistError
	return frappe.get_doc(DOCTYPE, found, for_update=True)


def share(customer, name, days=None):
	"""Give the catalogue a link, or a new one (the old stops at once). Returns the description of the link."""
	try:
		days = DEFAULT_DAYS if days in (None, "") else int(days)
	except (TypeError, ValueError):
		raise ShareRefused("bad_days") from None
	if days not in SHARE_DAYS:
		raise ShareRefused("bad_days")
	doc = _lock(customer, name)
	if not sharable(doc):
		raise ShareRefused("not_sharable" if doc.status == READY else "not_ready")
	token = feed.new_token()
	doc.share_token = token
	doc.share_hash = digest(token)
	# never beyond the catalogue's own life: it is deleted then, and the link with it
	doc.share_expires_on = min(getdate(add_days(nowdate(), days)), getdate(doc.expires_on)) if doc.expires_on else add_days(nowdate(), days)
	doc.share_opened_on = None
	doc.flags.ignore_permissions = True
	doc.save()
	return describe(doc.name)


def unshare(customer, name):
	"""Stop the link: it answers 404 from this moment."""
	doc = _lock(customer, name)
	doc.share_hash = None
	doc.share_expires_on = None
	doc.share_opened_on = None
	doc.flags.ignore_permissions = True
	doc.save()
	delete_all_passwords_for(DOCTYPE, doc.name)


def describe(name):
	"""The link of a catalogue as its owner's page shows it, or None. The address carries the secret: owner only."""
	row = frappe.db.get_value(DOCTYPE, name, ["share_hash", "share_expires_on", "share_opened_on"], as_dict=True)
	if not row or not row.share_hash:
		return None
	token = frappe.get_doc(DOCTYPE, name).get_password("share_token", raise_exception=False)
	if not token:
		return None
	return {
		"url": site_url(f"shared-catalogue/{token}"),
		"expires_on": str(row.share_expires_on or ""),
		"opened_on": str(row.share_opened_on or ""),
		"expired": bool(row.share_expires_on and getdate(row.share_expires_on) < getdate(nowdate())),
	}


# ---------------------------------------------------------------------------------------------
# The link, read by whoever holds it


def _file_of(name):
	names = frappe.get_all(
		"File", filters={"attached_to_doctype": DOCTYPE, "attached_to_name": name, "attached_to_field": "file"}, pluck="name"
	)
	return frappe.get_doc("File", names[0]).get_content() if names else None


class ShareRenderer(BaseRenderer):
	"""/shared-catalogue/<secret>: the file of the catalogue behind the secret, while its link lives."""

	def can_render(self):
		return bool(ADDRESS.match(self.path))

	def render(self):
		counted = bool(getattr(frappe.local, "request", None))
		if counted and throttle.hit("share-read", throttle.peer_ip(), 60) > READS_PER_MINUTE:
			return Response(status=429)
		token = ADDRESS.match(self.path).group(1)
		found = self.find(token)
		if not found:
			if counted and throttle.hit("share-miss", throttle.peer_ip(), 600) > MISSES_PER_TEN_MINUTES:
				return Response(status=429)
			return Response(status=404)
		row, content = found
		fmt = row.format or PDF
		response = Response(content, content_type=MIMETYPES[fmt])
		disposition = "inline" if fmt == PDF else "attachment"
		response.headers["Content-Disposition"] = f'{disposition}; filename="{jobs.download_name(row.title, fmt)}"'
		response.headers["Cache-Control"] = "private, max-age=300"
		response.headers["X-Robots-Tag"] = "noindex, nofollow"
		self.record_open(row.name)
		return response

	@staticmethod
	def find(token):
		"""(the catalogue row, its file) while the link lives, else None. Every reason a link is dead looks alike."""
		row = frappe.db.get_value(
			DOCTYPE,
			{"share_hash": digest(token)},
			["name", "customer", "title", "format", "status", "options", "share_expires_on"],
			as_dict=True,
		)
		if not row or row.status != READY or not row.share_expires_on or getdate(row.share_expires_on) < getdate(nowdate()):
			return None
		if not access.offered_to(row.customer) or not sharable(row):
			return None
		content = _file_of(row.name)
		return (row, content) if content else None

	@staticmethod
	def record_open(name):
		"""Write when the link was last opened, to the hour: a GET is never committed by Frappe."""
		last = frappe.db.get_value(DOCTYPE, name, "share_opened_on")
		if last and get_datetime(last) > add_to_date(now_datetime(), minutes=-OPENED_RECORDED_MINUTES):
			return
		frappe.db.set_value(DOCTYPE, name, "share_opened_on", now_datetime(), update_modified=False)
		frappe.db.commit()


# ---------------------------------------------------------------------------------------------
# The e-mail


def _plain(text):
	"""The reseller's words as one block of plain text: no control characters, no markup, a bounded length."""
	text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
	return text


def send(customer, payload, name, to, message=None):
	"""Send the link of a catalogue to one address, in the reseller's name. A ShareRefused, or None once queued.

	The reseller clicks; nothing is sent by itself. The shop is the sender (its own outgoing account) and the reseller's contact
	address is where a reply goes. The link is made when there is none."""
	address = single_email(to)
	if not address:
		raise ShareRefused("bad_email")
	message = _plain(message)
	if len(message) > MESSAGE_MAX:
		raise ShareRefused("message_too_long", MESSAGE_MAX)
	if throttle.hit("catalogue-mail", customer, 86400) > MAILS_PER_DAY:
		raise ShareRefused("mail_limit", MAILS_PER_DAY)
	if throttle.hit("catalogue-mail-to", hashlib.sha256(f"{customer}:{address.lower()}".encode()).hexdigest(), 86400) > MAILS_PER_RECIPIENT:
		raise ShareRefused("mail_limit_to", MAILS_PER_RECIPIENT)
	doc = _lock(customer, name)
	if not sharable(doc):
		raise ShareRefused("not_sharable" if doc.status == READY else "not_ready")
	link = describe(doc.name)
	if not link or link["expired"]:
		link = share(customer, name)
	values = payload["values"]
	brand = values.get("brand_name") or customer
	reply_to = values.get("contact_email") or frappe.db.get_value("User", frappe.session.user, "email")
	body = "".join(
		[
			f"<p>{escape(message).replace(chr(10), '<br>')}</p>" if message else "",
			f'<p><a href="{escape(link["url"], quote=True)}">{escape(doc.title)}</a></p>',
			"<p style=\"color:#6b7280;font-size:12px\">",
			escape(_("This link shows the catalogue until {0}.").format(link["expires_on"])),
			"<br>",
			escape(_("Sent by {0}.").format(brand)),
			"</p>",
		]
	)
	if not _queue_mail(recipients=[address], reply_to=reply_to, subject=_("{0}: {1}", context="Subject of the e-mail that carries a reseller's catalogue").format(brand, doc.title), message=body, reference_doctype=DOCTYPE, reference_name=doc.name):
		raise ShareRefused("mail_failed")
	return None


def _queue_mail(**kwargs):
	"""Queue the mail without letting the shop's mail-server error reach the reseller's browser as a modal."""
	saved = list(frappe.local.message_log or [])
	try:
		frappe.sendmail(**kwargs)
		return True
	except Exception:
		frappe.log_error("Reseller catalogue: mail not sent", frappe.get_traceback())
		return False
	finally:
		frappe.local.message_log = saved
