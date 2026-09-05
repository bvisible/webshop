# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt
import frappe

from webshop.webshop.doctype.webshop_settings.webshop_settings import (
    get_shopping_cart_settings,
)
from webshop.webshop.shopping_cart.cart import _set_price_list
from erpnext.utilities.product import get_price
from webshop.webshop.shopping_cart.cart import get_party


# //// Neoffice — _ imported for the page title (9953f79418, 2026-08-26).
from frappe import _


def get_context(context):
	# //// Neoffice — themes print context.title as the visible page heading
	# //// and as the last breadcrumb, and Frappe defaults it to the route
	# //// name — untranslated. A French shop read "wishlist" on screen while
	# //// its browser tab said the translated title.
	context.title = _("Wishlist")
	is_guest = frappe.session.user == "Guest"

	settings = get_shopping_cart_settings()
	items = get_wishlist_items() if not is_guest else []
	selling_price_list = _set_price_list(settings) if not is_guest else None

	items = set_stock_price_details(items, settings, selling_price_list)

	context.body_class = "product-page"
	context.items = items
	context.settings = settings
	# //// Neoffice — the macros expect cart_settings; without it the wishlist card could not
	# //// tell whether a guest may add to the cart (b9f319c437, 2025-02-24).
	context.cart_settings = settings
	context.no_cache = 1


def get_stock_availability(item_code, warehouse):
	from erpnext.stock.doctype.warehouse.warehouse import get_child_warehouses
	# //// Neoffice — POS reservations are read from here (see below).
	from webshop.webshop.utils.product import get_pos_reserved_qty

	if warehouse and frappe.get_cached_value("Warehouse", warehouse, "is_group") == 1:
		warehouses = get_child_warehouses(warehouse)
	else:
		warehouses = [warehouse] if warehouse else []

	stock_qty = 0.0
	# //// Neoffice — upstream reads Bin.actual_qty. projected_qty is what the shop may
	# //// promise: it already deducts the quantities reserved by open Sales Orders
	# //// (f3d9fb5de7, 2025-12-06).
	for wh in warehouses:
		# Use projected_qty which accounts for reserved quantities from Sales Orders
		bin_qty = frappe.utils.flt(
			frappe.db.get_value("Bin", {"item_code": item_code, "warehouse": wh}, "projected_qty")
		)
		# //// Neoffice — and POS invoices that are not consolidated yet hold stock that
		# //// projected_qty does not know about — a shop selling in store and online oversold
		# //// otherwise (17128042fc, 2025-12-05).
		# Subtract POS reserved quantities (unconsolidated POS Invoices)
		# POS reservations are not included in projected_qty
		pos_reserved = get_pos_reserved_qty(item_code, wh)
		stock_qty += max(0, bin_qty - pos_reserved)

	return bool(stock_qty)


def get_wishlist_items():
	if not frappe.db.exists("Wishlist", frappe.session.user):
		return []

	return frappe.db.get_all(
		"Wishlist Item",
		filters={"parent": frappe.session.user},
		fields=[
			"web_item_name",
			"item_code",
			"item_name",
			"website_item",
			"warehouse",
			"image",
			"item_group",
			"route",
		],
	)


def set_stock_price_details(items, settings, selling_price_list):
	for item in items:
		if settings.show_stock_availability:
			item.available = get_stock_availability(
				item.item_code, item.get("warehouse")
			)

		party = get_party()

		# //// Neoffice — the website_warehouse is passed to get_price so a Pricing Rule scoped
		# //// to a warehouse matches (d23d979933, 2025-12-05).
		# Get website_warehouse for Pricing Rule matching
		website_warehouse = frappe.db.get_value(
			"Website Item", {"item_code": item.item_code}, "website_warehouse"
		)
		price_details = get_price(
			item.item_code,
			selling_price_list,
			settings.default_customer_group,
			settings.company,
			party=party,
			# //// Neoffice — see above.
			warehouse=website_warehouse,
		)

		if price_details:
			item.formatted_price = price_details.get("formatted_price")
			item.formatted_mrp = price_details.get("formatted_mrp")
			if item.formatted_mrp:
				item.discount = price_details.get(
					"formatted_discount_percent"
				) or price_details.get("formatted_discount_rate")

	return items
