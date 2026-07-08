# -*- coding: utf-8 -*-
# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.utils import cint

from webshop.webshop.product_data_engine.filters import ProductFiltersBuilder
from webshop.webshop.product_data_engine.query import ProductQuery
from webshop.webshop.doctype.override_doctype.item_group import get_child_groups_for_website
from webshop.webshop.utils.discount_query import get_discounted_items_query, get_items_with_pricing_rule_discount
from webshop.webshop.utils.import_gift_cards import import_gift_cards_from_excel, get_gift_card_import_template


@frappe.whitelist(allow_guest=True)
def get_product_filter_data(query_args=None):
	"""
	Returns filtered products and discount filters.

	Args:
		query_args (dict): contains filters to get products list

	Query Args filters:
		search (str): Search Term.
		field_filters (dict): Keys include item_group, brand, etc.
		attribute_filters(dict): Keys include Color, Size, etc.
		start (int): Offset items by
		item_group (str): Valid Item Group
		from_filters (bool): Set as True to jump to page 1
	"""
	if isinstance(query_args, str):
		query_args = json.loads(query_args)

	query_args = frappe._dict(query_args or {})
	
	# Debug logging for filter issues
	if frappe.conf.developer_mode:
		if query_args:
			if query_args.get("field_filters"):
				# Log item_group specifically
				field_filters = query_args.get("field_filters", {})
				if isinstance(field_filters, str):
					try:
						field_filters = json.loads(field_filters)
					except:
						pass

	if query_args:
		search = query_args.get("search")
		field_filters = query_args.get("field_filters", {})
		attribute_filters = query_args.get("attribute_filters", {})
		sort_order = query_args.get("sort_order", "relevance")
		
		# Try to parse price_range
		price_range_param = query_args.get("price_range", {})
		if isinstance(price_range_param, str):
			try:
				price_range_param = json.loads(price_range_param)
			except json.JSONDecodeError:
				price_range_param = {}
		
		# Extract and validate price_range
		price_condition = None
		if price_range_param:
			# Handle both formats: min/max and min_price/max_price
			min_price = price_range_param.get("min") or price_range_param.get("min_price")
			max_price = price_range_param.get("max") or price_range_param.get("max_price")
			
			# Only set price_condition if we have valid numeric values
			if min_price is not None or max_price is not None:
				price_condition = {}
				if min_price is not None and str(min_price).replace('.', '').isdigit():
					price_condition["min_price"] = float(min_price)
				if max_price is not None and str(max_price).replace('.', '').isdigit():
					price_condition["max_price"] = float(max_price)
				
				# If price_condition is empty after validation, set it to None
				if not price_condition:
					price_condition = None
					
		start = cint(query_args.get("start")) if query_args.get("from_filters") else cint(
			query_args.get("start")
		)
		item_group = query_args.get("item_group")
		from_filters = query_args.get("from_filters")
	else:
		search, attribute_filters, field_filters, start, item_group, from_filters = (
			None,
			None,
			None,
			0,
			None,
			None,
		)
		sort_order = "relevance"
		price_condition = None

	# if new filter is checked, reset start to show filtered items from page 1
	if from_filters:
		start = 0

	engine = ProductQuery()
	
	# Pass price_condition to the query
	result = engine.query(
		attribute_filters,
		field_filters,
		search_term=search,
		start=start,
		item_group=item_group,
		price_condition=price_condition,
		sort_order=sort_order
	)

	# discount filter data
	filters = {}
	discounts = result.get("discounts")

	if discounts:
		filters["discount"] = get_discount_filters(discounts)
	
	# Get price filters based on current field filters
	# Don't include the current price range in the filter calculation
	filter_builder = ProductFiltersBuilder(item_group)
	price_filters = filter_builder.get_price_filters(field_filters, attribute_filters)
	if price_filters:
		filters["price_filters"] = price_filters

	return {
		"items": result.get("items"),
		"filters": filters,
		"settings": engine.settings,
		"items_count": result.get("items_count"),
		"total_count": result.get("total_count"),
		"sub_categories": result.get("sub_categories", [])
	}


@frappe.whitelist(allow_guest=True)
def get_products_html_for_website(
	item_group=None,
	start=0,
	limit=20,
	search=None,
	sort_order="relevance"
):
	"""
	Args:
		item_group (str): Valid Item Group
		start (int): Start index of results 
		limit (int): Number of results to return
		search (str): Search term
		sort_order (str): Sort order for results (relevance, price_low_to_high, price_high_to_low, new_arrivals, rating)
	
	Returns:
		dict: HTML for product list, items_count
	"""
	from webshop.webshop.doctype.website_item.website_item import render_product_cards

	engine = ProductQuery()
	
	result = engine.query(
		attribute_filters={},
		field_filters={},
		search_term=search,
		start=int(start),
		item_group=item_group,
		sort_order=sort_order
	)

	products = result.get("items", [])
	
	html = render_product_cards(products, engine.settings)

	return {"html": html, "items_count": result.get("items_count", 0)}


