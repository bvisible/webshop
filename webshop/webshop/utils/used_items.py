# //// Neoffice — added file (second-hand feature, no upstream equivalent).
"""Second-hand and refurbished units.

A used unit is a physical object: its own condition, its own photos, its own
price, a quantity of one. So it is its own Item, linked through
`condition_of_item` to the new item it copies. Nothing here is a variant (a
variant is a systematic attribute combination, not a unique object) and nothing
is a serial number (the cart adds items, and there is no price per serial).

The Item carries the condition fields (patches/add_item_condition_fields.py);
Website Item mirrors them (fetch_from). This module is the only place that
knows what the vocabulary means: which values count as second-hand, what Google
and schema.org call them, how a warranty in days reads in months.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

SECOND_HAND_CONDITIONS = ("Second-hand", "Refurbished")

# Google Merchant Center and schema.org share this vocabulary; the shop's
# Select uses the same three words on purpose.
CONDITION_SCHEMA_URL = {
	"New": "https://schema.org/NewCondition",
	"Refurbished": "https://schema.org/RefurbishedCondition",
	"Second-hand": "https://schema.org/UsedCondition",
}

USED_CODE_SUFFIX = "-USED-"


def is_second_hand(condition) -> bool:
	return condition in SECOND_HAND_CONDITIONS


def condition_schema_url(condition) -> str:
	return CONDITION_SCHEMA_URL.get(condition or "New", CONDITION_SCHEMA_URL["New"])


def warranty_months(warranty_days) -> int:
	"""Item.warranty_period is in days; a customer reads months."""
	days = cint(warranty_days)
	return int(round(days / 30.0)) if days else 0


def condition_info(website_item):
	"""What the product page says about a used or refurbished unit, or None."""
	if not is_second_hand(website_item.get("item_condition")):
		return None

	warranty_days = frappe.db.get_value("Item", website_item.item_code, "warranty_period")
	info = frappe._dict(
		condition=website_item.item_condition,
		grade=website_item.get("condition_grade"),
		details=website_item.get("condition_details"),
		warranty_months=warranty_months(warranty_days),
		reference=None,
	)

	reference_item = website_item.get("condition_of_item")
	if reference_item:
		from webshop.webshop.multi_site import excluded_item_names

		reference = frappe.db.get_value(
			"Website Item",
			{"item_code": reference_item, "published": 1},
			["name", "route", "web_item_name"],
			as_dict=True,
		)
		if reference and reference.name not in excluded_item_names():
			info.reference = reference
	return info


def get_used_units(item_code, limit=6):
	"""Published second-hand units of a new item, in stock, cheapest first."""
	from erpnext.utilities.product import get_price

	from webshop.webshop.multi_site import effective_price_list, excluded_item_names
	from webshop.webshop.utils.product import get_web_item_qty_in_stock
	from webshop.webshop.utils.utils import format_currency_value

	settings = frappe.get_cached_doc("Webshop Settings")
	units = frappe.get_all(
		"Website Item",
		filters={
			"published": 1,
			"condition_of_item": item_code,
			"item_condition": ("in", SECOND_HAND_CONDITIONS),
		},
		fields=[
			"name",
			"item_code",
			"web_item_name",
			"route",
			"website_image",
			"thumbnail",
			"item_condition",
			"condition_grade",
			"website_warehouse",
		],
	)
	excluded = set(excluded_item_names())
	price_list = effective_price_list(settings.price_list)
	out = []
	for unit in units:
		if unit.name in excluded:
			continue
		stock = get_web_item_qty_in_stock(unit.item_code, "website_warehouse", unit.website_warehouse)
		if not (stock and stock.in_stock):
			continue
		price = get_price(unit.item_code, price_list, settings.default_customer_group, settings.company)
		unit.price = flt(price.get("price_list_rate")) if price else 0
		unit.currency = price.get("currency") if price else None
		unit.formatted_price = (
			format_currency_value(unit.price, currency=unit.currency) if unit.price else None
		)
		out.append(unit)

	out.sort(key=lambda u: (u.price or 0))
	return out[:limit]


def next_used_item_code(item_code: str) -> str:
	"""ITEM-USED-01, ITEM-USED-02… the first code not taken."""
	n = frappe.db.count("Item", {"name": ("like", f"{item_code}{USED_CODE_SUFFIX}%")})
	while True:
		n += 1
		candidate = f"{item_code}{USED_CODE_SUFFIX}{n:02d}"
		if not frappe.db.exists("Item", candidate):
			return candidate


def _default_warehouse(source, company):
	website_warehouse = frappe.db.get_value(
		"Website Item", {"item_code": source.item_code}, "website_warehouse"
	)
	if website_warehouse:
		return website_warehouse
	for row in source.get("item_defaults") or []:
		if row.default_warehouse and (not company or row.company == company):
			return row.default_warehouse
	return frappe.db.get_single_value("Stock Settings", "default_warehouse")


@frappe.whitelist()
def create_used_unit(
	item_code,
	price,
	condition="Second-hand",
	grade=None,
	details=None,
	qty=1,
	cost=0,
	warranty_days=365,
	warehouse=None,
	publish=1,
):
	"""One click on the new item's form: a used unit, priced, in stock, published.

	Copies the Item (so taxes, UOMs, defaults and group follow), gives it its
	own code and condition, an Item Price on the shop's list, a Material
	Receipt for the unit, and a Website Item seeded from the new item's page.
	The photos are deliberately NOT the new item's: the caller is told to
	upload the unit's own pictures.
	"""
	frappe.has_permission("Item", "create", throw=True)
	if not is_second_hand(condition):
		frappe.throw(_("A second-hand unit is Second-hand or Refurbished."))

	source = frappe.get_doc("Item", item_code)
	if source.has_variants:
		frappe.throw(_("Create the used unit from a specific variant, not from the template."))

	price, cost, qty = flt(price), flt(cost), flt(qty)
	if price <= 0:
		frappe.throw(_("A selling price is required."))

	unit = frappe.copy_doc(source)
	unit.item_code = next_used_item_code(source.item_code)
	unit.item_name = (
		_("{0} (second-hand)").format(source.item_name)
		if condition == "Second-hand"
		else _("{0} (refurbished)").format(source.item_name)
	)
	unit.variant_of = None
	unit.has_variants = 0
	unit.set("attributes", [])
	unit.set("barcodes", [])
	unit.opening_stock = 0
	unit.standard_rate = 0
	unit.valuation_rate = cost
	unit.item_condition = condition
	unit.condition_grade = grade
	unit.condition_details = details
	unit.condition_of_item = source.item_code
	unit.warranty_period = cint(warranty_days) or None
	unit.flags.ignore_permissions = True
	unit.insert()

	settings = frappe.get_cached_doc("Webshop Settings")
	price_list = settings.price_list or frappe.db.get_value(
		"Price List", {"selling": 1, "enabled": 1}, "name"
	)
	frappe.get_doc(
		{
			"doctype": "Item Price",
			"item_code": unit.item_code,
			"price_list": price_list,
			"price_list_rate": price,
			"selling": 1,
		}
	).insert(ignore_permissions=True)

	company = settings.company or frappe.db.get_single_value("Global Defaults", "default_company")
	stock_entry = None
	if qty > 0 and unit.is_stock_item:
		from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry

		warehouse = warehouse or _default_warehouse(source, company)
		if not warehouse:
			frappe.throw(_("No warehouse to receive the unit into. Pick one."))
		stock_entry = make_stock_entry(
			item_code=unit.item_code,
			qty=qty,
			to_warehouse=warehouse,
			rate=cost,
			company=company,
			do_not_save=True,
		)
		for row in stock_entry.items:
			# a unit taken back for nothing still has to enter the stock
			row.allow_zero_valuation_rate = 0 if cost else 1
		stock_entry.flags.ignore_permissions = True
		stock_entry.save()
		stock_entry.submit()

	website_item = None
	if cint(publish):
		website_item = _publish_used_unit(unit, source, warehouse)

	return {
		"item_code": unit.item_code,
		"item_name": unit.item_name,
		"website_item": website_item.name if website_item else None,
		"route": website_item.route if website_item else None,
		"stock_entry": stock_entry.name if stock_entry else None,
	}


def _publish_used_unit(unit, source, warehouse):
	"""A Website Item for the unit, seeded from the new item's page."""
	from webshop.webshop.doctype.website_item.website_item import make_website_item

	name, _title = make_website_item(unit)
	website_item = frappe.get_doc("Website Item", name)

	source_page = frappe.db.get_value(
		"Website Item",
		{"item_code": source.item_code},
		["name", "short_description", "web_long_description", "website_image", "website_image_alt", "image_focus"],
		as_dict=True,
	)
	if source_page:
		website_item.short_description = source_page.short_description
		website_item.web_long_description = source_page.web_long_description
		website_item.website_image = source_page.website_image
		website_item.website_image_alt = source_page.website_image_alt
		website_item.image_focus = source_page.image_focus
		for spec in frappe.get_all(
			"Item Website Specification",
			filters={"parent": source_page.name, "parenttype": "Website Item"},
			fields=["label", "description"],
			order_by="idx",
		):
			website_item.append("website_specifications", spec)
	if warehouse:
		website_item.website_warehouse = warehouse
	website_item.web_item_name = unit.item_name
	website_item.flags.ignore_permissions = True
	website_item.save()
	return website_item
