# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe.utils import nowdate, nowtime, flt, getdate


def get_discounted_items_query(price_list=None, company=None, customer_group=None, filters=None, limit=50, offset=0):
	"""
	Get items that have active discounts through pricing rules or price list differences.
	
	This function builds an optimized SQL query to identify discounted items without
	calculating prices for every single item.
	
	Args:
		price_list: Default selling price list
		company: Company for pricing rules
		customer_group: Customer group for pricing rules
		filters: Additional filters for Website Items
		limit: Number of results to return
		offset: Pagination offset
	
	Returns:
		List of dictionaries containing item details with discount information
	"""
	
	if not price_list:
		price_list = frappe.db.get_single_value("Webshop Settings", "price_list")
	
	if not company:
		company = frappe.db.get_single_value("Webshop Settings", "company")
		
	if not customer_group:
		customer_group = frappe.db.get_single_value("Webshop Settings", "default_customer_group")
	
	current_date = nowdate()
	current_time = nowtime()
	
	# Build WHERE conditions for Website Item filters
	where_conditions = ["wi.published = 1"]
	#//// Neoffice multi-site: scope to the current site
	from webshop.webshop.multi_site import site_sql_predicate
	_site_pred = site_sql_predicate("wi")
	if _site_pred:
		where_conditions.append(_site_pred)
	values = []
	
	if filters:
		for key, value in filters.items():
			if isinstance(value, list):
				placeholders = ", ".join(["%s"] * len(value))
				where_conditions.append(f"wi.{key} IN ({placeholders})")
				values.extend(value)
			else:
				where_conditions.append(f"wi.{key} = %s")
				values.append(value)
	
	where_clause = " AND ".join(where_conditions)
	
	# Main query that combines multiple discount sources
	query = f"""
	WITH discounted_items AS (
		-- Method 1: Items with active Pricing Rules that have discount_percentage or discount_amount
		SELECT DISTINCT 
			wi.name,
			wi.item_code,
			wi.item_name,
			wi.web_item_name,
			wi.website_image,
			wi.route,
			wi.item_group,
			wi.has_variants,
			wi.variant_of,
			wi.short_description,
			wi.ranking,
			'pricing_rule' as discount_source,
			GREATEST(
				COALESCE(pr.discount_percentage, 0),
				CASE 
					WHEN pr.discount_amount > 0 AND ip.price_list_rate > 0 
					THEN (pr.discount_amount / ip.price_list_rate * 100)
					ELSE 0
				END
			) as discount_percent
		FROM `tabWebsite Item` wi
		INNER JOIN `tabItem` i ON wi.item_code = i.item_code
		INNER JOIN `tabItem Price` ip ON i.name = ip.item_code
		INNER JOIN `tabPricing Rule` pr ON (
			(pr.apply_on = 'Item Code' AND i.name = pr.item_code)
			OR (pr.apply_on = 'Item Group' AND i.item_group = pr.item_group)
			OR (pr.apply_on = 'Brand' AND i.brand = pr.brand)
			OR pr.apply_on = 'Transaction'
		)
		LEFT JOIN `tabPricing Rule Item Code` pric ON pr.name = pric.parent
		LEFT JOIN `tabPricing Rule Item Group` prig ON pr.name = prig.parent
		LEFT JOIN `tabPricing Rule Brand` prb ON pr.name = prb.parent
		WHERE {where_clause}
			AND ip.price_list = %s
			AND ip.selling = 1
			AND pr.disable = 0
			AND pr.selling = 1
			AND (pr.company = %s OR pr.company IS NULL OR pr.company = '')
			AND (pr.customer_group = %s OR pr.customer_group IS NULL OR pr.customer_group = '')
			AND (pr.valid_from IS NULL OR pr.valid_from <= %s)
			AND (pr.valid_upto IS NULL OR pr.valid_upto >= %s)
			AND (pr.discount_percentage > 0 OR pr.discount_amount > 0)
			AND (
				(pr.apply_on = 'Item Code' AND (i.name = pr.item_code OR pric.item_code = i.name))
				OR (pr.apply_on = 'Item Group' AND (i.item_group = pr.item_group OR prig.item_group = i.item_group))
				OR (pr.apply_on = 'Brand' AND (i.brand = pr.brand OR prb.brand = i.brand))
				OR pr.apply_on = 'Transaction'
			)
		
		UNION
		
		-- Method 2: Items with price differences between MRP and selling price list
		SELECT DISTINCT
			wi.name,
			wi.item_code,
			wi.item_name,
			wi.web_item_name,
			wi.website_image,
			wi.route,
			wi.item_group,
			wi.has_variants,
			wi.variant_of,
			wi.short_description,
			wi.ranking,
			'price_list_diff' as discount_source,
			CASE 
				WHEN ip_mrp.price_list_rate > ip_sell.price_list_rate AND ip_mrp.price_list_rate > 0
				THEN ((ip_mrp.price_list_rate - ip_sell.price_list_rate) / ip_mrp.price_list_rate * 100)
				ELSE 0
			END as discount_percent
		FROM `tabWebsite Item` wi
		INNER JOIN `tabItem` i ON wi.item_code = i.item_code
		INNER JOIN `tabItem Price` ip_sell ON i.name = ip_sell.item_code
		INNER JOIN `tabItem Price` ip_mrp ON i.name = ip_mrp.item_code
		INNER JOIN `tabPrice List` pl_mrp ON ip_mrp.price_list = pl_mrp.name
		WHERE {where_clause}
			AND ip_sell.price_list = %s
			AND ip_sell.selling = 1
			AND ip_mrp.price_list != %s
			AND ip_mrp.selling = 1
			AND pl_mrp.enabled = 1
			AND pl_mrp.show_in_website = 1
			AND ip_mrp.price_list_rate > ip_sell.price_list_rate
			AND ip_mrp.price_list_rate > 0
			AND ip_sell.price_list_rate > 0
	)
	SELECT 
		name,
		item_code,
		item_name,
		web_item_name,
		website_image,
		route,
		item_group,
		has_variants,
		variant_of,
		short_description,
		ranking,
		MAX(discount_percent) as discount_percent,
		GROUP_CONCAT(DISTINCT discount_source) as discount_sources
	FROM discounted_items
	WHERE discount_percent > 0
	GROUP BY item_code
	ORDER BY discount_percent DESC, ranking DESC
	LIMIT %s OFFSET %s
	"""
	
	# Prepare values for the query
	# Note: 'values' appears twice because where_clause is used twice in the query
	query_values = []
	query_values.extend(values)  # For first WHERE clause in pricing rule section
	query_values.extend([price_list, company, customer_group, current_date, current_date])  # For pricing rule filters
	query_values.extend(values)  # For second WHERE clause in price list diff section
	query_values.extend([price_list, price_list])  # For price list comparisons
	query_values.extend([limit, offset])  # For LIMIT and OFFSET
	
	return frappe.db.sql(query, query_values, as_dict=True)