@frappe.whitelist(allow_guest=True)
def get_products_json_for_website(
	item_group=None,
	start=0,
	limit=20,
	search=None,
	sort_order="relevance"
):
	"""
	Args:
		item_group (str): Valid Item Group
		start (int): Start index of results
		limit (int): Number of results to return
		search (str): Search term
		sort_order (str): Sort order for results

	Returns:
		dict: Items list and count
	"""
	# Simply return the result of the engine query
	engine = ProductQuery()
	
	result = engine.query(
		attribute_filters={},
		field_filters={}, 
		search_term=search,
		start=int(start),
		item_group=item_group,
		sort_order=sort_order
	)

	return {
		"items": result.get("items", []),
		"items_count": result.get("items_count", 0)
	}


@frappe.whitelist(allow_guest=True)
def get_product_filter_html(item_group=None, query_args=None):
	from webshop.webshop.doctype.webshop_settings.webshop_settings import get_shopping_cart_settings

	if query_args:
		query_args = json.loads(query_args)
		if query_args.get("field_filters"):
			query_args["field_filters"] = json.loads(query_args.get("field_filters"))
		if query_args.get("attribute_filters"):
			query_args["attribute_filters"] = json.loads(query_args.get("attribute_filters"))
		
		if query_args.get("price_range"):
			try:
				query_args["price_range"] = json.loads(query_args.get("price_range"))
			except (json.JSONDecodeError, TypeError):
				# If it's already a dict or malformed, leave as is
				pass
		
		query_args = frappe._dict(query_args)
	else:
		query_args = frappe._dict()

	# Ensure field_filters and attribute_filters are dictionaries
	field_filters = query_args.get("field_filters") or {}
	attribute_filters = query_args.get("attribute_filters") or {}
	price_range = query_args.get("price_range") or {}
	sort_order = query_args.get("sort_order", "relevance")

	# Initialize the filter builder
	filter_engine = ProductFiltersBuilder(item_group)
	filters = filter_engine.get_all_filters(field_filters, attribute_filters)

	# Initialize as empty dict if None
	if not filters:
		filters = frappe._dict()
	elif isinstance(filters, tuple):
		# Handle case where get_all_filters returns a tuple
		filters = filters[0] if filters[0] else frappe._dict()
	
	# Always ensure discount key exists
	if "discount" not in filters:
		filters["discount"] = []
	
	# Add price filter
	filters["price_range"] = price_range
	filters["sort_order"] = sort_order
	
	# Add selected filters info for template
	selected_filters = frappe._dict()
	if field_filters:
		selected_filters.update(field_filters)
	if attribute_filters:
		selected_filters.update(attribute_filters)
	
	html = frappe.render_template(
		"templates/includes/products/product_filters.html",
		{
			"filters": filters,
			"selected_filters": selected_filters,
			"settings": get_shopping_cart_settings()
		}
	)
	
	return html


def get_discount_filters(discounts):
	discount_filters = []
	
	# Add predefined discount ranges
	ranges = [
		(0, 10, "Up to 10%"),
		(10, 25, "10% - 25%"),
		(25, 50, "25% - 50%"),
		(50, 100, "50% and above"),
		(100, 100, "With Discount")  # Special case to show only discounted items
	]
	
	for min_val, max_val, label in ranges:
		discount_filters.append(
			{
				"label": label,
				"value": max_val,  # Use max value as the filter value
				"min_discount": min_val,
				"max_discount": max_val
			}
		)
	
	return discount_filters


