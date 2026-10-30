# //// Neoffice — added file (no upstream equivalent).
"""The reseller's brand page: read it, save it, send a logo, and see what a markup does to prices.

Open to the customers of the groups the shop allowed, and to nobody else (`access.require_reseller`
starts every endpoint). Identity comes from the session: no endpoint takes a customer, and a
`customer` key slipped into the values is dropped by `brand.clean_brand`. Prices are computed here,
from the price list of the customer, with the markup the page asks to try: the browser never sends a
price. A refusal of what a person typed answers `{"ok": false, "field", "message"}` so the page can
put it beside the field; a refusal of permission raises.
"""

import base64
import binascii
import html

import frappe
from frappe import _
from frappe.utils import fmt_money

from webshop.webshop.catalogue import access, brand, logo, markup
from webshop.webshop.catalogue.refusals import brand_message, logo_message
from webshop.webshop.doctype.reseller_catalogue_profile.reseller_catalogue_profile import (
	BRAND_FIELDS,
	application_defaults,
)
from webshop.webshop.product_data_engine.catalogue_scope import visible_item_filters
from webshop.webshop.utils import customer_pricing

DOCTYPE = "Reseller Catalogue Profile"
# the price preview shows SAMPLE_SIZE products. A customer's price costs about 21 ms an item (measured
# on osiris, 42 pricing rules): products are priced SAMPLE_CHUNK at a time and the scan stops as soon as
# enough are priced, so a keystroke in the markup field costs a fraction of a second, not a catalogue.
SAMPLE_SIZE = 5
SAMPLE_CHUNK = 10
SAMPLE_SCAN_MAX = 50
PRICED_CODES_MAX = 1000
# a logo of 2 MB is 2.8 MB once written in base64: refuse a longer body before decoding it
MAX_LOGO_BASE64 = 3 * 1024 * 1024


def _refused(field, message):
	return {"ok": False, "field": field, "message": message}


def _profile(customer, create=False):
	"""The customer's profile document, created from the starting values when asked."""
	if frappe.db.exists(DOCTYPE, customer):
		return frappe.get_doc(DOCTYPE, customer)
	if not create:
		return None
	doc = frappe.new_doc(DOCTYPE)
	doc.customer = customer
	for field, value in starting_values(customer).items():
		doc.set(field, value)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc


def starting_values(customer):
	"""What the form shows to a customer who has no profile yet: neutral defaults, the customer's name,
	and whatever their approved account request already said about the company."""
	values = dict(brand.DEFAULTS)
	values["brand_name"] = frappe.db.get_value("Customer", customer, "customer_name") or customer
	values.update(application_defaults(customer))
	return values


def _plain(value):
	"""A text as the reseller typed it. Frappe stores a Data field with its HTML characters escaped (`&`
	becomes `&amp;`), as it does a product's name; the form, the sheets and the catalogues print what was typed."""
	return html.unescape(value) if isinstance(value, str) else value


def _values(profile, customer):
	values = _stored_values(profile, customer)
	for field in (*brand.TEXT_LIMITS, brand.ADDRESS_FIELD):
		values[field] = _plain(values.get(field))
	return values


def _stored_values(profile, customer):
	if not profile:
		return starting_values(customer)
	values = {field: profile.get(field) for field in BRAND_FIELDS}
	for field, default in brand.DEFAULTS.items():
		if values.get(field) in (None, ""):
			values[field] = default
	values["default_markup_percent"] = float(values["default_markup_percent"])
	values["vat_rate"] = float(values["vat_rate"])
	return values


def _logo_files(profile):
	return frappe.get_all(
		"File",
		filters={"attached_to_doctype": DOCTYPE, "attached_to_name": profile.name, "attached_to_field": "logo"},
		pluck="name",
	)


def _logo_data_url(profile):
	"""The logo as a data URL, or None. A private file cannot be linked from the page (the customer has no
	read permission on the profile), so the page is handed the pixels."""
	if not profile or not profile.logo:
		return None
	names = _logo_files(profile)
	if not names:
		return None
	content = frappe.get_doc("File", names[0]).get_content()
	if not content or len(content) > logo.MAX_BYTES:
		return None
	return "data:image/png;base64," + base64.b64encode(content).decode("ascii")


def _inks(values):
	return {
		"primary": brand.readable_ink(values["primary_colour"]),
		"secondary": brand.readable_ink(values["secondary_colour"]),
	}


def _payload(customer):
	profile = _profile(customer)
	values = _values(profile, customer)
	return {
		"ok": True,
		"customer": customer,
		"saved": bool(profile),
		"values": values,
		"logo": _logo_data_url(profile),
		"ink": _inks(values),
		"credit_line": _plain((access.shop_settings().get("catalogue_credit_text") or "").strip()),
		"roundings": list(markup.ROUNDINGS),
		"displays": list(brand.PRICE_DISPLAYS),
		"max_markup": float(markup.MAX_MARKUP_PERCENT),
	}


@frappe.whitelist()
def get_my_brand():
	return _payload(access.require_reseller())