def get_discounted_items_count(price_list=None, company=None, customer_group=None, filters=None):
	"""
	Get count of items that have active discounts.
	
	This is a simplified version of the main query just for counting.
	"""
	
	if not price_list:
		price_list = frappe.db.get_single_value("Webshop Settings", "price_list")
	
	if not company:
		company = frappe.db.get_single_value("Webshop Settings", "company")
		
	if not customer_group:
		customer_group = frappe.db.get_single_value("Webshop Settings", "default_customer_group")
	
	current_date = nowdate()
	
	# Build WHERE conditions
	where_conditions = ["wi.published = 1"]
	#//// Neoffice multi-site: scope to the current site
	from webshop.webshop.multi_site import site_sql_predicate
	_site_pred = site_sql_predicate("wi")
	if _site_pred:
		where_conditions.append(_site_pred)
	values = []
	
	if filters:
		for key, value in filters.items():
			if isinstance(value, list):
				placeholders = ", ".join(["%s"] * len(value))
				where_conditions.append(f"wi.{key} IN ({placeholders})")
				values.extend(value)
			else:
				where_conditions.append(f"wi.{key} = %s")
				values.append(value)
	
	where_clause = " AND ".join(where_conditions)
	
	# Count query
	query = f"""
	SELECT COUNT(DISTINCT wi.item_code) as count
	FROM `tabWebsite Item` wi
	INNER JOIN `tabItem` i ON wi.item_code = i.item_code
	WHERE {where_clause}
		AND (
			-- Has pricing rule discount
			EXISTS (
				SELECT 1 
				FROM `tabItem Price` ip
				INNER JOIN `tabPricing Rule` pr ON (
					(pr.apply_on = 'Item Code' AND i.name = pr.item_code)
					OR (pr.apply_on = 'Item Group' AND i.item_group = pr.item_group)
					OR (pr.apply_on = 'Brand' AND i.brand = pr.brand)
					OR pr.apply_on = 'Transaction'
				)
				LEFT JOIN `tabPricing Rule Item Code` pric ON pr.name = pric.parent
				LEFT JOIN `tabPricing Rule Item Group` prig ON pr.name = prig.parent
				LEFT JOIN `tabPricing Rule Brand` prb ON pr.name = prb.parent
				WHERE ip.item_code = i.name
					AND ip.price_list = %s
					AND ip.selling = 1
					AND pr.disable = 0
					AND pr.selling = 1
					AND (pr.company = %s OR pr.company IS NULL OR pr.company = '')
					AND (pr.customer_group = %s OR pr.customer_group IS NULL OR pr.customer_group = '')
					AND (pr.valid_from IS NULL OR pr.valid_from <= %s)
					AND (pr.valid_upto IS NULL OR pr.valid_upto >= %s)
					AND (pr.discount_percentage > 0 OR pr.discount_amount > 0)
					AND (
						(pr.apply_on = 'Item Code' AND (i.name = pr.item_code OR pric.item_code = i.name))
						OR (pr.apply_on = 'Item Group' AND (i.item_group = pr.item_group OR prig.item_group = i.item_group))
						OR (pr.apply_on = 'Brand' AND (i.brand = pr.brand OR prb.brand = i.brand))
						OR pr.apply_on = 'Transaction'
					)
			)
			-- Or has price list difference
			OR EXISTS (
				SELECT 1
				FROM `tabItem Price` ip_sell
				INNER JOIN `tabItem Price` ip_mrp ON i.name = ip_mrp.item_code
				INNER JOIN `tabPrice List` pl_mrp ON ip_mrp.price_list = pl_mrp.name
				WHERE ip_sell.item_code = i.name
					AND ip_sell.price_list = %s
					AND ip_sell.selling = 1
					AND ip_mrp.price_list != %s
					AND ip_mrp.selling = 1
					AND pl_mrp.enabled = 1
					AND pl_mrp.show_in_website = 1
					AND ip_mrp.price_list_rate > ip_sell.price_list_rate
					AND ip_mrp.price_list_rate > 0
					AND ip_sell.price_list_rate > 0
			)
		)
	"""
	
	# Prepare values
	query_values = values + [
		# For pricing rule exists check
		price_list, company, customer_group, current_date, current_date,
		# For price list diff exists check
		price_list, price_list
	]
	
	result = frappe.db.sql(query, query_values, as_dict=True)
	return result[0]["count"] if result else 0