@frappe.whitelist(allow_guest=True)
def get_all_variants_info(item_code):
	"""Get all variants information for a template item.
	
	Args:
		item_code: The template item code
		
	Returns:
		Dict containing variants data with attributes, prices, stock info
	"""
	# Get the template item
	template_item = frappe.get_doc("Item", item_code)
	
	if not template_item.has_variants:
		return {"variants": []}
	
	# Get all variants
	variants = frappe.get_all(
		"Item",
		filters={"variant_of": item_code, "disabled": 0},
		fields=["name", "item_code", "item_name"]
	)
	
	if not variants:
		return {"variants": []}
	
	# Get variant attributes
	variant_attributes = frappe.get_all(
		"Item Variant Attribute",
		filters={"parent": item_code},
		fields=["attribute"],
		order_by="idx"
	)
	
	# Get price list from settings
	price_list = frappe.db.get_single_value("Webshop Settings", "price_list")
	
	# Build variant data
	variants_data = []
	price_min = None
	price_max = None
	
	for variant in variants:
		variant_data = {
			"item_code": variant.item_code,
			"item_name": variant.item_name,
			"attributes": {},
			"in_stock": False,
			"stock_qty": 0,
			"exists": True,
			"website_item": False
		}
		
		# Get variant attributes
		variant_attrs = frappe.get_all(
			"Item Variant Attribute",
			filters={"parent": variant.item_code},
			fields=["attribute", "attribute_value"]
		)
		
		for attr in variant_attrs:
			variant_data["attributes"][attr.attribute] = attr.attribute_value
		
		# Check if website item exists
		website_item = frappe.db.get_value(
			"Website Item",
			{"item_code": variant.item_code},
			["name", "published", "website_image", "on_backorder", "website_warehouse"],
			as_dict=True
		)

		if website_item and website_item.published:
			variant_data["website_item"] = True
			variant_data["image"] = website_item.website_image

			# Get stock info
			if not website_item.on_backorder:
				# Get actual stock
				from webshop.webshop.utils.product import get_web_item_qty_in_stock
				stock_info = get_web_item_qty_in_stock(variant.item_code, "website_warehouse")
				variant_data["in_stock"] = stock_info.in_stock
				variant_data["stock_qty"] = stock_info.stock_qty
			else:
				# On backorder items are considered in stock
				variant_data["in_stock"] = True
				variant_data["stock_qty"] = None

			# Get price with Pricing Rules applied
			if price_list:
				from erpnext.utilities.product import get_price
				from webshop.webshop.doctype.webshop_settings.webshop_settings import get_shopping_cart_settings

				cart_settings = get_shopping_cart_settings()
				price_obj = get_price(
					variant.item_code,
					price_list,
					cart_settings.default_customer_group,
					cart_settings.company,
					warehouse=website_item.website_warehouse
				)

				if price_obj:
					variant_data["price"] = {
						"price_list_rate": price_obj.get("price_list_rate"),
						"formatted_price": price_obj.get("formatted_price"),
						"currency": price_obj.get("currency"),
						"formatted_mrp": price_obj.get("formatted_mrp"),
						"discount_percent": price_obj.get("discount_percent"),
						"formatted_discount_percent": price_obj.get("formatted_discount_percent")
					}

					# Track min/max prices (use discounted price)
					actual_price = price_obj.get("price_list_rate")
					if actual_price:
						if price_min is None or actual_price < price_min:
							price_min = actual_price
						if price_max is None or actual_price > price_max:
							price_max = actual_price
		
		variants_data.append(variant_data)
	
	# Build price range
	price_range = None
	if price_min is not None and price_max is not None:
		from webshop.webshop.utils.utils import format_currency_value
		currency = frappe.db.get_value("Price List", price_list, "currency") if price_list else None
		if price_min == price_max:
			price_range = {
				"min": price_min,
				"max": price_max,
				"formatted": format_currency_value(price_min, currency=currency)
			}
		else:
			price_range = {
				"min": price_min,
				"max": price_max,
				"formatted": f"{format_currency_value(price_min, currency=currency)} - {format_currency_value(price_max, currency=currency)}"
			}
	
	return {
		"variants": variants_data,
		"attributes": variant_attributes,
		"price_range": price_range
	}


