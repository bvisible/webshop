# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe.utils import flt

from webshop.webshop.doctype.item_review.item_review import get_customer
from webshop.webshop.shopping_cart.product_info import get_product_info_for_website
from webshop.webshop.utils.product import get_non_stock_item_status
from webshop.webshop.utils.loyalty_points import format_loyalty_points_message
from webshop.webshop.shopping_cart.cart import get_party


class ProductQuery:
	"""Query engine for product listing

	Attributes:
	        fields (list): Fields to fetch in query
	        conditions (string): Conditions for query building
	        or_conditions (string): Search conditions
	        page_length (Int): Length of page for the query
	        settings (Document): Webshop Settings DocType
	"""

	def __init__(self):
		self.settings = frappe.get_doc("Webshop Settings")
		self.page_length = self.settings.products_per_page or 20

		self.or_filters = []
		self.filters = [["published", "=", 1]]
		#//// Neoffice multi-site: hide items restricted to other sites
		#//// (empty child table = visible everywhere -> empty list = no-op).
		from webshop.webshop.multi_site import excluded_item_names

		excluded = excluded_item_names()
		if excluded:
			self.filters.append(["name", "not in", excluded])
		self.fields = [
			"web_item_name",
			"name",
			"item_name",
			"item_code",
			"website_image",
			"image_focus",
			"variant_of",
			"has_variants",
			"item_group",
			"web_long_description",
			"short_description",
			"route",
			"website_warehouse",
			"ranking",
			"on_backorder",
			"is_gift_card",
		]
		self._total_count_cache = None
		# For multi-word search with custom SQL
		self._search_sql_condition = None
		self._search_values = []
		# Store search term for match priority ordering
		self._search_term = None

	def query(self, attributes=None, fields=None, search_term=None, start=0, item_group=None, price_condition=None, sort_order=None):
		"""
		Args:
		        attributes (dict, optional): Item Attribute filters
		        fields (dict, optional): Field level filters
		        search_term (str, optional): Search term to lookup
		        start (int, optional): Page start
		        sort_order (str, optional): Sort order (relevance, price_low_to_high, price_high_to_low, new_arrivals, rating)

		Returns:
		        dict: Dict containing items, item count & discount range
		"""
		# Track if discounts included in field filters
		self.filter_with_discount = bool(fields.get("discount"))
		result, discount_list, website_item_groups, cart_items, count = [], [], [], [], 0

		if fields:
			self.build_fields_filters(fields)
		if item_group:
			self.build_item_group_filters(item_group)
		if search_term:
			self.build_search_filters(search_term)
		if self.settings.hide_variants:
			self.filters.append(["variant_of", "is", "not set"])
		if price_condition:
			self.build_price_filters(price_condition)
		# Add stock filter if requested
		if fields and fields.get("in_stock"):
			self.build_stock_filters(True)

		# Store sort order for use in query
		self.sort_order = sort_order
		
		
		# query results with proper sorting
		if attributes:
			result, count = self.query_items_with_attributes(attributes, start)
		else:
			result, count = self.query_items(start=start)

		if self.settings.enabled:
			cart_items = self.get_cart_items()

		result, discount_list = self.add_display_details(result, discount_list, cart_items)

		discounts = []
		if discount_list:
			discounts = [min(discount_list), max(discount_list)]

		# Note: Discount filtering is now handled directly in the query methods
		# for better performance (query_items_with_discount_filter and 
		# query_items_with_discount_and_price_sort)

		return {
			"items": result, 
			"items_count": len(result),
			"total_count": count,  # This is the count before discount filter
			"discounts": discounts
		}

	def query_items(self, start=0):
		"""Build a query to fetch Website Items based on field filters."""
		# Get total count using get_all with limit 0 for better performance
		# Cache the count for the same filters to avoid repeated queries
		count_filters = self.filters.copy()
		
		# Create a cache key based on filters
		cache_key = frappe.utils.cstr(count_filters) + frappe.utils.cstr(self.or_filters)
		
		if self._total_count_cache and self._total_count_cache.get('key') == cache_key:
			count = self._total_count_cache.get('count')
		else:
			# Build SQL query for counting with proper handling of filters and or_filters
			conditions = []
			values = []
			
			# Handle regular filters
			if count_filters:
				for filter_item in count_filters:
					if isinstance(filter_item, list) and len(filter_item) >= 3:
						field, operator, value = filter_item[0], filter_item[1], filter_item[2]
						if operator == "=":
							conditions.append(f"`{field}` = %s")
							values.append(value)
						elif operator == "in":
							if isinstance(value, list):
								placeholders = ", ".join(["%s"] * len(value))
								conditions.append(f"`{field}` IN ({placeholders})")
								values.extend(value)
						elif operator == "not in":
							#//// Neoffice multi-site: items restricted to other sites
							if isinstance(value, list) and value:
								placeholders = ", ".join(["%s"] * len(value))
								conditions.append(f"`{field}` NOT IN ({placeholders})")
								values.extend(value)
						elif operator == "is":
							if value == "not set":
								conditions.append(f"`{field}` IS NULL")
			
			# Handle or_filters
			or_conditions = []
			if self.or_filters:
				for or_filter in self.or_filters:
					if isinstance(or_filter, list) and len(or_filter) >= 3:
						field, operator, value = or_filter[0], or_filter[1], or_filter[2]
						if operator == "like":
							# Check if field contains LOWER() function call
							if field.startswith("LOWER("):
								or_conditions.append(f"{field} LIKE %s")
							else:
								or_conditions.append(f"`{field}` LIKE %s")
							values.append(value)
						elif operator == "=":
							or_conditions.append(f"`{field}` = %s")
							values.append(value)
						elif operator == "in":
							if isinstance(value, list):
								placeholders = ", ".join(["%s"] * len(value))
								or_conditions.append(f"`{field}` IN ({placeholders})")
								values.extend(value)

			# Build final WHERE clause
			where_clause = ""
			if conditions:
				where_clause = " WHERE " + " AND ".join(conditions)

			# Handle multi-word search with custom SQL condition
			if self._search_sql_condition:
				search_clause = f"({self._search_sql_condition})"
				values.extend(self._search_values)
				if where_clause:
					where_clause += " AND " + search_clause
				else:
					where_clause = " WHERE " + search_clause
			elif or_conditions:
				or_clause = " (" + " OR ".join(or_conditions) + ")"
				if where_clause:
					where_clause += " AND " + or_clause
				else:
					where_clause = " WHERE " + or_clause
			
			# Execute count query
			count_sql = f"SELECT COUNT(*) FROM `tabWebsite Item`{where_clause}"
			count = frappe.db.sql(count_sql, values)[0][0]
			self._total_count_cache = {'key': cache_key, 'count': count}
			

		# Check if we need special handling for discount filter
		if self.filter_with_discount:
			# Check if we also need price sorting
			if hasattr(self, 'sort_order') and self.sort_order in ["price_low_to_high", "price_high_to_low"]:
				# For discount + price sort, the price sort method will handle it
				pass  # Continue with normal flow
			else:
				# Use optimized query for discount filter only
				return self.query_items_with_discount_filter(start)
		
		# Determine order_by based on sort_order
		if hasattr(self, 'sort_order') and self.sort_order:
			if self.sort_order == "new_arrivals":
				order_by = "creation desc"
			elif self.sort_order == "rating":
				# TODO: Add average_rating field to Website Item
				order_by = "ranking desc"  # Fallback to ranking for now
			elif self.sort_order in ["price_low_to_high", "price_high_to_low"]:
				# For price sorting, we need a custom query
				return self.query_items_with_price_sort(start, self.sort_order)
			else:
				order_by = "ranking desc"
		else:
			order_by = "ranking desc"
		
		# Standard pagination
		page_length = self.page_length
		effective_start = start

		# If we have a search term, use custom SQL to support match priority ordering
		if self._search_term:
			items = self._query_items_with_custom_search(
				page_length, effective_start, order_by
			)
		else:
			items = frappe.db.get_all(
				"Website Item",
				fields=self.fields,
				filters=self.filters,
				or_filters=self.or_filters,
				limit_page_length=page_length,
				limit_start=effective_start,
				order_by=order_by,
			)

		return items, count

	def _query_items_with_custom_search(self, page_length, start, order_by):
		"""Execute query with custom SQL search condition for multi-word search.

		Args:
			page_length (int): Number of items per page
			start (int): Offset for pagination
			order_by (str): ORDER BY clause

		Returns:
			list: List of Website Item dicts
		"""
		# Build field list
		field_list = ", ".join([f"`{field}`" for field in self.fields])

		# Build WHERE conditions from self.filters
		conditions = []
		values = []

		# Add match priority values first (they come before WHERE clause values)
		priority_sql, priority_values = self._get_match_priority_sql()
		if priority_sql:
			values.extend(priority_values)

		for filter_item in self.filters:
			if isinstance(filter_item, list) and len(filter_item) >= 3:
				field, operator, value = filter_item[0], filter_item[1], filter_item[2]
				if operator == "=":
					conditions.append(f"`{field}` = %s")
					values.append(value)
				elif operator == "in":
					if isinstance(value, list):
						placeholders = ", ".join(["%s"] * len(value))
						conditions.append(f"`{field}` IN ({placeholders})")
						values.extend(value)
				elif operator == "not in":
					#//// Neoffice multi-site: items restricted to other sites
					if isinstance(value, list) and value:
						placeholders = ", ".join(["%s"] * len(value))
						conditions.append(f"`{field}` NOT IN ({placeholders})")
						values.extend(value)
				elif operator == "is":
					if value == "not set":
						conditions.append(f"`{field}` IS NULL")

		# Add the custom search condition (for multi-word search)
		if self._search_sql_condition:
			conditions.append(f"({self._search_sql_condition})")
			values.extend(self._search_values)
		# Handle single-word search with or_filters
		elif self.or_filters:
			or_conditions = []
			for or_filter in self.or_filters:
				if isinstance(or_filter, list) and len(or_filter) >= 3:
					field, operator, value = or_filter[0], or_filter[1], or_filter[2]
					if operator == "like":
						or_conditions.append(f"`{field}` LIKE %s")
						values.append(value)
			if or_conditions:
				conditions.append(f"({' OR '.join(or_conditions)})")

		# Build WHERE clause
		where_clause = " AND ".join(conditions) if conditions else "1=1"

		# Build ORDER BY with match priority if search is active
		if priority_sql:
			final_order_by = f"match_priority ASC, {order_by}"
			query = f"""
				SELECT {field_list}, {priority_sql} as match_priority
				FROM `tabWebsite Item`
				WHERE {where_clause}
				ORDER BY {final_order_by}
				LIMIT %s OFFSET %s
			"""
		else:
			query = f"""
				SELECT {field_list}
				FROM `tabWebsite Item`
				WHERE {where_clause}
				ORDER BY {order_by}
				LIMIT %s OFFSET %s
			"""
		values.extend([page_length, start])

		results = frappe.db.sql(query, values, as_dict=True)

		# Remove match_priority from results (internal use only)
		for r in results:
			r.pop("match_priority", None)

		return results
	
	def query_items_with_discount_filter(self, start=0):
		"""Query items that have active discounts using optimized SQL."""
		# Use the new optimized method with caching
		return self.query_items_with_discount_optimized(start)
	
	def query_items_with_discount_and_price_sort(self, start, sort_order, price_list, where_clause, values):
		"""Optimized query for items with discounts, sorted by price"""
		# Build field list
		field_list = ", ".join([f"wi.`{field}`" for field in self.fields])
		
		# Determine sort direction and aggregate function
		is_price_sort = sort_order in ["price_low_to_high", "price_high_to_low"]
		sort_direction = "ASC" if sort_order == "price_low_to_high" else "DESC"
		aggregate_func = "MIN" if sort_order == "price_low_to_high" else "MAX"
		default_price = "999999999" if sort_order == "price_low_to_high" else "0"
		
		# Determine ORDER BY clause
		if is_price_sort:
			order_by = f"current_price {sort_direction}, ranking DESC"
		elif sort_order == "new_arrivals":
			order_by = "creation DESC, ranking DESC"
		elif sort_order == "rating":
			order_by = "ranking DESC"
		elif sort_order == "relevance":
			order_by = "ranking DESC"
		else:
			order_by = "ranking DESC"
		
		# Build optimized query that combines discount detection and price sorting
		query_sql = f"""
		WITH discounted_items AS (
			SELECT 
				{field_list},
				wi.creation,
				COALESCE(
					CASE 
						WHEN wi.has_variants = 1 THEN
							(SELECT {aggregate_func}(vip.price_list_rate)
							 FROM `tabItem Price` vip
							 INNER JOIN `tabItem` vi ON vi.name = vip.item_code
							 WHERE vi.variant_of = wi.item_code
							 AND vip.selling = 1
							 AND vip.price_list = %s
							 AND vip.price_list_rate > 0)
						ELSE ip.price_list_rate
					END,
					{default_price}
				) as current_price,
				GREATEST(
					-- Pricing rule discount
					COALESCE(pr.discount_percentage, 0),
					-- Price list comparison discount
					CASE 
						WHEN ip_mrp.price_list_rate > 0 AND ip.price_list_rate > 0 
						THEN ((ip_mrp.price_list_rate - ip.price_list_rate) / ip_mrp.price_list_rate * 100)
						ELSE 0
					END
				) as discount_percent,
				ip.price_list_rate,
				ip_mrp.price_list_rate as mrp
			FROM `tabWebsite Item` wi
			LEFT JOIN `tabItem Price` ip ON wi.item_code = ip.item_code 
				AND ip.selling = 1 
				AND ip.price_list = %s
			LEFT JOIN `tabItem Price` ip_mrp ON wi.item_code = ip_mrp.item_code 
				AND ip_mrp.selling = 1 
				AND ip_mrp.price_list != %s
				AND ip_mrp.price_list_rate > COALESCE(ip.price_list_rate, 0)
			LEFT JOIN (
				-- Get best discount from pricing rules
				SELECT 
					pri.item_code,
					MAX(pr.discount_percentage) as discount_percentage
				FROM `tabPricing Rule` pr
				INNER JOIN `tabPricing Rule Item Code` pri ON pri.parent = pr.name
				WHERE pr.disable = 0
				AND pr.selling = 1
				AND pr.discount_percentage > 0
				AND (pr.valid_from IS NULL OR pr.valid_from <= CURDATE())
				AND (pr.valid_upto IS NULL OR pr.valid_upto >= CURDATE())
				GROUP BY pri.item_code
			) pr ON wi.item_code = pr.item_code
			{where_clause}
		)
		SELECT *
		FROM discounted_items
		WHERE discount_percent > 0
		ORDER BY {order_by}
		LIMIT %s OFFSET %s
		"""
		
		# Build values list
		query_values = [price_list, price_list, price_list]  # For the price lookups
		query_values.extend(values)  # For WHERE conditions
		query_values.extend([self.page_length, start])  # For LIMIT and OFFSET
		
		items = frappe.db.sql(query_sql, query_values, as_dict=True)
		
		# Get count of discounted items
		count_sql = f"""
		SELECT COUNT(*)
		FROM (
			SELECT wi.name
			FROM `tabWebsite Item` wi
			LEFT JOIN `tabItem Price` ip ON wi.item_code = ip.item_code 
				AND ip.selling = 1 
				AND ip.price_list = %s
			LEFT JOIN `tabItem Price` ip_mrp ON wi.item_code = ip_mrp.item_code 
				AND ip_mrp.selling = 1 
				AND ip_mrp.price_list != %s
				AND ip_mrp.price_list_rate > COALESCE(ip.price_list_rate, 0)
			LEFT JOIN (
				SELECT 
					pri.item_code,
					MAX(pr.discount_percentage) as discount_percentage
				FROM `tabPricing Rule` pr
				INNER JOIN `tabPricing Rule Item Code` pri ON pri.parent = pr.name
				WHERE pr.disable = 0
				AND pr.selling = 1
				AND pr.discount_percentage > 0
				AND (pr.valid_from IS NULL OR pr.valid_from <= CURDATE())
				AND (pr.valid_upto IS NULL OR pr.valid_upto >= CURDATE())
				GROUP BY pri.item_code
			) pr ON wi.item_code = pr.item_code
			{where_clause}
			AND (pr.discount_percentage > 0 OR (ip_mrp.price_list_rate > 0 AND ip.price_list_rate > 0))
		) as discounted_count
		"""
		
		count_values = [price_list, price_list]
		count_values.extend(values)
		count = frappe.db.sql(count_sql, count_values)[0][0]
		
		# Add additional item details
		discount_list = []
		cart_items = self.get_cart_items() if self.settings.enabled else []
		
		for item in items:
			# Format price info
			if item.get("price_list_rate"):
				from webshop.webshop.utils.utils import format_currency_value
				currency = frappe.db.get_single_value("Webshop Settings", "company") 
				if currency:
					currency = frappe.db.get_value("Company", currency, "default_currency") or "USD"
				else:
					currency = "USD"
				
				item["currency"] = currency
				item["formatted_price"] = format_currency_value(item.price_list_rate, currency=currency)
				if item.get("mrp") and item.mrp > item.price_list_rate:
					item["formatted_mrp"] = format_currency_value(item.mrp, currency=currency)
				
				if item.get("discount_percent"):
					item["discount_percent"] = flt(item.discount_percent)
					discount_list.append(item.discount_percent)
					item["discount"] = f"{int(item.discount_percent)}% OFF"
			
			# Add stock info
			if self.settings.show_stock_availability:
				self.get_stock_availability(item)
			
			# Check cart and wishlist status
			item.in_cart = item.item_code in cart_items
			item.wished = frappe.db.exists("Wishlist Item", {"item_code": item.item_code, "parent": frappe.session.user})
			
			# Add loyalty points information if enabled
			if self.settings.enable_loyalty_points and (frappe.session.user != "Guest" or self.settings.show_loyalty_points_for_guests):
				if item.get("formatted_price") and item.get("current_price"):
					customer = frappe.session.user if frappe.session.user != "Guest" else None
					loyalty_info = format_loyalty_points_message(item.item_code, item.current_price, 1, customer)
					if loyalty_info and loyalty_info.get("earned_text"):
						item.loyalty_points_html = loyalty_info["earned_text"]
			
			# Clean up temporary fields
			for field in ["current_price", "price_list_rate", "mrp"]:
				if field in item:
					del item[field]
		
		return items, count
	
	def query_items_with_regular_discount_flow(self, start):
		"""Fallback method using regular flow with buffer for discount filtering."""
		# Temporarily disable filter_with_discount to avoid recursion
		self.filter_with_discount = False
		
		# Fetch more items with buffer
		old_page_length = self.page_length
		self.page_length = old_page_length * 20  # 20x buffer
		
		# Get items using regular query
		items, count = self.query_items(start)
		
		# Restore page length
		self.page_length = old_page_length
		self.filter_with_discount = True
		
		return items, count
	
	def query_items_with_price_sort(self, start, sort_order):
		"""Query items with price-based sorting using SQL join"""
		# Get default price list from settings
		price_list = frappe.db.get_single_value("Webshop Settings", "price_list")
		
		# Build WHERE conditions
		conditions = []
		values = []
		
		# Add filters
		for filter_item in self.filters:
			if isinstance(filter_item, list) and len(filter_item) >= 3:
				field, operator, value = filter_item[0], filter_item[1], filter_item[2]
				
				if operator == "=":
					conditions.append(f"wi.`{field}` = %s")
					values.append(value)
				elif operator == "in" and isinstance(value, list):
					placeholders = ", ".join(["%s"] * len(value))
					conditions.append(f"wi.`{field}` IN ({placeholders})")
					values.extend(value)
				elif operator == "not in" and isinstance(value, list) and value:
					#//// Neoffice multi-site: items restricted to other sites
					placeholders = ", ".join(["%s"] * len(value))
					conditions.append(f"wi.`{field}` NOT IN ({placeholders})")
					values.extend(value)
				elif operator == "is":
					if value == "not set":
						conditions.append(f"wi.`{field}` IS NULL")
		
		# Add or_filters (for search)
		or_conditions = []
		if self.or_filters:
			for or_filter in self.or_filters:
				if isinstance(or_filter, list) and len(or_filter) >= 3:
					field, operator, value = or_filter[0], or_filter[1], or_filter[2]
					
					if operator == "like":
						or_conditions.append(f"wi.`{field}` LIKE %s")
						values.append(value)
					elif operator == "=":
						or_conditions.append(f"wi.`{field}` = %s")
						values.append(value)
		
		# Build final WHERE clause
		where_parts = []
		if conditions:
			where_parts.append(" AND ".join(conditions))
		if or_conditions:
			where_parts.append("(" + " OR ".join(or_conditions) + ")")
		
		where_clause = " WHERE " + " AND ".join(where_parts) if where_parts else ""
		
		# If discount filter is active, use optimized query
		if self.filter_with_discount and price_list:
			return self.query_items_with_discount_and_price_sort(start, sort_order, price_list, where_clause, values)
		
		# Count query - create a copy of values for count query
		count_values = values.copy()
		count_sql = f"""
			SELECT COUNT(DISTINCT wi.name) 
			FROM `tabWebsite Item` wi
			{where_clause}
		"""
		count = frappe.db.sql(count_sql, count_values)[0][0]
		
		# Main query with price join
		order_clause = "ASC" if sort_order == "price_low_to_high" else "DESC"
		
		# Build field list
		field_list = ", ".join([f"wi.`{field}`" for field in self.fields])
		
		# For templates with variants, we need to get the min or max price of their variants
		# For "low to high", use MIN price and 999999999 as default for items without price (they appear last)
		# For "high to low", use MAX price and 0 as default (they appear first)
		default_price = "999999999" if sort_order == "price_low_to_high" else "0"
		aggregate_func = "MIN" if sort_order == "price_low_to_high" else "MAX"
		
		# Build the query SQL with proper parameter placeholders
		if price_list:
			query_sql = f"""
				SELECT DISTINCT {field_list}, 
					CASE 
						WHEN wi.has_variants = 1 THEN
							COALESCE(
								(SELECT {aggregate_func}(vip.price_list_rate)
								 FROM `tabItem Price` vip
								 INNER JOIN `tabItem` vi ON vi.name = vip.item_code
								 WHERE vi.variant_of = wi.item_code
								 AND vip.selling = 1
								 AND vip.price_list = %s
								 AND vip.price_list_rate > 0),
								{default_price}
							)
						ELSE 
							COALESCE(ip.price_list_rate, {default_price})
					END as sort_price
				FROM `tabWebsite Item` wi
				LEFT JOIN `tabItem Price` ip ON wi.item_code = ip.item_code 
					AND ip.selling = 1 
					AND ip.price_list = %s
				{where_clause}
				ORDER BY sort_price {order_clause}, wi.ranking DESC
				LIMIT %s OFFSET %s
			"""
			
			# Build values list for the query in the correct order
			# The price_list parameters come BEFORE the WHERE clause in the SQL
			query_values = [price_list, price_list]  # First the price lists (subquery, then join)
			query_values.extend(values)  # Then the WHERE clause values
		else:
			# No price list configured - sort by default price
			query_sql = f"""
				SELECT DISTINCT {field_list}, 
					{default_price} as sort_price
				FROM `tabWebsite Item` wi
				{where_clause}
				ORDER BY sort_price {order_clause}, wi.ranking DESC
				LIMIT %s OFFSET %s
			"""
			query_values = values.copy()
		
		# Add limit and offset
		query_values.extend([self.page_length, start])
		
		items = frappe.db.sql(query_sql, query_values, as_dict=True)
		
		# Remove the sort_price field from results
		for item in items:
			if 'sort_price' in item:
				del item['sort_price']
		
		return items, count

	def query_items_with_attributes(self, attributes, start=0):
		"""Build a query to fetch Website Items based on field & attribute filters."""
		item_codes = []

		for attribute, values in attributes.items():
			if not isinstance(values, list):
				values = [values]

			# get items that have selected attribute & value
			item_code_list = frappe.db.get_all(
				"Item",
				fields=["item_code"],
				filters=[
					["published_in_website", "=", 1],
					["Item Variant Attribute", "attribute", "=", attribute],
					["Item Variant Attribute", "attribute_value", "in", values],
				],
			)
			item_codes.append({x.item_code for x in item_code_list})

		if item_codes:
			item_codes = list(set.intersection(*item_codes))
			self.filters.append(["item_code", "in", item_codes])

		items, count = self.query_items(start=start)

		return items, count

	def build_fields_filters(self, filters):
		"""Build filters for field values

		Args:
		        filters (dict): Filters
		"""
		for field, values in filters.items():
			if not values:
				continue
				
			# Handle discount filter separately - it's processed in query methods
			if field == "discount":
				# Skip here as it's handled by query_items_with_discount_filter
				continue
				
			# Handle stock filter
			if field == "in_stock" and values:
				# Will be handled separately in add_stock_filter
				continue

			# Get tags
			if field == "_user_tags":
				if isinstance(values, list):
					# Create OR filters for each tag
					tag_filters = []
					for tag in values:
						# Tags can be stored with or without leading comma
						tag_filters.append(["_user_tags", "like", f"%{tag}%"])
					
					# Add tag filters to OR filters
					self.or_filters.extend(tag_filters)
				continue

			# Special handling for item_group field
			if field == "item_group":
				# Use the specialized item_group filter builder
				# Handle both single value and list of values
				if isinstance(values, list) and len(values) > 1:
					# For multiple item groups, we need to collect all possible groups
					# and use IN clause for OR logic
					all_groups = []
					for item_group in values:
						# Get child groups for each selected group
						from webshop.webshop.doctype.override_doctype.item_group import get_child_groups_for_website
						try:
							include_groups = get_child_groups_for_website(item_group, include_self=True)
							if include_groups:
								include_groups = [x.name for x in include_groups]
								all_groups.extend(include_groups)
							else:
								# If no child groups found, at least include the group itself
								all_groups.append(item_group)
						except Exception as e:
							frappe.log_error(f"Error getting child groups for {item_group}: {str(e)}")
							# On error, at least include the group itself
							all_groups.append(item_group)
					
					# Remove duplicates and add as single IN filter
					all_groups = list(set(all_groups))

					if all_groups:
						self.filters.append(["item_group", "in", all_groups])
					else:
						# If no groups found at all, add impossible condition
						self.filters.append(["name", "=", "no_match_found"])
				else:
					# Single item group
					single_value = values[0] if isinstance(values, list) else values
					self.build_item_group_filters(single_value)
				continue

			# handle multiselect fields in filter addition
			meta = frappe.get_meta("Website Item", cached=True)
			df = meta.get_field(field)
			if df and df.fieldtype == "Table MultiSelect":
				child_doctype = df.options
				child_meta = frappe.get_meta(child_doctype, cached=True)
				fields = child_meta.get("fields")
				if fields:
					self.filters.append([child_doctype, fields[0].fieldname, "IN", values])
			elif isinstance(values, list):
				# If value is a list use `IN` query
				self.filters.append([field, "in", values])
			else:
				# `=` will be faster than `IN` for most cases
				self.filters.append([field, "=", values])

	def build_item_group_filters(self, item_group):
		"Add filters for Item group page and include Website Item Groups."
		from webshop.webshop.doctype.override_doctype.item_group import get_child_groups_for_website

		try:
			# Always include child groups when filtering
			# This ensures that selecting a parent category shows all products from child categories
			include_groups = get_child_groups_for_website(item_group, include_self=True)
			include_groups = [x.name for x in include_groups] if include_groups else []

			if include_groups:
				# Use regular filters for item_group to ensure proper count
				self.filters.append(["item_group", "in", include_groups])
			else:
				# Fallback if no children found
				self.filters.append(["item_group", "=", item_group])
		except Exception as e:
			frappe.log_error(f"Error in build_item_group_filters for {item_group}: {str(e)}")
			# On error, at least filter by the item group itself
			self.filters.append(["item_group", "=", item_group])
		
		# Note: Website Item Group filtering would require complex joins
		# and is not included in the count query for performance reasons

	def build_search_filters(self, search_term):
		"""Query search term in specified fields with fuzzy multi-word matching.

		Improvements over simple LIKE search:
		- Case-insensitive matching
		- Multi-word search (each word is searched independently)
		- Order-independent (words can appear in any order)
		- Tolerant of extra spaces

		Args:
		        search_term (str): Search candidate
		"""
		if not search_term or not search_term.strip():
			return

		search_term = search_term.strip()
		# Store for match priority ordering
		self._search_term = search_term

		# First check if search term matches an exact item_code (case-insensitive)
		exact_match = frappe.db.exists("Website Item", {"item_code": search_term})
		if exact_match:
			# If exact item_code match found, only filter by that
			self.filters.append(["item_code", "=", search_term])
			return

		# Default fields to search from
		default_fields = {"item_code", "item_name", "description", "web_long_description", "item_group"}

		# Get meta search fields
		meta = frappe.get_meta("Website Item")
		meta_fields = set(meta.get_search_fields())

		# Join the meta fields and default fields set
		search_fields = default_fields.union(meta_fields)
		if frappe.db.count("Website Item", cache=True) > 50000:
			search_fields.discard("web_long_description")

		# Split search term into individual words and normalize
		# This allows "glock 17" to match "Glock 17 Gen5" regardless of order or case
		words = [w.strip().lower() for w in search_term.split() if w.strip()]

		if not words:
			return

		# For single word search, use simple LIKE
		# Note: MariaDB/MySQL LIKE is case-insensitive by default with utf8 collations
		if len(words) == 1:
			search = "%{}%".format(words[0])
			for field in search_fields:
				self.or_filters.append([field, "like", search])
		else:
			# For multi-word search, we need ALL words to match in ANY of the fields
			# This is done by building a custom SQL condition stored in _search_sql_condition
			# The condition will be: (field1 LIKE %word1% OR field2 LIKE %word1% ...) AND (field1 LIKE %word2% OR ...)
			self._build_multiword_search_condition(words, search_fields)

	def _build_multiword_search_condition(self, words, search_fields):
		"""Build SQL condition for multi-word search where ALL words must match.

		Args:
			words (list): List of search words (already lowercased)
			search_fields (set): Fields to search in
		"""
		# Store the condition for use in query methods
		# Each word must be found in at least one field
		word_conditions = []
		self._search_values = []

		for word in words:
			field_conditions = []
			search_pattern = f"%{word}%"
			for field in search_fields:
				field_conditions.append(f"LOWER(`{field}`) LIKE %s")
				self._search_values.append(search_pattern)

			# This word must match at least one field
			word_conditions.append(f"({' OR '.join(field_conditions)})")

		# ALL words must match (AND between word conditions)
		self._search_sql_condition = " AND ".join(word_conditions)

	def _get_match_priority_sql(self, table_alias=""):
		"""Generate SQL CASE WHEN clause for search match priority.

		Priority order (lower is better):
		1. web_item_name match
		2. item_name match
		3. item_code match
		4. brand match
		5. item_group match
		6. description match
		7. web_long_description match
		8. No match (fallback)

		Args:
			table_alias (str): Table alias prefix (e.g., "wi." or "")

		Returns:
			tuple: (case_sql, values) or (None, []) if no search term
		"""
		if not self._search_term:
			return None, []

		search_pattern = f"%{self._search_term}%"
		prefix = f"{table_alias}." if table_alias else ""

		case_sql = f"""
			CASE
				WHEN {prefix}`web_item_name` LIKE %s THEN 1
				WHEN {prefix}`item_name` LIKE %s THEN 2
				WHEN {prefix}`item_code` LIKE %s THEN 3
				WHEN {prefix}`brand` LIKE %s THEN 4
				WHEN {prefix}`item_group` LIKE %s THEN 5
				WHEN {prefix}`description` LIKE %s THEN 6
				WHEN {prefix}`web_long_description` LIKE %s THEN 7
				ELSE 8
			END
		"""
		values = [search_pattern] * 7
		return case_sql, values

	def build_price_filters(self, price_condition):
		"""Build price filters to filter products by price range.
		
		Args:
			price_condition (dict): Dict containing min_price and max_price
		"""
		if not price_condition:
			return
				
		# Get store settings
		settings = frappe.get_cached_doc("Webshop Settings")
		
		# Get default price list
		default_price_list = settings.price_list

		# Instead of using a direct SQL subquery, we will store the item IDs 
		# that match our price criteria and use them as a filter
		min_price = price_condition.get("min_price")
		max_price = price_condition.get("max_price")
		
		# Build conditions for SQL query
		conditions = [
			"price_list = %s",
			"selling = 1"
		]
		
		values = [default_price_list]
		
		if min_price is not None:
			conditions.append("price_list_rate >= %s")
			values.append(float(min_price))
		
		if max_price is not None:
			conditions.append("price_list_rate <= %s")
			values.append(float(max_price))
		
		# Get item codes that match price criteria
		item_codes_query = """
			SELECT item_code 
			FROM `tabItem Price` 
			WHERE {}
		""".format(" AND ".join(conditions))
				
		item_codes = [d[0] for d in frappe.db.sql(item_codes_query, values)]
		
		if item_codes:
			# Add filter to include only items with retrieved codes
			self.filters.append(["item_code", "in", item_codes])
		else:
			# If no articles match, add an impossible condition to return nothing
			self.filters.append(["name", "=", "no_match_found"])
			
	def build_stock_filters(self, in_stock_only=True):
		"""Build filters to show only in-stock items.
		
		Args:
			in_stock_only (bool): If True, filter only in-stock items
		"""
		if not in_stock_only:
			return
			
		# Get all item codes that are in stock
		# This includes checking actual stock and also non-stock items
		stock_items_query = """
			SELECT DISTINCT wi.item_code
			FROM `tabWebsite Item` wi
			LEFT JOIN `tabItem` i ON wi.item_code = i.item_code
			LEFT JOIN `tabBin` b ON wi.item_code = b.item_code AND b.warehouse = wi.website_warehouse
			WHERE wi.published = 1
			AND (
				-- Non-stock items are always "in stock"
				i.is_stock_item = 0
				-- Stock items with actual stock
				OR (i.is_stock_item = 1 AND b.actual_qty > 0)
				-- Items on backorder
				OR wi.on_backorder = 1
			)
		"""
		
		in_stock_items = [d[0] for d in frappe.db.sql(stock_items_query)]
		
		if in_stock_items:
			self.filters.append(["item_code", "in", in_stock_items])
		else:
			# No items in stock, return empty result
			self.filters.append(["name", "=", "no_match_found"])
	

	def add_display_details(self, result, discount_list, cart_items):
		"""Add price and availability details in result."""
		for item in result:
			product_info = get_product_info_for_website(item.item_code, skip_quotation_creation=True).get(
				"product_info"
			)

			if product_info and product_info["price"]:
				# update/mutate item and discount_list objects
				self.get_price_discount_info(item, product_info["price"], discount_list)

			if self.settings.show_stock_availability:
				self.get_stock_availability(item)

			item.in_cart = item.item_code in cart_items

			item.wished = False
			if frappe.db.exists(
				"Wishlist Item", {"item_code": item.item_code, "parent": frappe.session.user}
			):
				item.wished = True

			# Add loyalty points information if enabled
			if self.settings.enable_loyalty_points and (frappe.session.user != "Guest" or self.settings.show_loyalty_points_for_guests):
				if item.get("formatted_price") and item.get("price_list_rate"):
					customer = frappe.session.user if frappe.session.user != "Guest" else None
					loyalty_info = format_loyalty_points_message(item.item_code, item.price_list_rate, 1, customer)
					if loyalty_info and loyalty_info.get("earned_text"):
						item.loyalty_points_html = loyalty_info["earned_text"]

		return result, discount_list

	def get_price_discount_info(self, item, price_object, discount_list):
		"""Modify item object and add price details."""
		from webshop.webshop.utils.utils import format_currency_value
		
		fields = ["formatted_mrp", "formatted_price", "price_list_rate"]
		for field in fields:
			item[field] = price_object.get(field)

		# Override formatted_price with our custom formatting
		if price_object.get("price_list_rate") is not None:
			item["formatted_price"] = format_currency_value(
				price_object.get("price_list_rate"),
				currency=price_object.get("currency")
			)
			
		# Also format MRP if it exists
		if price_object.get("mrp_rate") is not None:
			item["formatted_mrp"] = format_currency_value(
				price_object.get("mrp_rate"),
				currency=price_object.get("currency")
			)

		if price_object.get("discount_percent"):
			item.discount_percent = flt(price_object.discount_percent)
			discount_list.append(price_object.discount_percent)

		if item.formatted_mrp:
			item.discount = price_object.get("formatted_discount_percent") or price_object.get(
				"formatted_discount_rate"
			)

	def get_stock_availability(self, item):
		"""Modify item object and add stock details."""
		from webshop.templates.pages.wishlist import (
			get_stock_availability as get_stock_availability_from_template,
		)
		from webshop.webshop.utils.product import get_web_item_qty_in_stock

		item.in_stock = False
		item.stock_qty = 0
		warehouse = item.get("website_warehouse")
		is_stock_item = frappe.get_cached_value("Item", item.item_code, "is_stock_item")

		if item.get("on_backorder"):
			return

		if not is_stock_item:
			if warehouse:
				# product bundle case
				item.in_stock = get_non_stock_item_status(item.item_code, "website_warehouse")
			else:
				item.in_stock = True
		elif warehouse:
			# stock item and has warehouse - get full stock info
			stock_info = get_web_item_qty_in_stock(item.item_code, "website_warehouse", warehouse)
			item.in_stock = stock_info.in_stock
			item.stock_qty = stock_info.stock_qty if stock_info.stock_qty else 0

	def get_cart_items(self):
		customer = get_customer(silent=True)
		if customer:
			quotation = frappe.get_all(
				"Quotation",
				fields=["name"],
				filters={
					"party_name": customer,
					"contact_email": frappe.session.user,
					"order_type": "Shopping Cart",
					"docstatus": 0,
				},
				order_by="modified desc",
				limit_page_length=1,
			)
			if quotation:
				items = frappe.get_all(
					"Quotation Item", fields=["item_code"], filters={"parent": quotation[0].get("name")}
				)
				items = [row.item_code for row in items]
				return items

		return []
	
	def get_user_discount_cache_key(self, item_codes=None):
		"""Generate a unique cache key per user and context"""
		key_parts = [
			"discount_filter",
			frappe.session.user,
			self.settings.price_list,
			frappe.utils.today()  # Expire daily
		]
		if item_codes:
			key_parts.append(hash(tuple(sorted(item_codes))))
		return ":".join(map(str, key_parts))
	
	def query_items_with_discount_optimized(self, start=0):
		"""Optimized version with user cache"""
		# For now, disable caching to fix pagination issue
		# The cache was causing problems because it was caching paginated results
		# and then applying additional pagination on top
		
		# Execute optimized query directly
		items, count = self._execute_discount_query_optimized(start)
		
		return items, count
	
	def _get_discount_order_by(self):
		"""Get ORDER BY clause for discount queries based on sort_order"""
		if hasattr(self, 'sort_order') and self.sort_order:
			if self.sort_order == "new_arrivals":
				return "creation DESC, discount_percent DESC"
			elif self.sort_order == "rating":
				return "ranking DESC, discount_percent DESC"
			elif self.sort_order == "price_low_to_high":
				return "price_list_rate ASC, discount_percent DESC"
			elif self.sort_order == "price_high_to_low":
				return "price_list_rate DESC, discount_percent DESC"
			elif self.sort_order == "relevance":
				return "ranking DESC, discount_percent DESC"
		
		# Default: sort by ranking (relevance), then by discount percentage
		return "ranking DESC, discount_percent DESC"
	
	def _get_filtered_item_codes(self):
		"""Get item codes that match current filters (excluding discount filter)"""
		conditions = []
		values = []
		
		for filter_item in self.filters:
			if isinstance(filter_item, list) and len(filter_item) >= 3:
				field, operator, value = filter_item[0], filter_item[1], filter_item[2]
				if field == "published":
					continue  # Skip the default published filter
				
				if operator == "=":
					conditions.append(f"`{field}` = %s")
					values.append(value)
				elif operator == "in" and isinstance(value, list):
					placeholders = ", ".join(["%s"] * len(value))
					conditions.append(f"`{field}` IN ({placeholders})")
					values.extend(value)
				elif operator == "not in" and isinstance(value, list) and value:
					#//// Neoffice multi-site: items restricted to other sites
					placeholders = ", ".join(["%s"] * len(value))
					conditions.append(f"`{field}` NOT IN ({placeholders})")
					values.extend(value)
		
		if not conditions:
			return None
		
		where_clause = " WHERE " + " AND ".join(conditions)
		sql = f"SELECT name FROM `tabWebsite Item` {where_clause} LIMIT 1000"
		
		results = frappe.db.sql(sql, values)
		return [r[0] for r in results] if results else None
	
	def _execute_discount_query_optimized(self, start):
		"""Optimized query using CTE for discounts"""
		price_list = self.settings.price_list
		if not price_list:
			# Fallback to regular query if no price list
			return self.query_items_with_regular_discount_flow(start)
		
		# Build WHERE conditions for main query
		conditions = ["wi.published = 1"]
		values = {}
		
		for filter_item in self.filters:
			if isinstance(filter_item, list) and len(filter_item) >= 3:
				field, operator, value = filter_item[0], filter_item[1], filter_item[2]
				if field == "published":
					continue
				
				if operator == "=":
					param_name = f"{field}_val"
					conditions.append(f"wi.`{field}` = %({param_name})s")
					values[param_name] = value
				elif operator == "in" and isinstance(value, list):
					param_names = []
					for i, v in enumerate(value):
						param_name = f"{field}_val_{i}"
						param_names.append(f"%({param_name})s")
						values[param_name] = v
					conditions.append(f"wi.`{field}` IN ({', '.join(param_names)})")
				elif operator == "not in" and isinstance(value, list) and value:
					#//// Neoffice multi-site: items restricted to other sites
					param_names = []
					for i_ni, v in enumerate(value):
						param_name = f"ni_{field}_val_{i_ni}"
						param_names.append(f"%({param_name})s")
						values[param_name] = v
					conditions.append(f"wi.`{field}` NOT IN ({', '.join(param_names)})")
				elif operator == "is":
					if value == "not set":
						conditions.append(f"wi.`{field}` IS NULL")
		
		where_clause = " AND ".join(conditions)
		
		# Build field list
		field_list = ", ".join([f"wi.`{field}`" for field in self.fields])
		
		# Use CTE to pre-filter items with discounts
		sql = f"""
		WITH discounted_items AS (
			SELECT DISTINCT 
				wi.name,
				wi.item_code,
				wi.creation,
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
				COALESCE(ip.price_list_rate, 0) as price_list_rate,
				COALESCE(ip_mrp.price_list_rate, 0) as mrp
			FROM `tabWebsite Item` wi
			LEFT JOIN `tabItem Price` ip ON ip.item_code = wi.item_code 
				AND ip.price_list = %(price_list)s
				AND ip.selling = 1
				AND (ip.valid_from IS NULL OR ip.valid_from <= CURDATE())
				AND (ip.valid_upto IS NULL OR ip.valid_upto >= CURDATE())
			LEFT JOIN `tabItem Price` ip_mrp ON ip_mrp.item_code = wi.item_code
				AND ip_mrp.price_list != %(price_list)s
				AND ip_mrp.selling = 1
				AND ip_mrp.price_list_rate > COALESCE(ip.price_list_rate, 0)
				AND (ip_mrp.valid_from IS NULL OR ip_mrp.valid_from <= CURDATE())
				AND (ip_mrp.valid_upto IS NULL OR ip_mrp.valid_upto >= CURDATE())
			WHERE {where_clause}
			HAVING discount_percent > 0
		)
		SELECT 
			{field_list},
			di.discount_percent,
			di.price_list_rate,
			di.mrp,
			wi.creation
		FROM `tabWebsite Item` wi
		INNER JOIN discounted_items di ON di.name = wi.name
		ORDER BY {self._get_discount_order_by()}
		LIMIT %(limit)s OFFSET %(offset)s
		"""
		
		# Add values for the query
		values.update({
			'price_list': price_list,
			'limit': self.page_length,
			'offset': start
		})
		
		items = frappe.db.sql(sql, values, as_dict=True)
		
		# Get count using the same discount logic as main query
		count_sql = f"""
		WITH discounted_items AS (
			SELECT DISTINCT 
				wi.name,
				wi.item_code,
				wi.creation,
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
				) as discount_percent
			FROM `tabWebsite Item` wi
			LEFT JOIN `tabItem Price` ip ON ip.item_code = wi.item_code 
				AND ip.price_list = %(price_list)s
				AND ip.selling = 1
				AND (ip.valid_from IS NULL OR ip.valid_from <= CURDATE())
				AND (ip.valid_upto IS NULL OR ip.valid_upto >= CURDATE())
			LEFT JOIN `tabItem Price` ip_mrp ON ip_mrp.item_code = wi.item_code
				AND ip_mrp.price_list != %(price_list)s
				AND ip_mrp.selling = 1
				AND ip_mrp.price_list_rate > COALESCE(ip.price_list_rate, 0)
				AND (ip_mrp.valid_from IS NULL OR ip_mrp.valid_from <= CURDATE())
				AND (ip_mrp.valid_upto IS NULL OR ip_mrp.valid_upto >= CURDATE())
			WHERE {where_clause}
			HAVING discount_percent > 0
		)
		SELECT COUNT(DISTINCT name) FROM discounted_items
		"""
		
		count_values = {k: v for k, v in values.items() if k not in ['limit', 'offset']}
		count = frappe.db.sql(count_sql, count_values)[0][0]
		
		# Process items (add formatted prices, stock info, etc.)
		return self._process_discount_items(items), count
	
	def _process_discount_items(self, items):
		"""Process discount items to add formatted prices and other info"""
		cart_items = self.get_cart_items() if self.settings.enabled else []
		
		for item in items:
			# Format price info
			if item.get("price_list_rate"):
				from webshop.webshop.utils.utils import format_currency_value
				currency = frappe.db.get_single_value("Webshop Settings", "company") 
				if currency:
					currency = frappe.db.get_value("Company", currency, "default_currency") or "USD"
				else:
					currency = "USD"
				
				item["currency"] = currency
				item["formatted_price"] = format_currency_value(item.price_list_rate, currency=currency)
				if item.get("mrp") and item.mrp > item.price_list_rate:
					item["formatted_mrp"] = format_currency_value(item.mrp, currency=currency)
				
				if item.get("discount_percent"):
					item["discount_percent"] = flt(item.discount_percent)
					item["discount"] = f"{int(item.discount_percent)}% OFF"
			
			# Add stock info
			if self.settings.show_stock_availability:
				self.get_stock_availability(item)
			
			# Check cart and wishlist status
			item.in_cart = item.item_code in cart_items
			item.wished = frappe.db.exists("Wishlist Item", {"item_code": item.item_code, "parent": frappe.session.user})
			
			# Add loyalty points information if enabled
			if self.settings.enable_loyalty_points and (frappe.session.user != "Guest" or self.settings.show_loyalty_points_for_guests):
				if item.get("formatted_price") and item.get("price_list_rate"):
					customer = frappe.session.user if frappe.session.user != "Guest" else None
					loyalty_info = format_loyalty_points_message(item.item_code, item.price_list_rate, 1, customer)
					if loyalty_info and loyalty_info.get("earned_text"):
						item.loyalty_points_html = loyalty_info["earned_text"]
			
			# Clean up temporary fields
			for field in ["price_list_rate", "mrp"]:
				if field in item:
					del item[field]
		
		return items
	