def get_items_with_pricing_rule_discount(price_list=None, company=None, customer_group=None, limit=50):
	"""
	Get items that specifically have pricing rule discounts.
	Useful for promotional sections.
	"""
	
	if not price_list:
		price_list = frappe.db.get_single_value("Webshop Settings", "price_list")
	
	if not company:
		company = frappe.db.get_single_value("Webshop Settings", "company")
		
	if not customer_group:
		customer_group = frappe.db.get_single_value("Webshop Settings", "default_customer_group")
	
	current_date = nowdate()
	
	#//// Neoffice multi-site: scope to the current site
	from webshop.webshop.multi_site import site_sql_condition
	_site_cond = site_sql_condition("wi")

	query = f"""
	SELECT DISTINCT
		wi.name,
		wi.item_code,
		wi.item_name,
		wi.web_item_name,
		wi.website_image,
		wi.route,
		pr.title as pricing_rule_title,
		pr.discount_percentage,
		pr.discount_amount,
		pr.valid_upto,
		ip.price_list_rate,
		GREATEST(
			COALESCE(pr.discount_percentage, 0),
			CASE 
				WHEN pr.discount_amount > 0 AND ip.price_list_rate > 0 
				THEN (pr.discount_amount / ip.price_list_rate * 100)
				ELSE 0
			END
		) as effective_discount_percent
	FROM `tabWebsite Item` wi
	INNER JOIN `tabItem` i ON wi.item_code = i.item_code
	INNER JOIN `tabItem Price` ip ON i.name = ip.item_code
	INNER JOIN `tabPricing Rule` pr ON (
		(pr.apply_on = 'Item Code' AND i.name = pr.item_code)
		OR (pr.apply_on = 'Item Group' AND i.item_group = pr.item_group)
		OR (pr.apply_on = 'Brand' AND i.brand = pr.brand)
		OR pr.apply_on = 'Transaction'
	)
	LEFT JOIN `tabPricing Rule Item Code` pric ON pr.name = pric.parent
	LEFT JOIN `tabPricing Rule Item Group` prig ON pr.name = prig.parent
	LEFT JOIN `tabPricing Rule Brand` prb ON pr.name = prb.parent
	WHERE wi.published = 1{_site_cond}
		AND ip.price_list = %s
		AND ip.selling = 1
		AND pr.disable = 0
		AND pr.selling = 1
		AND pr.promotional = 1  -- Only promotional pricing rules
		AND (pr.company = %s OR pr.company IS NULL OR pr.company = '')
		AND (pr.customer_group = %s OR pr.customer_group IS NULL OR pr.customer_group = '')
		AND (pr.valid_from IS NULL OR pr.valid_from <= %s)
		AND (pr.valid_upto IS NULL OR pr.valid_upto >= %s)
		AND (pr.discount_percentage > 0 OR pr.discount_amount > 0)
		AND (
			(pr.apply_on = 'Item Code' AND (i.name = pr.item_code OR pric.item_code = i.name))
			OR (pr.apply_on = 'Item Group' AND (i.item_group = pr.item_group OR prig.item_group = i.item_group))
			OR (pr.apply_on = 'Brand' AND (i.brand = pr.brand OR prb.brand = i.brand))
			OR pr.apply_on = 'Transaction'
		)
	ORDER BY effective_discount_percent DESC, wi.ranking DESC
	LIMIT %s
	"""
	
	return frappe.db.sql(query, [
		price_list, company, customer_group, current_date, current_date, limit
	], as_dict=True)