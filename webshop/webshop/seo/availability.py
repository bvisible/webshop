# //// Neoffice — added file (no upstream equivalent). The availability the structured data
# //// declares, computed from the shop's stock rule and not from what the page shows.
"""Availability for search engines and shopping feeds.

The product page's JSON-LD read `product_info.in_stock`, which `get_product_info_for_website`
only fills when the shop DISPLAYS its stock (`show_stock_availability`). A shop that hides
its stock therefore told Google every product was out of stock; so did an item on backorder,
and a model with variants, whose own stock is always empty since its variants hold it.
Google Merchant Center compares this value with the feed and refuses items that disagree.
"""

import frappe
from frappe.utils import cint, flt

SCHEMA = "https://schema.org/"
IN_STOCK = SCHEMA + "InStock"
OUT_OF_STOCK = SCHEMA + "OutOfStock"
BACK_ORDER = SCHEMA + "BackOrder"

# A model with more variants than this is judged on the first ones: the answer only needs
# one variant in stock, and a product page must not run hundreds of stock queries.
MAX_VARIANTS_CHECKED = 200


def schema_availability(item_code, cart_settings=None) -> str:
	"""schema.org availability of a Website Item's item, whatever the page chooses to display."""
	if not item_code:
		return OUT_OF_STOCK
	if frappe.db.get_value("Website Item", {"item_code": item_code}, "on_backorder"):
		return BACK_ORDER
	if item_can_be_bought(item_code):
		return IN_STOCK
	if cart_settings is None:
		from webshop.webshop.doctype.webshop_settings.webshop_settings import (
			get_shopping_cart_settings,
		)

		cart_settings = get_shopping_cart_settings()
	# The shop takes orders beyond its stock: an empty shelf is a delay, not a refusal.
	if cint(cart_settings.get("allow_items_not_in_stock")):
		return BACK_ORDER
	return OUT_OF_STOCK


def item_can_be_bought(item_code) -> bool:
	"""Whether the shop's stock rule lets this item (or one of its variants) be sold now."""
	if cint(frappe.db.get_value("Item", item_code, "has_variants")):
		variants = frappe.get_all(
			"Item",
			filters={"variant_of": item_code, "disabled": 0},
			pluck="name",
			limit=MAX_VARIANTS_CHECKED,
		)
		return any(_in_stock(code) for code in variants)
	return _in_stock(item_code)


def _in_stock(item_code) -> bool:
	# The same three rules the product page applies (shopping_cart/product_info.py):
	# the website warehouse, a non-stock item's own status, the multi-warehouse sources.
	from webshop.webshop.multi_warehouse.sources import get_item_warehouse_sources
	from webshop.webshop.utils.product import get_non_stock_item_status, get_web_item_qty_in_stock

	status = get_web_item_qty_in_stock(item_code, "website_warehouse")
	if not status.is_stock_item:
		return bool(get_non_stock_item_status(item_code, "website_warehouse"))
	sources = get_item_warehouse_sources(item_code)
	if len(sources) > 1:
		return sum(flt(source.stock_qty) for source in sources) > 0
	return bool(status.in_stock)


def bulk_availability(item_codes, cart_settings=None, fallback_warehouse=None) -> dict[str, frappe._dict]:
	"""schema_availability for the variants of one model at once, with the quantity the shop may
	promise: {item code: {availability, qty}}; qty is None for an item the shop does not count
	(not a stock item, on backorder). Same rules as schema_availability, in fewer queries: the
	variant selector and the model page's ProductGroup ask for a dozen variants on every render.

	fallback_warehouse is the model's website warehouse, which a variant without one of its own
	uses (get_web_item_qty_in_stock resolves it the same way)."""
	from webshop.webshop.multi_warehouse import sources as mw_sources
	from webshop.webshop.utils.product import get_non_stock_item_status, get_web_items_qty_in_stock

	codes = list(dict.fromkeys(code for code in item_codes or [] if code))
	if not codes:
		return {}
	if cart_settings is None:
		from webshop.webshop.doctype.webshop_settings.webshop_settings import (
			get_shopping_cart_settings,
		)

		cart_settings = get_shopping_cart_settings()
	web_items = {
		row.item_code: row
		for row in frappe.get_all(
			"Website Item",
			filters={"item_code": ["in", codes]},
			fields=["item_code", "on_backorder", "website_warehouse"],
		)
	}
	stock_items = set(frappe.get_all("Item", filters={"name": ["in", codes], "is_stock_item": 1}, pluck="name"))
	found, qty = {}, {}
	counted = []
	for code in codes:
		if cint((web_items.get(code) or {}).get("on_backorder")):
			found[code] = BACK_ORDER
		elif code not in stock_items:
			found[code] = IN_STOCK if get_non_stock_item_status(code, "website_warehouse") else None
		else:
			counted.append(code)
	if mw_sources.is_enabled(cart_settings):
		# a model sold from several sources: each variant by the single rule, which sums them
		for code in counted:
			sources = mw_sources.get_item_warehouse_sources(code, cart_settings)
			if len(sources) > 1:
				qty[code] = sum(flt(source.stock_qty) for source in sources)
	by_warehouse = {}
	for code in counted:
		if code in qty:
			continue
		warehouse = (web_items.get(code) or {}).get("website_warehouse") or fallback_warehouse
		by_warehouse.setdefault(warehouse, []).append(code)
	for warehouse, group in by_warehouse.items():
		# no warehouse at all: nothing counted, as get_web_item_qty_in_stock answers
		levels = get_web_items_qty_in_stock(group, warehouse) if warehouse else {}
		for code in group:
			qty[code] = flt(levels.get(code))
	for code in counted:
		found[code] = IN_STOCK if qty.get(code, 0) > 0 else None
	# The shop takes orders beyond its stock: an empty shelf is a delay, not a refusal.
	beyond = cint(cart_settings.get("allow_items_not_in_stock"))
	return {
		code: frappe._dict(
			availability=found[code] or (BACK_ORDER if beyond else OUT_OF_STOCK),
			qty=qty.get(code),
		)
		for code in codes
	}
