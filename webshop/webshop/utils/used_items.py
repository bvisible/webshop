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

	info.reference = get_new_model(website_item)
	return info


def get_new_model(website_item):
	"""The new model a used unit copies, as the unit's page shows it: name, route, picture,
	price on this site's list, stock — or None when the new item has no published page here.
	(2026-09-14: the page used to print a bare "See the new model" link; the merchant wants the
	new product SEEN from the used one, as the used ones are seen from the new one.)"""
	reference_item = website_item.get("condition_of_item")
	if not reference_item:
		return None
	from webshop.webshop.multi_site import excluded_item_names

	reference = frappe.db.get_value(
		"Website Item",
		# a page without a route can neither be linked nor redirected to (the CI's fresh site
		# gave one none, and a sold unit's page redirected to "/None")
		{"item_code": reference_item, "published": 1, "route": ("is", "set")},
		["name", "item_code", "route", "web_item_name", "website_image", "thumbnail", "website_warehouse"],
		as_dict=True,
	)
	if not reference or reference.name in excluded_item_names():
		return None
	_price_and_stock(reference)
	return reference


def get_sibling_units(website_item, limit=6):
	"""The other used units of the same model still for sale, cheapest first: a customer
	comparing two used copies should see both."""
	reference_item = website_item.get("condition_of_item")
	if not reference_item:
		return []
	return [u for u in get_used_units(reference_item, limit=limit + 1) if u.name != website_item.name][:limit]


def _price_and_stock(row):
	"""Price on this site's list and stock by the shop's own rule, written on the row."""
	from erpnext.utilities.product import get_price

	from webshop.webshop.multi_site import effective_price_list
	from webshop.webshop.utils.product import get_web_item_qty_in_stock
	from webshop.webshop.utils.utils import format_currency_value

	settings = frappe.get_cached_doc("Webshop Settings")
	stock = get_web_item_qty_in_stock(row.item_code, "website_warehouse", row.get("website_warehouse"))
	row.in_stock = bool(stock and stock.in_stock)
	price = get_price(row.item_code, effective_price_list(settings.price_list), settings.default_customer_group, settings.company)
	row.price = flt(price.get("price_list_rate")) if price else 0
	row.currency = price.get("currency") if price else None
	row.formatted_price = format_currency_value(row.price, currency=row.currency) if row.price else None
	return row


def used_unit_in_stock(website_item) -> bool:
	"""Whether a used unit can still be sold: the shop's own stock rule — every exposed
	source when multi-warehouse is on, the item's website warehouse otherwise."""
	from webshop.webshop.multi_warehouse.sources import get_aggregate_stock
	from webshop.webshop.utils.product import get_web_item_qty_in_stock

	settings = frappe.get_cached_doc("Webshop Settings")
	stock = get_aggregate_stock(website_item.item_code, settings) if cint(settings.get("enable_multi_warehouse")) else None
	if stock is None:
		stock = get_web_item_qty_in_stock(website_item.item_code, "website_warehouse", website_item.get("website_warehouse"))
	return bool(stock and stock.in_stock)


def sold_flag(website_item) -> int:
	"""1 when a used unit has nothing left to sell, 0 for everything else. A used unit is one
	of a kind: sold means gone from the catalogue, not "out of stock" (2026-09-14)."""
	if not is_second_hand(website_item.get("item_condition")):
		return 0
	return 0 if used_unit_in_stock(website_item) else 1


def refresh_sold_flag(website_item_name):
	"""Recompute `sold` on one Website Item from the stock and write it only when it changes;
	clears the page's cache so the catalogue and the unit's page follow at once."""
	from frappe.website.utils import clear_cache

	row = frappe.db.get_value(
		"Website Item", website_item_name, ["name", "item_code", "item_condition", "website_warehouse", "sold", "route"], as_dict=True
	)
	if not row:
		return None
	sold = sold_flag(row)
	if cint(row.sold) != sold:
		frappe.db.set_value("Website Item", row.name, "sold", sold, update_modified=False)
		clear_cache(row.route)
		clear_cache()
	return sold


def on_stock_ledger_entry(doc, method=None):
	"""Stock Ledger Entry on_submit: remembers the used units a voucher moves. Only
	second-hand items are looked at, so the hook costs nothing on ordinary movements.

	The flag cannot be computed here: ERPNext submits the ledger entry first and updates the
	warehouse's Bin only afterwards (stock_ledger.make_sl_entries: make_entry, then
	repost_current_voucher and update_bin_qty), so the stock read at this point is the one
	BEFORE the movement — a unit just sold still read as in stock and stayed in the
	catalogue (found by the CI, 2026-09-14). refresh_moved_used_units recomputes it once the
	voucher is done."""
	condition = frappe.get_cached_value("Item", doc.item_code, "item_condition")
	if not is_second_hand(condition):
		return
	frappe.flags.setdefault("webshop_used_units_moved", set()).add(doc.item_code)


def refresh_moved_used_units(doc, method=None):
	"""Every document's on_submit / on_cancel ("*" in hooks.py): once a voucher is done —
	its ledger written and its bins updated — the used units it moved (a sale, a return, a
	receipt) get their `sold` flag again. A ledger entry's own submit is skipped: its bin is
	not updated yet. Returns at once when nothing second-hand moved."""
	moved = frappe.flags.get("webshop_used_units_moved")
	if not moved or doc.doctype == "Stock Ledger Entry":
		return
	frappe.flags.webshop_used_units_moved = set()
	for item_code in moved:
		for name in frappe.get_all("Website Item", filters={"item_code": item_code}, pluck="name"):
			refresh_sold_flag(name)


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
			"sold": 0,
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
	price_list=None,
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
	price_list = (
		price_list
		or settings.price_list
		or frappe.db.get_value("Price List", {"selling": 1, "enabled": 1}, "name")
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
		# the warehouse says which company receives the unit; the shop's
		# company is only a way to pick a default warehouse
		company = frappe.db.get_value("Warehouse", warehouse, "company") or company
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