@frappe.whitelist(methods=["POST"])
def save_my_brand(values=None):
	customer = access.require_reseller()
	values = frappe.parse_json(values) if isinstance(values, str) else values
	if not isinstance(values, dict):
		return _refused(None, _("Nothing to save."))
	try:
		clean = brand.clean_brand(values)
	except brand.BrandRefused as refusal:
		return _refused(refusal.field, brand_message(refusal.field, refusal.reason))
	profile = _profile(customer, create=True)
	profile.update(clean)
	profile.flags.ignore_permissions = True
	profile.save()
	return _payload(customer)


def _drop_logo_files(profile, keep=None):
	for name in _logo_files(profile):
		if name != keep:
			frappe.delete_doc("File", name, ignore_permissions=True, force=True)


@frappe.whitelist(methods=["POST"])
def upload_my_logo(content=None):
	"""`content`: the file, as base64 or a data URL. Kept as a private PNG built from its pixels."""
	customer = access.require_reseller()
	if not isinstance(content, str) or not content:
		return _refused("logo", logo_message("not_an_image"))
	if len(content) > MAX_LOGO_BASE64:
		return _refused("logo", logo_message("too_large"))
	body = content.split(",", 1)[1] if content.startswith("data:") and "," in content else content
	try:
		raw = base64.b64decode(body, validate=True)
		png = logo.clean_logo(raw)
	except (binascii.Error, ValueError) as error:
		reason = error.reason if isinstance(error, logo.LogoRefused) else "not_an_image"
		return _refused("logo", logo_message(reason))
	profile = _profile(customer, create=True)
	new_file = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"logo-{frappe.generate_hash(length=10)}.png",
			"content": png,
			"is_private": 1,
			"attached_to_doctype": DOCTYPE,
			"attached_to_name": profile.name,
			"attached_to_field": "logo",
		}
	)
	new_file.flags.ignore_permissions = True
	new_file.insert()
	profile.db_set("logo", new_file.file_url)
	_drop_logo_files(profile, keep=new_file.name)
	return _payload(customer)


@frappe.whitelist(methods=["POST"])
def remove_my_logo():
	customer = access.require_reseller()
	profile = _profile(customer)
	if profile:
		_drop_logo_files(profile)
		profile.db_set("logo", "")
	return _payload(customer)


@frappe.whitelist()
def preview_prices(
	markup_percent=None, price_rounding=None, price_display=None, vat_rate=None, primary_colour=None, secondary_colour=None
):
	"""A few of the shop's products at the price THIS customer pays, and at the price they would sell at
	with the markup being tried. The price list is the customer's, resolved the way the cart resolves it:
	this is the proof, on screen, that a catalogue prints the figure the customer is charged."""
	customer = access.require_reseller()
	profile = _profile(customer)
	current = _values(profile, customer)
	asked = {
		"default_markup_percent": markup_percent,
		"price_rounding": price_rounding,
		"price_display": price_display,
		"vat_rate": vat_rate,
		"primary_colour": primary_colour,
		"secondary_colour": secondary_colour,
	}
	try:
		clean = brand.clean_brand({field: value for field, value in asked.items() if value not in (None, "")})
	except brand.BrandRefused as refusal:
		return _refused(refusal.field, brand_message(refusal.field, refusal.reason))
	current.update(clean)

	settings = access.shop_settings()
	party = frappe.get_cached_doc("Customer", customer)
	price_list = customer_pricing.customer_price_list(settings, party)
	currency = customer_pricing.currency_of(price_list)
	# the products this customer's list prices at all: a list that prices a handful of products would
	# otherwise show nothing, those few rarely being among the newest of the shop
	priced_codes = frappe.get_all(
		"Item Price",
		filters={"price_list": price_list, "selling": 1},
		pluck="item_code",
		distinct=True,
		limit=PRICED_CODES_MAX,
	)
	items = []
	if priced_codes:
		items = frappe.get_all(
			"Website Item",
			filters={**visible_item_filters(), "item_code": ["in", priced_codes]},
			fields=["item_code", "web_item_name"],
			order_by="modified desc",
			limit=SAMPLE_SCAN_MAX,
		)
	including_vat = current["price_display"] == "Including VAT"
	rows = []
	for start in range(0, len(items), SAMPLE_CHUNK):
		chunk = items[start : start + SAMPLE_CHUNK]
		priced = customer_pricing.prices_for([item.item_code for item in chunk], price_list, party, settings)
		for item in chunk:
			cost = (priced.get(item.item_code) or {}).get("price")
			if cost is None:
				continue
			selling = markup.selling_price(
				cost, current["default_markup_percent"], current["price_rounding"], current["vat_rate"], including_vat
			)
			rows.append(
				{
					"item_code": item.item_code,
					"name": item.web_item_name or item.item_code,
					"cost": fmt_money(cost, currency=currency),
					"price": fmt_money(float(selling), currency=currency),
				}
			)
			if len(rows) == SAMPLE_SIZE:
				break
		if len(rows) == SAMPLE_SIZE:
			break
	return {
		"ok": True,
		"price_list": price_list,
		"currency": currency,
		"rows": rows,
		"ink": _inks(current),
	}
