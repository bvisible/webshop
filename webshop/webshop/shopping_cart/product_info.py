# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.utils import flt, fmt_money

from webshop.webshop.doctype.webshop_settings.webshop_settings import (
    get_shopping_cart_settings,
    show_quantity_in_website,
)
from webshop.webshop.shopping_cart.cart import _get_cart_quotation, _set_price_list
from erpnext.utilities.product import (get_price)
from webshop.webshop.utils.product import (get_non_stock_item_status, get_web_item_qty_in_stock)
from webshop.webshop.shopping_cart.cart import get_party


@frappe.whitelist(allow_guest=True)
def get_product_info_for_website(item_code, skip_quotation_creation=False):
	"""
	Get product price / stock info for website
	"""

	cart_settings = get_shopping_cart_settings()
	if not cart_settings.enabled:
		# return settings even if cart is disabled
		return frappe._dict({"product_info": {}, "cart_settings": cart_settings})

	cart_quotation = frappe._dict()
	if not skip_quotation_creation:
		cart_quotation = _get_cart_quotation()

	selling_price_list = (
		cart_quotation.get("selling_price_list")
		if cart_quotation
		else cart_settings.price_list if not cart_settings.enable_guest_cart
		else _set_price_list(cart_settings, None)
	)

	price = {}
	if cart_settings.show_price:
		is_guest = frappe.session.user == "Guest"
		party = get_party()

		# Show Price if logged in.
		# If not logged in, check if price is hidden for guest.
		if not is_guest or not cart_settings.hide_price_for_guest:
			# Check if item is a template with variants
			has_variants = frappe.db.get_value("Item", item_code, "has_variants")

			# Get website_warehouse for Pricing Rule matching
			website_warehouse = frappe.db.get_value(
				"Website Item", {"item_code": item_code}, "website_warehouse"
			)

			if has_variants:
				# Get price from variants for template items
				price = get_template_price_from_variants(
					item_code,
					selling_price_list,
					cart_settings.default_customer_group,
					cart_settings.company,
					party=party,
					warehouse=website_warehouse,
				)
			else:
				price = get_price(
					item_code,
					selling_price_list,
					cart_settings.default_customer_group,
					cart_settings.company,
					party=party,
					warehouse=website_warehouse,
				)

	stock_status = None

	if cart_settings.show_stock_availability:
		on_backorder = frappe.get_cached_value(
			"Website Item", {"item_code": item_code}, "on_backorder"
		)
		if on_backorder:
			stock_status = frappe._dict({"on_backorder": True})
		else:
			stock_status = get_web_item_qty_in_stock(item_code, "website_warehouse")

	product_info = {
		"price": price,
		"qty": 0,
		"uom": frappe.db.get_value("Item", item_code, "stock_uom"),
		"sales_uom": frappe.db.get_value("Item", item_code, "sales_uom"),
	}

	if stock_status:
		if stock_status.on_backorder:
			product_info["on_backorder"] = True
		else:
			product_info["stock_qty"] = stock_status.stock_qty
			product_info["in_stock"] = (
				stock_status.in_stock
				if stock_status.is_stock_item
				else get_non_stock_item_status(item_code, "website_warehouse")
			)
			product_info["show_stock_qty"] = show_quantity_in_website()

	if product_info["price"]:
		if frappe.session.user != "Guest":
			item = (
				cart_quotation.get({"item_code": item_code}) if cart_quotation else None
			)
			if item:
				product_info["qty"] = item[0].qty

	return frappe._dict({"product_info": product_info, "cart_settings": cart_settings})


def set_product_info_for_website(item):
	"""set product price uom for website"""
	product_info = get_product_info_for_website(
		item.item_code, skip_quotation_creation=True
	).get("product_info")

	if product_info:
		item.update(product_info)
		item["stock_uom"] = product_info.get("uom")
		item["sales_uom"] = product_info.get("sales_uom")
		if product_info.get("price"):
			item["price_stock_uom"] = product_info.get("price").get("formatted_price")
			item["price_sales_uom"] = product_info.get("price").get(
				"formatted_price_sales_uom"
			)
		else:
			item["price_stock_uom"] = ""
			item["price_sales_uom"] = ""