@frappe.whitelist(allow_guest=True)
def get_product_price_info(items):
	"""Get price information for multiple items.
	
	Args:
		items: List of item codes
		
	Returns:
		Dict with item codes as keys and price info as values
	"""
	if isinstance(items, str):
		items = json.loads(items)
	
	if not items:
		return {}
	
	# Get price list from settings
	price_list = frappe.db.get_single_value("Webshop Settings", "price_list")
	if not price_list:
		return {}
	
	# Get currency
	currency = frappe.db.get_value("Price List", price_list, "currency")
	
	result = {}
	
	# Get prices for all items in a single query
	prices = frappe.db.sql("""
		SELECT 
			ip.item_code,
			ip.price_list_rate
		FROM `tabItem Price` ip
		WHERE ip.item_code IN %(items)s
		AND ip.price_list = %(price_list)s
		AND ip.selling = 1
		AND ip.price_list_rate > 0
		ORDER BY ip.item_code
	""", {"items": items, "price_list": price_list}, as_dict=True)
	
	# Create a dict for quick lookup
	price_map = {p.item_code: p.price_list_rate for p in prices}
	
	# Get pricing rules if any
	from erpnext.utilities.product import get_price

	for item_code in items:
		# Get base price
		base_price = price_map.get(item_code, 0)

		if base_price:
			# Get website_warehouse for Pricing Rule matching
			website_warehouse = frappe.db.get_value(
				"Website Item", {"item_code": item_code}, "website_warehouse"
			)
			# Get price with pricing rules
			price_obj = get_price(
				item_code,
				price_list,
				customer_group=frappe.db.get_single_value("Webshop Settings", "default_customer_group"),
				company=frappe.db.get_single_value("Webshop Settings", "company"),
				qty=1,
				warehouse=website_warehouse
			)
			
			if price_obj:
				from webshop.webshop.utils.utils import format_currency_value
				formatted_price = format_currency_value(
					price_obj.get("price_list_rate") or base_price,
					currency=currency
				)
				
				result[item_code] = {
					"price_list_rate": price_obj.get("price_list_rate") or base_price,
					"formatted_price": formatted_price
				}
				
				# Add discount info if applicable
				if price_obj.get("discount_percent"):
					result[item_code]["discount"] = f"{price_obj.get('discount_percent')}% OFF"
					result[item_code]["formatted_mrp"] = format_currency_value(base_price, currency=currency)
			else:
				# No pricing rule, use base price
				result[item_code] = {
					"price_list_rate": base_price,
					"formatted_price": format_currency_value(base_price, currency=currency)
				}
		else:
			# No price found
			result[item_code] = {
				"price_list_rate": 0,
				"formatted_price": ""
			}
	
	return result


@frappe.whitelist(allow_guest=True)
def get_guest_redirect_on_action():
	return frappe.db.get_single_value("Webshop Settings", "redirect_on_action")


@frappe.whitelist(allow_guest=True)
def get_all_guest_product_info():
	# Get Cart via Cookies
	from webshop.webshop.shopping_cart.cart import get_cart_quotation

	cart_quotation = get_cart_quotation()
	
	# Return both wishlist and cart items
	return {
		"cart_items": {
			d.item_code: d.qty for d in cart_quotation.items
		} if cart_quotation else {},
		"wishlisted_items": []  # Guest users don't have wishlists
	}


@frappe.whitelist()
def get_all_product_info():
	"""Get all product info for logged in user - cart items and wishlisted items."""
	# Get all Cart Items
	from webshop.webshop.shopping_cart.cart import get_cart_quotation
	
	cart_quotation = get_cart_quotation()
	
	# Get all wishlist items
	from webshop.webshop.doctype.wishlist.wishlist import get_wished_items_dict
	
	wishlisted_items = get_wished_items_dict() or {}

	# Return both
	return {
		"cart_items": {
			d.item_code: d.qty for d in cart_quotation.items
		} if cart_quotation else {},
		"wishlisted_items": wishlisted_items
	}


@frappe.whitelist(allow_guest=True)
def get_item_groups_html(item_group=None):
	from webshop.webshop.shopping_cart.cart import get_party
	
	# Get child item groups
	if item_group:
		item_groups = get_child_groups_for_website(item_group, immediate=True)
	else:
		# Get root level item groups  
		item_groups = frappe.get_all(
			"Item Group",
			filters={
				"parent_item_group": ["in", ["All Item Groups", ""]],
				"show_in_website": 1
			},
			fields=["name", "route", "website_title", "item_group_name"],
			order_by="weightage desc, item_group_name"
		)
	
	html = frappe.render_template(
		"templates/includes/products/item_group_grid.html",
		{"item_groups": item_groups}
	)
	
	return html


