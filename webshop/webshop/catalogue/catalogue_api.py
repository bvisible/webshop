# //// Neoffice — added file (no upstream equivalent).
"""The reseller's catalogues: ask for one, follow it, download it, make it again, delete it.

Open to the customers of the groups the shop allowed (`access.require_reseller` starts every endpoint) and
to nobody else. Identity comes from the session: no endpoint takes a customer, and a catalogue that is not
the caller's is a 404, the same answer as one that does not exist. The browser sends a title, a selection
(item groups, brands, products) and three options; it never sends a price — every figure printed is computed
by the job, from the reseller's own price list and markup.

A refusal of what a person chose answers `{"ok": false, "field", "message"}` so the page can put it beside the
field; a refusal of permission raises. Making a catalogue takes seconds to a minute: the endpoint only writes
the request and queues the job (`jobs.generate`); the page polls `get_catalogues` for its progress.
"""

import json

import frappe
from werkzeug.wrappers import Response

from webshop.webshop.catalogue import access, book, jobs, selection
from webshop.webshop.catalogue import api as brand_api
from webshop.webshop.catalogue.pdf import chromium_available
from webshop.webshop.catalogue.refusals import catalogue_message, options_message, selection_message
from webshop.webshop.catalogue.sheet_api import _filename
from webshop.webshop.doctype.reseller_catalogue.reseller_catalogue import QUEUED, READY, RUNNING
from webshop.webshop.multi_site import get_current_profile_name
from webshop.webshop.utils import throttle

DOCTYPE = jobs.DOCTYPE
LIST_MAX = 50
FIELDS = [
	"name",
	"title",
	"status",
	"progress",
	"stage",
	"item_count",
	"page_count",
	"generated_on",
	"prices_as_of",
	"expires_on",
	"error",
	"creation",
	"options",
]


def _refused(field, message):
	return {"ok": False, "field": field, "message": message}


def _row(row):
	"""A catalogue as the page shows it: what it is and where it stands, no file path and no selection."""
	options = {}
	try:
		options = json.loads(row.options or "{}")
	except ValueError:
		pass
	out = {field: row.get(field) for field in FIELDS if field != "options"}
	out["prices"] = options.get("prices")
	out["layout"] = options.get("layout")
	out["markup_percent"] = options.get("markup_percent")
	out["active"] = row.status in (QUEUED, RUNNING)
	return out


def _state(customer, payload=None):
	payload = payload or brand_api._payload(customer)
	rows = frappe.get_all(
		DOCTYPE, filters={"customer": customer}, fields=FIELDS, order_by="creation desc", limit=LIST_MAX
	)
	return {
		"ok": True,
		"catalogues": [_row(row) for row in rows],
		"busy": jobs.is_running(customer),
		"brand_saved": payload["saved"],
		"default_markup": payload["values"]["default_markup_percent"],
		"engine": chromium_available(),
		"limits": {
			"products": selection.MAX_PRODUCTS,
			"daily": jobs.DAILY_LIMIT,
			"keep_days": jobs.KEEP_DAYS,
		},
	}


def _owned(customer, name):
	"""The name of the caller's catalogue, or a 404: a foreign catalogue is not told apart from a missing one."""
	found = frappe.db.get_value(DOCTYPE, {"name": name or "", "customer": customer}, "name") if isinstance(name, str) else None
	if not found:
		raise frappe.DoesNotExistError
	return found


def _ask(customer, payload, title, picked, options):
	"""Check a request and, when it holds, write it and queue the job. Returns the new state, or a refusal."""
	if not payload["saved"]:
		return _refused(None, catalogue_message("no_brand"))
	if not chromium_available():
		return _refused(None, catalogue_message("no_engine"))
	try:
		title = book.clean_title(title)
		clean_options = book.clean_options(options, payload["values"]["default_markup_percent"])
	except book.OptionsRefused as refusal:
		return _refused(refusal.field, options_message(refusal.field, refusal.reason))
	try:
		clean = selection.clean_selection(picked)
	except selection.SelectionRefused as refusal:
		return _refused("selection", selection_message(refusal.reason))
	count = selection.count_products(clean)
	if not count:
		return _refused("selection", catalogue_message("empty"))
	if count > selection.MAX_PRODUCTS:
		return _refused("selection", catalogue_message("too_many_products", selection.MAX_PRODUCTS))
	# two clicks at once: the second waits here for the first to commit, then sees it
	frappe.db.get_value("Customer", customer, "name", for_update=True)
	if jobs.is_running(customer):
		return _refused(None, catalogue_message("busy"))
	if jobs.asked_since(customer) >= jobs.DAILY_LIMIT:
		return _refused(None, catalogue_message("daily_limit", jobs.DAILY_LIMIT))
	doc = frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"title": title,
			"customer": customer,
			"status": QUEUED,
			"selection": json.dumps(clean),
			"options": json.dumps(clean_options),
			"website_profile": get_current_profile_name() or "",
			"expires_on": frappe.utils.add_days(frappe.utils.nowdate(), jobs.KEEP_DAYS),
		}
	).insert(ignore_permissions=True)
	jobs.enqueue_generation(doc.name)
	return _state(customer, payload)


