# -*- coding: utf-8 -*-
# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.utils import cint

from webshop.webshop.product_data_engine.filters import ProductFiltersBuilder
from webshop.webshop.product_data_engine.query import ProductQuery
from webshop.webshop.doctype.override_doctype.item_group import get_child_groups_for_website
from webshop.webshop.utils.discount_query import get_discounted_items_query, get_items_with_pricing_rule_discount


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
			["name", "published", "website_image", "on_backorder"],
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
			
			# Get price
			if price_list:
				price_obj = frappe.db.get_value(
					"Item Price",
					{
						"item_code": variant.item_code,
						"price_list": price_list,
						"selling": 1
					},
					["price_list_rate", "currency"],
					as_dict=True
				)
				
				if price_obj:
					formatted_price = frappe.utils.fmt_money(
						price_obj.price_list_rate,
						currency=price_obj.currency
					)
					
					variant_data["price"] = {
						"price_list_rate": price_obj.price_list_rate,
						"formatted_price": formatted_price,
						"currency": price_obj.currency
					}
					
					# Track min/max prices
					if price_min is None or price_obj.price_list_rate < price_min:
						price_min = price_obj.price_list_rate
					if price_max is None or price_obj.price_list_rate > price_max:
						price_max = price_obj.price_list_rate
		
		variants_data.append(variant_data)
	
	# Build price range
	price_range = None
	if price_min is not None and price_max is not None:
		currency = frappe.db.get_value("Price List", price_list, "currency") if price_list else None
		if price_min == price_max:
			price_range = {
				"min": price_min,
				"max": price_max,
				"formatted": frappe.utils.fmt_money(price_min, currency=currency)
			}
		else:
			price_range = {
				"min": price_min,
				"max": price_max,
				"formatted": f"{frappe.utils.fmt_money(price_min, currency=currency)} - {frappe.utils.fmt_money(price_max, currency=currency)}"
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
			# Get price with pricing rules
			price_obj = get_price(
				item_code,
				price_list,
				customer_group=frappe.db.get_single_value("Webshop Settings", "default_customer_group"),
				company=frappe.db.get_single_value("Webshop Settings", "company"),
				qty=1
			)
			
			if price_obj:
				formatted_price = frappe.utils.fmt_money(
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
					result[item_code]["formatted_mrp"] = frappe.utils.fmt_money(base_price, currency=currency)
			else:
				# No pricing rule, use base price
				result[item_code] = {
					"price_list_rate": base_price,
					"formatted_price": frappe.utils.fmt_money(base_price, currency=currency)
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
	from frappe.utils import fmt_money
	
	if min_price == max_price:
		return {
			"formatted": fmt_money(min_price, currency=currency),
			"min": min_price,
			"max": max_price,
			"currency": currency
		}
	else:
		return {
			"formatted": f"{fmt_money(min_price, currency=currency)} - {fmt_money(max_price, currency=currency)}",
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