@frappe.whitelist(allow_guest=True)
def get_variant_grid(template_item_code):
	"""
	Get all variants of a template item for grid display.
	
	Args:
		template_item_code: Item code of the template/parent item
		
	Returns:
		Dict containing variants info and attributes for grid display
	"""
	from frappe.utils import cint
	from webshop.webshop.shopping_cart.product_info import get_product_info_for_website
	
	# Check if item exists and is a template
	template_item = frappe.get_cached_doc("Item", template_item_code)
	if not template_item.has_variants:
		return {"error": "Item is not a template"}
	
	# Get all variants
	variants = frappe.get_all(
		"Item",
		filters={
			"variant_of": template_item_code,
			"disabled": 0,
			"has_variants": 0
		},
		fields=["name", "item_code", "item_name"]
	)
	
	if not variants:
		return {"variants": [], "attributes": []}
	
	# Get attributes for this template
	attributes = frappe.get_all(
		"Item Variant Attribute",
		filters={"parent": template_item_code},
		fields=["attribute"],
		order_by="idx"
	)
	
	attributes_list = [attr.attribute for attr in attributes]
	
	# Get attribute values for all variants
	variants_info = []
	for variant in variants:
		variant_attributes = frappe.get_all(
			"Item Variant Attribute",
			filters={"parent": variant.item_code},
			fields=["attribute", "attribute_value"]
		)
		
		# Create attribute dict
		attr_dict = {
			attr.attribute: attr.attribute_value 
			for attr in variant_attributes
		}
		
		# Get product info including price
		product_info = get_product_info_for_website(
			variant.item_code, 
			skip_quotation_creation=True
		).get("product_info", {})
		
		# Check if variant is published
		is_published = frappe.db.get_value(
			"Website Item",
			{"item_code": variant.item_code},
			"published"
		)
		
		# Build variant info
		variant_info = {
			"item_code": variant.item_code,
			"item_name": variant.item_name,
			"attributes": attr_dict,
			"in_stock": product_info.get("in_stock", 0),
			"stock_qty": product_info.get("stock_qty", 0),
			"price": product_info.get("price"),
			"published": cint(is_published)
		}
		
		# Only add basic info for unpublished variants
		if not is_published:
			variant_info = {
				"item_code": variant.item_code,
				"item_name": variant.item_name,
				"attributes": attr_dict,
				"published": 0,
				"price": None,
				"in_stock": 0,
				"stock_qty": 0
			}
		
		variants_info.append(variant_info)
	
	# Calculate price range
	price_range = calculate_price_range(variants_info)
	
	return {
		"variants": variants_info,
		"attributes": attributes_list,
		"template_item": template_item.name,
		"price_range": price_range
	}


def calculate_price_range(variants):
	"""Calculate min and max price from all variants that have prices."""
	prices = []
	currency = None
	
	for variant in variants:
		if variant.get("price") and variant["price"].get("price_list_rate"):
			prices.append(variant["price"]["price_list_rate"])
			if not currency and variant["price"].get("currency"):
				currency = variant["price"]["currency"]
	
	if not prices:
		return None
	
	min_price = min(prices)
	max_price = max(prices)
	
	# Format prices
	from webshop.webshop.utils.utils import format_currency_value
	
	if min_price == max_price:
		return {
			"formatted": format_currency_value(min_price, currency=currency),
			"min": min_price,
			"max": max_price,
			"currency": currency
		}
	else:
		return {
			"formatted": f"{format_currency_value(min_price, currency=currency)} - {format_currency_value(max_price, currency=currency)}",
			"min": min_price,
			"max": max_price,
			"currency": currency
		}


@frappe.whitelist(allow_guest=True)
def get_discounted_products(item_group=None, limit=20, offset=0):
	"""
	Get products that have active discounts.
	
	This API uses an optimized query to fetch only products with discounts,
	either through pricing rules or price list differences.
	
	Args:
		item_group: Filter by specific item group
		limit: Number of items to return (default 20, max 100)
		offset: Pagination offset
		
	Returns:
		Dict with:
		- items: List of discounted products
		- total_count: Total number of discounted products
		- has_more: Boolean indicating if more results exist
	"""
	# Validate and sanitize inputs
	limit = min(int(limit or 20), 100)  # Cap at 100 items
	offset = int(offset or 0)
	
	# Get webshop settings
	settings = frappe.get_cached_doc("Webshop Settings")
	if not settings.enabled:
		return {"items": [], "total_count": 0, "has_more": False}
	
	# Build filters
	filters = {"published": 1}
	if item_group:
		filters["item_group"] = item_group
	
	# Execute optimized query
	items = get_discounted_items_query(
		price_list=settings.price_list,
		company=settings.company,
		customer_group=settings.default_customer_group,
		filters=filters,
		limit=limit + 1,  # Fetch one extra to check if more exist
		offset=offset
	)
	
	# Check if there are more items
	has_more = len(items) > limit
	if has_more:
		items = items[:limit]  # Remove the extra item
	
	# Add formatted prices and additional info
	from webshop.webshop.shopping_cart.product_info import get_product_info_for_website
	
	for item in items:
		# Get full product info
		product_info = get_product_info_for_website(item.item_code, skip_quotation_creation=True).get("product_info", {})
		
		# Add price info
		if product_info.get("price"):
			item.update({
				"formatted_price": product_info["price"].get("formatted_price"),
				"formatted_mrp": product_info["price"].get("formatted_mrp"),
				"currency": product_info["price"].get("currency")
			})
		
		# Add stock info if enabled
		if settings.show_stock_availability and product_info:
			item.update({
				"in_stock": product_info.get("in_stock", False),
				"on_backorder": product_info.get("on_backorder", False)
			})
		
		# Format discount display
		if item.get("discount_percent"):
			item["formatted_discount"] = f"{int(item.discount_percent)}% OFF"
	
	return {
		"items": items,
		"total_count": len(items),
		"has_more": has_more
	}


