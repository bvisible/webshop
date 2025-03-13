# -*- coding: utf-8 -*-
# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.utils import cint

from webshop.webshop.product_data_engine.filters import ProductFiltersBuilder
from webshop.webshop.product_data_engine.query import ProductQuery
from webshop.webshop.doctype.override_doctype.item_group import get_child_groups_for_website


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

	query_args = frappe._dict(query_args)

	if query_args:
		search = query_args.get("search")
		field_filters = query_args.get("field_filters", {})
		attribute_filters = query_args.get("attribute_filters", {})
		
		# Try to parse price_range
		price_range_param = query_args.get("price_range", {})
		
		try:
			# If price_range is already a dictionary, use it directly
			if isinstance(price_range_param, dict):
				price_range = price_range_param
			else:
				price_range = json.loads(price_range_param) if price_range_param else {}
			
		except Exception as e:
			frappe.log_error("Price Filter Debug", f"Error parsing price_range: {e}")
			price_range = {}
		
		start = cint(query_args.start) if query_args.get("start") else 0
		item_group = query_args.get("item_group")
		from_filters = query_args.get("from_filters")
	else:
		search, attribute_filters, item_group, from_filters = None, None, None, None
		field_filters = {}
		price_range = {}
		start = 0

	# if new filter is checked, reset start to show filtered items from page 1
	if from_filters:
		start = 0

	sub_categories = []
	if item_group:
		sub_categories = get_child_groups_for_website(item_group, immediate=True)

	engine = ProductQuery()

	try:
		# Add price condition if specified
		# Prepare price conditions for the query
		price_condition = {}
		if price_range:			
			# Convert values to float to avoid type conversion issues
			if price_range.get("min") is not None:
				try:
					price_condition["min_price"] = float(price_range.get("min"))
				except (ValueError, TypeError):
					frappe.log_error("Price Filter Debug", f"Error converting min_price: {price_range.get('min')}")
			
			if price_range.get("max") is not None:
				try:
					price_condition["max_price"] = float(price_range.get("max"))
				except (ValueError, TypeError):
					frappe.log_error("Price Filter Debug", f"Error converting max_price: {price_range.get('max')}")

		result = engine.query(
			attribute_filters,
			field_filters,
			search_term=search,
			start=start,
			item_group=item_group,
			price_condition=price_condition
		)
		
		# Get total count
		engine.page_length = 0 
		total_result = engine.query(
			attribute_filters,
			field_filters,
			search_term=search,
			start=0,
			item_group=item_group,
			price_condition=price_condition
		)
		engine.page_length = engine.settings.products_per_page or 20  # Restore pagination
	except Exception:
		frappe.log_error("Product query with filter failed")
		return {"exc": "Something went wrong!"}

	# discount filter data
	filters = {}
	discounts = result["discounts"]

	# Initialize filter engine
	filter_engine = ProductFiltersBuilder(item_group)

	# Add discount filters if available
	if discounts:
		filters["discount_filters"] = filter_engine.get_discount_filters(discounts)
	
	# Add tag filters if enabled in settings
	if frappe.db.get_single_value("Webshop Settings", "enable_tag_filters"):
		tag_filters = filter_engine.get_tag_filters()
		if tag_filters:
			filters["tag_filters"] = tag_filters
			
	# Add price filters if enabled in settings
	if frappe.db.get_single_value("Webshop Settings", "enable_price_filter"):
		price_filters = filter_engine.get_price_filters()
		if price_filters:
			filters["price_filters"] = price_filters

	return {
		"items": result["items"] or [],
		"filters": filters,
		"settings": engine.settings,
		"sub_categories": sub_categories,
		"items_count": len(result["items"]),
		"total_count": len(result["items"]) if field_filters.get("discount") else total_result["items_count"],
	}


@frappe.whitelist(allow_guest=True)
def get_guest_redirect_on_action():
	return frappe.db.get_single_value("Webshop Settings", "redirect_on_action")


@frappe.whitelist(allow_guest=True)
def get_product_price_info(items):
	"""
	Get product price information for a list of items.

	Args:
		items (list): List of item codes

	Returns:
		dict: Dictionary with item codes as keys and price information as values
	"""
	if isinstance(items, str):
		items = json.loads(items)

	if not items:
		return {}

	from webshop.webshop.shopping_cart.product_info import get_product_info_for_website

	result = {}
	for item_code in items:
		product_info = get_product_info_for_website(item_code, skip_quotation_creation=True)
		price_info = {}

		if product_info and product_info.get("product_info") and product_info["product_info"].get("price"):
			price = product_info["product_info"]["price"]
			price_info = {
				"formatted_price": price.get("formatted_price"),
				"formatted_mrp": price.get("formatted_mrp"),
				"discount": price.get("discount_percent")
			}

		result[item_code] = price_info

	return result