@frappe.whitelist(allow_guest=True)
def get_website_item_name(item_code):
	return frappe.db.get_value("Website Item", {"item_code": item_code}, "item_name")


def get_template_price_from_variants(item_code, price_list, customer_group, company, qty=1, party=None, warehouse=None):
	"""
	Get price information for a template item based on its variants' prices.
	Applies Pricing Rules to get actual selling prices with discounts.

	Returns price object with:
	- If all variants have same price: standard price display
	- If variants have different prices: "from X" prefix with minimum price

	Args:
		item_code: Template item code
		price_list: Selling price list
		customer_group: Default customer group
		company: Company
		qty: Quantity (default 1)
		party: Customer party object
		warehouse: Warehouse for Pricing Rule matching (optional)

	Returns:
		dict: Price object similar to get_price() output, with additional
		      'is_range' and 'price_prefix' fields for templates
	"""
	if not price_list:
		return {}

	# Get all variants with their base prices
	variants = frappe.db.sql(
		"""
		SELECT
			i.name as item_code,
			ip.price_list_rate,
			ip.currency
		FROM `tabItem` i
		INNER JOIN `tabItem Price` ip ON i.name = ip.item_code
		WHERE i.variant_of = %s
			AND ip.selling = 1
			AND ip.price_list = %s
			AND ip.price_list_rate > 0
		""",
		(item_code, price_list),
		as_dict=True,
	)

	if not variants:
		return {}

	# Get prices with Pricing Rules applied for each variant
	prices_with_discount = []
	mrp_prices = []
	currency = variants[0].currency

	for variant in variants:
		# Get variant's website_warehouse if not provided
		variant_warehouse = warehouse
		if not variant_warehouse:
			variant_warehouse = frappe.db.get_value(
				"Website Item", {"item_code": variant.item_code}, "website_warehouse"
			)
		variant_price = get_price(
			variant.item_code,
			price_list,
			customer_group,
			company,
			qty=qty,
			party=party,
			warehouse=variant_warehouse,
		)
		if variant_price and variant_price.get("price_list_rate"):
			prices_with_discount.append(flt(variant_price.get("price_list_rate")))
			# Track MRP (original price before discount) if available
			if variant_price.get("formatted_mrp"):
				mrp_prices.append(flt(variant.price_list_rate))

	if not prices_with_discount:
		return {}

	min_price = min(prices_with_discount)
	max_price = max(prices_with_discount)

	# Determine if prices vary
	is_range = min_price != max_price

	# Build price object similar to get_price() output
	price_obj = frappe._dict({
		"price_list_rate": min_price,
		"currency": currency,
		"is_range": is_range,
	})

	# Add MRP info if there are discounts
	if mrp_prices:
		min_mrp = min(mrp_prices)
		if min_mrp > min_price:
			price_obj["mrp"] = min_mrp
			price_obj["formatted_mrp"] = fmt_money(min_mrp, currency=currency)
			discount_percent = ((min_mrp - min_price) / min_mrp) * 100
			price_obj["discount_percent"] = flt(discount_percent, 0)
			price_obj["formatted_discount_percent"] = str(int(discount_percent)) + "%"

	# Format the price with "from" prefix if prices vary
	if is_range:
		price_obj["price_prefix"] = _("from")
		price_obj["formatted_price"] = _("from") + " " + fmt_money(min_price, currency=currency)
		price_obj["max_price"] = max_price
		price_obj["formatted_max_price"] = fmt_money(max_price, currency=currency)
	else:
		price_obj["price_prefix"] = ""
		price_obj["formatted_price"] = fmt_money(min_price, currency=currency)

	# Get currency symbol
	price_obj["currency_symbol"] = (
		frappe.db.get_value("Currency", currency, "symbol", cache=True) or currency
	) if not frappe.db.get_default("hide_currency_symbol") else ""

	return price_obj