@frappe.whitelist(allow_guest=True)
def get_promotional_products(limit=10):
	"""
	Get products with active promotional pricing rules.
	Useful for homepage promotional sections.
	
	Args:
		limit: Number of items to return (default 10, max 50)
		
	Returns:
		List of products with promotional discounts
	"""
	# Validate input
	limit = min(int(limit or 10), 50)
	
	# Get webshop settings
	settings = frappe.get_cached_doc("Webshop Settings")
	if not settings.enabled:
		return []
	
	# Get promotional items
	items = get_items_with_pricing_rule_discount(
		price_list=settings.price_list,
		company=settings.company,
		customer_group=settings.default_customer_group,
		limit=limit
	)
	
	# Add formatted prices
	from webshop.webshop.shopping_cart.product_info import get_product_info_for_website
	
	for item in items:
		# Get full product info
		product_info = get_product_info_for_website(item.item_code, skip_quotation_creation=True).get("product_info", {})
		
		# Add price info
		if product_info.get("price"):
			item.update({
				"formatted_price": product_info["price"].get("formatted_price"),
				"formatted_mrp": product_info["price"].get("formatted_mrp"),
				"currency": product_info["price"].get("currency")
			})
		
		# Format discount display
		if item.get("effective_discount_percent"):
			item["formatted_discount"] = f"{int(item.effective_discount_percent)}% OFF"
		
		# Add promotion end date if available
		if item.get("valid_upto"):
			from frappe.utils import formatdate
			item["promotion_ends"] = formatdate(item.valid_upto)
	
	return items


@frappe.whitelist(allow_guest=True)
def get_discount_items_preview(limit=20, price_list=None):
	"""Endpoint optimized to quickly retrieve items with discount"""
	from webshop.webshop.shopping_cart.cart import get_party
	
	limit = min(int(limit or 20), 50)  # Max 50 items
	
	# Get settings
	settings = frappe.get_cached_doc("Webshop Settings")
	if not settings.enabled:
		return []
	
	if not price_list:
		price_list = settings.price_list
	
	if not price_list:
		return []
	
	#//// Neoffice multi-site: scope to the current site (also keys the cache per site)
	from webshop.webshop.multi_site import get_current_profile_name, site_sql_condition
	_site_cond = site_sql_condition("wi")

	# Use user cache
	cache_key = f"discount_preview:{frappe.session.user}:{get_current_profile_name() or 'all'}:{price_list}:{limit}"
	cached = frappe.cache().get_value(cache_key)
	if cached:
		return cached
	
	# Simplified query for preview
	party = get_party()
	customer = party.name if party else None
	
	# Query with CTE for better performance
	items = frappe.db.sql(f"""
		WITH discount_items AS (
			SELECT 
				wi.name, wi.item_code, wi.web_item_name,
				wi.thumbnail, wi.route, wi.website_image,
				wi.short_description,
				GREATEST(
					COALESCE(
						(SELECT MAX(pr.discount_percentage)
						 FROM `tabPricing Rule Item Code` pri
						 INNER JOIN `tabPricing Rule` pr ON pr.name = pri.parent
						 WHERE pri.item_code = wi.item_code
						 AND pr.disable = 0
						 AND pr.selling = 1
						 AND pr.discount_percentage > 0
						 AND (pr.valid_from IS NULL OR pr.valid_from <= CURDATE())
						 AND (pr.valid_upto IS NULL OR pr.valid_upto >= CURDATE())
						), 0
					),
					CASE 
						WHEN ip_mrp.price_list_rate > 0 AND ip.price_list_rate > 0 
						     AND ip_mrp.price_list_rate > ip.price_list_rate
						THEN ((ip_mrp.price_list_rate - ip.price_list_rate) / ip_mrp.price_list_rate * 100)
						ELSE 0
					END
				) as discount_percent,
				ip.price_list_rate,
				ip_mrp.price_list_rate as mrp
			FROM `tabWebsite Item` wi
			LEFT JOIN `tabItem Price` ip ON ip.item_code = wi.item_code 
				AND ip.price_list = %(price_list)s
				AND ip.selling = 1
				AND (ip.valid_from IS NULL OR ip.valid_from <= CURDATE())
				AND (ip.valid_upto IS NULL OR ip.valid_upto >= CURDATE())
			LEFT JOIN `tabItem Price` ip_mrp ON ip_mrp.item_code = wi.item_code
				AND ip_mrp.price_list = %(mrp_price_list)s
				AND ip_mrp.selling = 1
				AND (ip_mrp.valid_from IS NULL OR ip_mrp.valid_from <= CURDATE())
				AND (ip_mrp.valid_upto IS NULL OR ip_mrp.valid_upto >= CURDATE())
			WHERE wi.published = 1{_site_cond}
		)
		SELECT * FROM discount_items
		WHERE discount_percent > 0
		ORDER BY discount_percent DESC, name
		LIMIT %(limit)s
	""", {
		'price_list': price_list,
		'mrp_price_list': getattr(settings, 'mrp_price_list', price_list) or price_list,
		'limit': limit
	}, as_dict=True)
	
	# Format prices
	from webshop.webshop.utils.utils import format_currency_value
	currency = frappe.db.get_value("Company", settings.company, "default_currency") if settings.company else "USD"
	
	for item in items:
		if item.get("price_list_rate"):
			item["formatted_price"] = format_currency_value(item.price_list_rate, currency=currency)
			if item.get("mrp") and item.mrp > item.price_list_rate:
				item["formatted_mrp"] = format_currency_value(item.mrp, currency=currency)
			if item.get("discount_percent"):
				item["discount"] = f"{int(item.discount_percent)}% OFF"
		
		# Clean up fields
		for field in ["price_list_rate", "mrp"]:
			if field in item:
				del item[field]
	
	# Cache for 5 minutes
	frappe.cache().set_value(cache_key, items, expires_in_sec=300)
	return items