def _json(value):
	"""What the browser sent as JSON text, parsed. Text that is not JSON gives None, which the checks refuse in
	their own words (a selection that is not one): a crafted request must not become a server error."""
	if isinstance(value, str):
		try:
			return json.loads(value)
		except ValueError:
			return None
	return value


@frappe.whitelist()
@throttle.throttle("catalogues-state", 90, 60)
def get_catalogues():
	return _state(access.require_reseller())


@frappe.whitelist()
@throttle.throttle("catalogues-choices", 30, 60)
def get_choices():
	"""What the page offers to tick: the shop's item groups and brands, with what each carries."""
	access.require_reseller()
	return {"ok": True, **selection.choices()}


@frappe.whitelist()
@throttle.throttle("catalogues-search", 60, 60)
def search_products(text=None):
	access.require_reseller()
	return {"ok": True, "products": selection.search(text)}


@frappe.whitelist(methods=["POST"])
@throttle.throttle("catalogues-count", 60, 60)
def count_products(picked=None):
	"""How many products a selection holds, so that the page can say so before it is sent."""
	access.require_reseller()
	try:
		clean = selection.clean_selection(_json(picked))
	except selection.SelectionRefused:
		return {"ok": True, "count": 0, "too_many": False}
	count = selection.count_products(clean)
	return {"ok": True, "count": count, "too_many": count > selection.MAX_PRODUCTS}


@frappe.whitelist(methods=["POST"])
@throttle.throttle("catalogues-create", 20, 3600)
def create_catalogue(title=None, picked=None, options=None):
	customer = access.require_reseller()
	return _ask(customer, brand_api._payload(customer), title, _json(picked), _json(options))


@frappe.whitelist(methods=["POST"])
@throttle.throttle("catalogues-create", 20, 3600)
def remake_catalogue(name=None):
	"""A new catalogue from the selection and options of one of the caller's: the prices are computed again."""
	customer = access.require_reseller()
	found = _owned(customer, name)
	old = frappe.db.get_value(DOCTYPE, found, ["title", "selection", "options"], as_dict=True)
	return _ask(customer, brand_api._payload(customer), old.title, _json(old.selection), _json(old.options))


@frappe.whitelist(methods=["POST"])
def delete_catalogue(name=None):
	customer = access.require_reseller()
	found = _owned(customer, name)
	status = frappe.db.get_value(DOCTYPE, found, "status")
	if status in (QUEUED, RUNNING) and jobs.is_running(customer):
		return _refused(None, catalogue_message("busy"))
	frappe.delete_doc(DOCTYPE, found, ignore_permissions=True, force=True)
	return _state(customer)


@frappe.whitelist(methods=["GET"])
@throttle.throttle("catalogues-download", 30, 60)
def download_catalogue(name=None):
	"""The PDF of one of the caller's finished catalogues."""
	customer = access.require_reseller()
	found = _owned(customer, name)
	row = frappe.db.get_value(DOCTYPE, found, ["title", "status"], as_dict=True)
	file_names = frappe.get_all(
		"File", filters={"attached_to_doctype": DOCTYPE, "attached_to_name": found, "attached_to_field": "file"}, pluck="name"
	)
	if row.status != READY or not file_names:
		raise frappe.DoesNotExistError
	content = frappe.get_doc("File", file_names[0]).get_content()
	if not content:
		raise frappe.DoesNotExistError
	response = Response(content, mimetype="application/pdf")
	response.headers["Content-Disposition"] = f'attachment; filename="{_filename(row.title)}"'
	response.headers["X-Robots-Tag"] = "noindex"
	response.headers["Cache-Control"] = "private, no-store"
	return response
