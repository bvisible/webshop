# //// Neoffice — added file (no upstream equivalent). The stock quantity the partner API tells, and the warehouses
# //// it is counted in (reseller catalogue, lot 5).
"""The stock a key reads: a quantity, counted where staff chose.

A key tells, for each product, an `availability` word (`in_stock`, `out_of_stock`, `backorder`) and a `stock`
number. Where the number is counted is the staff's choice, per access (`Partner API Access.stock_warehouses`):

- **nothing chosen**: the quantity the shop itself promises its visitors (`seo.availability.bulk_availability`: the
  website warehouse, or the sources of a product sold from several warehouses). `stock` is null for a product the
  shop does not count (a service, an item on backorder).
- **warehouses chosen**: the stock held by those warehouses, with the orders already placed deducted
  (`get_web_items_qty_in_stock`, which expands a group warehouse into its children). An order is checked against
  this same quantity, so what a program reads is what it can order.
"""

import frappe
from frappe.utils import cint, flt

from webshop.webshop.seo import availability as stock
from webshop.webshop.utils.product import get_web_items_qty_in_stock

DOCTYPE = "Partner API Access"
WORDS = {stock.IN_STOCK: "in_stock", stock.BACK_ORDER: "backorder", stock.OUT_OF_STOCK: "out_of_stock"}


def warehouses_of(customer):
	"""The warehouses staff chose for this access, in the order they wrote them; empty = the shop's own rule."""
	return frappe.get_all(
		"Partner API Warehouse", filters={"parent": customer, "parenttype": DOCTYPE}, pluck="warehouse", order_by="idx"
	)


def levels(codes, warehouses=None):
	"""{item code: frappe._dict(availability=<schema.org URL>, qty=<number or None>)} for the items asked."""
	codes = list(dict.fromkeys(code for code in codes or [] if code))
	if not codes:
		return {}
	base = stock.bulk_availability(codes)
	if not warehouses:
		return {code: frappe._dict(availability=base[code].availability, qty=base[code].qty) for code in codes}
	stock_items = set(frappe.get_all("Item", filters={"name": ["in", codes], "is_stock_item": 1}, pluck="name"))
	counted = [code for code in codes if code in stock_items]
	qty = {code: 0.0 for code in counted}
	for warehouse in dict.fromkeys(warehouses):
		for code, held in get_web_items_qty_in_stock(counted, warehouse).items():
			qty[code] = qty.get(code, 0.0) + flt(held)
	on_backorder = (
		set(frappe.get_all("Website Item", filters={"item_code": ["in", counted], "on_backorder": 1}, pluck="item_code"))
		if counted
		else set()
	)
	from webshop.webshop.doctype.webshop_settings.webshop_settings import get_shopping_cart_settings

	# the shop takes orders beyond its stock: an empty shelf is a delay, not a refusal (the page's own rule)
	beyond = cint(get_shopping_cart_settings().get("allow_items_not_in_stock"))
	found = {}
	for code in codes:
		if code not in qty:
			found[code] = frappe._dict(availability=base[code].availability, qty=None)
		elif code in on_backorder:
			found[code] = frappe._dict(availability=stock.BACK_ORDER, qty=qty[code])
		elif qty[code] > 0:
			found[code] = frappe._dict(availability=stock.IN_STOCK, qty=qty[code])
		else:
			found[code] = frappe._dict(availability=stock.BACK_ORDER if beyond else stock.OUT_OF_STOCK, qty=qty[code])
	return found


def word(level):
	return WORDS.get(level.availability, "out_of_stock")


def number(qty):
	"""A quantity as a JSON number: 12, not 12.0; null where the shop does not count."""
	if qty is None:
		return None
	value = flt(qty, 3)
	return int(value) if value == int(value) else value