@frappe.whitelist()
def import_gift_cards(file_content=None, dry_run=False):
	"""API endpoint to import gift cards from Excel file"""
	return import_gift_cards_from_excel(file_content, dry_run)


@frappe.whitelist()
def download_gift_card_template():
	"""API endpoint to download gift card import template"""
	return get_gift_card_import_template()


@frappe.whitelist()
def clear_webshop_cache():
	"""
	Manually clear all webshop caches.

	Requires System Manager role.
	Clears carousel cache, product price cache, discount cache, etc.

	Returns:
		dict: Status and message
	"""
	if "System Manager" not in frappe.get_roles():
		frappe.throw(_("Only System Manager can clear webshop cache"))

	try:
		# Clear carousel cache
		from webshop.webshop.utils.carousel_cache import CarouselCacheManager
		cache_manager = CarouselCacheManager()
		cache_manager.clear_cache()

		# Clear promotion cache
		cache_manager.clear_promotion_cache()

		# Clear brand carousel cache
		try:
			from webshop.webshop.utils.brand_carousel_helper import clear_brand_carousel_cache
			clear_brand_carousel_cache()
		except ImportError:
			pass

		# Clear product price caches
		cache_keys = frappe.cache().get_keys("discount_preview:*")
		for key in cache_keys:
			frappe.cache().delete_value(key)

		cache_keys = frappe.cache().get_keys("product_info:*")
		for key in cache_keys:
			frappe.cache().delete_value(key)

		cache_keys = frappe.cache().get_keys("webshop_item:*")
		for key in cache_keys:
			frappe.cache().delete_value(key)

		frappe.logger().info("Webshop cache manually cleared by " + frappe.session.user)

		return {
			"status": "success",
			"message": _("Webshop cache cleared successfully")
		}

	except Exception as e:
		frappe.log_error(f"Error clearing webshop cache: {str(e)}", "Webshop Cache Clear Error")
		return {
			"status": "error",
			"message": str(e)
		}


# Address Management API
@frappe.whitelist()
def get_address(address_name):
	"""Get address details for editing"""
	from webshop.webshop.shopping_cart.cart import get_party

	if frappe.session.user == "Guest":
		frappe.throw(_("Please login to continue"))

	party = get_party()
	if not party:
		frappe.throw(_("No customer account found"))

	# Check if address belongs to this customer
	address = frappe.get_doc("Address", address_name)
	is_linked = False
	for link in address.links:
		if link.link_doctype == "Customer" and link.link_name == party.name:
			is_linked = True
			break

	if not is_linked:
		frappe.throw(_("Address not found or access denied"))

	return {
		"name": address.name,
		"address_title": address.address_title,
		"address_line1": address.address_line1,
		"address_line2": address.address_line2,
		"city": address.city,
		"state": address.state,
		"country": address.country,
		"pincode": address.pincode,
		"phone": address.phone,
		"email_id": address.email_id,
		"is_primary_address": address.is_primary_address,
		"is_shipping_address": address.is_shipping_address
	}


