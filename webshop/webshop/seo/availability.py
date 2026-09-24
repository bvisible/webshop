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
