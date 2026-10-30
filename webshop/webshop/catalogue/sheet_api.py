# //// Neoffice — added file (no upstream equivalent).
"""The product sheet's two doors: the shop's, open to a visitor; the reseller's, open to a reseller.

The shop's sheet says what the page says, to anybody, so a visitor may ask for it (throttled per connection:
a sheet costs one render of the shared Chromium). The reseller's sheet is made in their own name from their
saved brand, with their price, so it is open only to the customers of the groups the shop allowed
(`access.require_reseller`), and the identity is the account's: no argument names a customer.

Both answer a PDF the browser shows or saves. The sheet is never indexed (`X-Robots-Tag`): a copy of a
page, its price included, would be a duplicate of it. The shop's is kept five minutes for a visitor, since
every visitor is shown the same page; the reseller's is never kept by anyone but them.
"""

import hashlib
import re
import unicodedata

import frappe
from frappe import _
from frappe.utils import cint
from werkzeug.wrappers import Response

from webshop.webshop.catalogue import access, sheet
from webshop.webshop.catalogue import api as brand_api
from webshop.webshop.catalogue.pdf import chromium_available, render_pdf
from webshop.webshop.utils import throttle

CACHE_SECONDS = 300


def _filename(name):
	"""A name any browser saves: ASCII letters, digits and dashes."""
	ascii_name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
	return (re.sub(r"[^A-Za-z0-9]+", "-", ascii_name).strip("-")[:60] or "product-sheet") + ".pdf"


def _response(pdf, name, private):
	response = Response(pdf, mimetype="application/pdf")
	response.headers["Content-Disposition"] = f'inline; filename="{_filename(name)}"'
	response.headers["X-Robots-Tag"] = "noindex"
	response.headers["Cache-Control"] = "private, no-store" if private else f"public, max-age={CACHE_SECONDS}"
	return response


def make_pdf(data):
	"""The PDF of a built sheet. A bench without the Chrome PDF generator cannot make one, and says so."""
	if not chromium_available():
		frappe.throw(_("Product sheets are not available on this site."))
	try:
		return render_pdf(sheet.render_html(data))
	except Exception:
		frappe.log_error("Product sheet could not be rendered", frappe.get_traceback())
		frappe.throw(_("The sheet could not be made. Try again in a moment."))


def _shop_cache_key(doc):
	"""What makes two visitors' sheets identical: the product as last saved, the language, the site, the day."""
	parts = [doc.name, str(doc.modified), frappe.local.lang, str(getattr(frappe.local, "website_profile", "")), frappe.utils.nowdate()]
	return "webshop_product_sheet:" + hashlib.sha256("|".join(parts).encode()).hexdigest()


@frappe.whitelist(allow_guest=True, methods=["GET"])  # nosemgrep: frappe-semgrep-rules.rules.security.guest-whitelisted-method -- open to visitors on purpose: the sheet says what the product page says; throttled per connection, never indexed
@throttle.throttle("sheet", 20, 60)
def product_sheet(item=None):
	if not cint(frappe.get_cached_doc("Webshop Settings").get("enable_product_sheet")):
		raise frappe.DoesNotExistError
	doc = sheet.find_item(item)
	if not doc:
		raise frappe.DoesNotExistError
	# every visitor is shown the same page; a signed-in customer may be shown their own price list
	key = _shop_cache_key(doc) if frappe.session.user == "Guest" else None
	pdf = frappe.cache.get_value(key) if key else None
	if not pdf:
		pdf = make_pdf(sheet.build_sheet(doc))
		if key:
			frappe.cache.set_value(key, pdf, expires_in_sec=CACHE_SECONDS)
	return _response(pdf, doc.web_item_name or doc.item_code, private=False)


@frappe.whitelist(methods=["GET"])
@throttle.throttle("my-sheet", 30, 60)
def my_product_sheet(item=None, prices="customers"):
	"""The sheet in the signed-in reseller's name. `prices`: "customers" (their price, markup added) or "none"."""
	customer = access.require_reseller()
	doc = sheet.find_item(item)
	if not doc:
		raise frappe.DoesNotExistError
	payload = brand_api._payload(customer)
	if not payload["saved"]:
		# a brand never saved is the neutral defaults, a markup of 0: the price printed would be the one they pay
		frappe.throw(_("Set up your brand first: your logo, your colours and your markup."))
	data = sheet.build_sheet(
		doc,
		sheet.RESELLER,
		{"payload": payload, "credit_line": payload["credit_line"], "prices": prices != "none"},
	)
	return _response(make_pdf(data), data.name, private=True)