@frappe.whitelist()
def update_address(address_name, address_data):
	"""Update an existing address"""
	from webshop.webshop.shopping_cart.cart import get_party

	if frappe.session.user == "Guest":
		frappe.throw(_("Please login to continue"))

	party = get_party()
	if not party:
		frappe.throw(_("No customer account found"))

	# Parse address data if string
	if isinstance(address_data, str):
		address_data = json.loads(address_data)

	# Check if address belongs to this customer
	address = frappe.get_doc("Address", address_name)
	is_linked = False
	for link in address.links:
		if link.link_doctype == "Customer" and link.link_name == party.name:
			is_linked = True
			break

	if not is_linked:
		frappe.throw(_("Address not found or access denied"))

	# Update address fields
	address.address_title = address_data.get("address_title")
	address.address_line1 = address_data.get("address_line1")
	address.address_line2 = address_data.get("address_line2")
	address.city = address_data.get("city")
	address.state = address_data.get("state")
	address.country = address_data.get("country")
	address.pincode = address_data.get("pincode")
	address.phone = address_data.get("phone")
	address.email_id = address_data.get("email_id")
	address.is_primary_address = address_data.get("is_primary_address", 0)
	address.is_shipping_address = address_data.get("is_shipping_address", 0)

	address.save()

	# Update customer's primary address if needed
	if address.is_primary_address:
		from frappe.contacts.doctype.address.address import get_address_display
		customer = frappe.get_doc("Customer", party.name)
		customer.customer_primary_address = address.name
		customer.primary_address = get_address_display(address.name)
		customer.save(ignore_permissions=True)

	frappe.db.commit()

	return {"success": True, "message": _("Address updated successfully")}


@frappe.whitelist()
def delete_address(address_name):
	"""Delete an address if it belongs to the current user's customer"""
	from webshop.webshop.shopping_cart.cart import get_party

	if frappe.session.user == "Guest":
		frappe.throw(_("Please login to continue"))

	party = get_party()
	if not party:
		frappe.throw(_("No customer account found"))

	# Check if address belongs to this customer
	address = frappe.get_doc("Address", address_name)
	is_linked = False
	for link in address.links:
		if link.link_doctype == "Customer" and link.link_name == party.name:
			is_linked = True
			break

	if not is_linked:
		frappe.throw(_("Address not found or access denied"))

	# Check if address is used in any pending quotations
	quotations = frappe.get_all(
		"Quotation",
		filters={
			"party_name": party.name,
			"docstatus": 0,
			"customer_address": address_name
		}
	)
	if quotations:
		# Clear address from quotations first
		for q in quotations:
			frappe.db.set_value("Quotation", q.name, "customer_address", None)

	quotations_shipping = frappe.get_all(
		"Quotation",
		filters={
			"party_name": party.name,
			"docstatus": 0,
			"shipping_address_name": address_name
		}
	)
	if quotations_shipping:
		for q in quotations_shipping:
			frappe.db.set_value("Quotation", q.name, "shipping_address_name", None)

	# Delete the address (ignore_permissions because we already verified ownership via customer link)
	frappe.delete_doc("Address", address_name, ignore_permissions=True)
	frappe.db.commit()

	return {"success": True, "message": _("Address deleted successfully")}

@frappe.whitelist(allow_guest=True)
def get_cart_recommendations(item_codes=None, limit=4):
	"""Frequently-bought-together suggestions for the cart drawer.

	Takes the cart's item codes and returns up to `limit` related products
	(pre-computed from 6 months of sales), excluding what's already in the cart.
	"""
	import json as _json

	from webshop.webshop.utils.frequently_bought_together import get_frequently_bought_together

	if isinstance(item_codes, str):
		try:
			item_codes = _json.loads(item_codes or "[]")
		except ValueError:
			item_codes = []
	item_codes = [c for c in (item_codes or []) if c][:10]
	if not item_codes:
		return []

	limit = min(int(limit or 4), 8)
	seen, out = set(item_codes), []
	for code in item_codes:
		for it in get_frequently_bought_together(code, limit=limit):
			if it.item_code in seen:
				continue
			seen.add(it.item_code)
			out.append({
				"item_code": it.item_code,
				"name": it.web_item_name,
				"route": it.route,
				"image": it.website_image or it.thumbnail or "",
				"price": it.get("formatted_price") or "",
			})
			if len(out) >= limit:
				return out
	return out
