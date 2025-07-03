# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt
import frappe
from frappe.utils import floor
from webshop.webshop.utils.utils import format_currency_value


class ProductFiltersBuilder:
	def __init__(self, item_group=None):
		# Always use Webshop Settings for filters configuration
		# This ensures consistent filter display across all pages
		self.doc = frappe.get_doc("Webshop Settings")
		self.item_group = item_group

	def get_field_filters(self):
		from webshop.webshop.doctype.override_doctype.item_group import get_child_groups_for_website


		if not self.doc.enable_field_filters:
			return

		fields, filter_data = [], []
		filter_fields = [row.fieldname for row in self.doc.filter_fields]  # fields in settings

		# filter valid field filters i.e. those that exist in Website Item
		web_item_meta = frappe.get_meta("Website Item", cached=True)
		fields = [
			web_item_meta.get_field(field) for field in filter_fields if web_item_meta.has_field(field)
		]

		for df in fields:
			item_filters, item_or_filters = {"published": 1}, []
			link_doctype_values = self.get_filtered_link_doctype_records(df)

			if df.fieldtype == "Link":
				if self.item_group:
					include_child = frappe.db.get_value("Item Group", self.item_group, "include_descendants")
					if include_child:
						include_groups = get_child_groups_for_website(self.item_group, include_self=True)
						include_groups = [x.name for x in include_groups]
						item_or_filters.extend(
							[
								["item_group", "in", include_groups],
								["Website Item Group", "item_group", "=", self.item_group],  # consider website item groups
							]
						)
					else:
						item_or_filters.extend(
							[
								["item_group", "=", self.item_group],
								["Website Item Group", "item_group", "=", self.item_group],  # consider website item groups
							]
						)

				# exclude variants if mentioned in settings
				if frappe.db.get_single_value("Webshop Settings", "hide_variants"):
					item_filters["variant_of"] = ["is", "not set"]

				# Get link field values attached to published items
				item_values = frappe.get_all(
					"Website Item",
					fields=[df.fieldname],
					filters=item_filters,
					or_filters=item_or_filters,
					distinct="True",
					pluck=df.fieldname,
				)

				values = list(set(item_values) & link_doctype_values)  # intersection of both
				
				# Special handling for item_group to include parents
				if df.fieldname == 'item_group' and values:
					# Get all parent groups needed for hierarchy
					all_needed_groups = set(values)
					
					# Get parent information for all groups
					parent_info = frappe.db.sql("""
						SELECT name, parent_item_group 
						FROM `tabItem Group` 
						WHERE show_in_website = 1
					""", as_dict=True)
					
					parent_map = {g.name: g.parent_item_group for g in parent_info}
					
					# Add all parents up to the root
					for group in list(values):
						current = group
						while current in parent_map:
							parent = parent_map[current]
							if parent and parent != "All Item Groups":
								all_needed_groups.add(parent)
							current = parent
					
					# Update values to include all needed groups
					values = list(all_needed_groups)
			else:
				# table multiselect
				values = list(link_doctype_values)

			# Remove None
			if None in values:
				values.remove(None)

			if values:
				# If it's a category filter, get the hierarchical structure
				if df.fieldname == 'item_group':
					hierarchical_item_groups = self.get_hierarchical_item_groups(values)
					filter_data.append([df, hierarchical_item_groups])
				# If it's a brand filter, get brands with counts
				elif df.fieldname == 'brand':
					brands_with_counts = self.get_brands_with_counts(values)
					filter_data.append([df, brands_with_counts])
				else:
					# Sort values alphabetically
					sorted_values = sorted(values, key=lambda x: x.lower() if isinstance(x, str) else str(x))
					filter_data.append([df, sorted_values])

		return filter_data
		
	def get_hierarchical_item_groups(self, item_group_values):
		"""Get categories with their hierarchical structure parent-child"""
		# Get all categories with their parent/child information
		all_item_groups = frappe.get_all(
			"Item Group",
			fields=["name", "parent_item_group", "lft", "rgt"],
			filters={
				"show_in_website": 1,
				"name": ["in", item_group_values]
			},
			order_by="lft asc"
		)
		
		
		
		# Get the number of products for each category (including children)
		item_counts = {}
		
		# First, get direct counts
		direct_counts = frappe.db.sql("""
			SELECT item_group, COUNT(*) as count
			FROM `tabWebsite Item`
			WHERE published = 1 AND item_group IN %(groups)s
			GROUP BY item_group
		""", {"groups": [g.name for g in all_item_groups]}, as_dict=True)
		
		direct_count_map = {d.item_group: d.count for d in direct_counts}
		
		# Calculate total counts including children
		for item_group in all_item_groups:
			# Get all descendant groups
			descendants = frappe.db.sql("""
				SELECT name FROM `tabItem Group`
				WHERE lft > %s AND rgt < %s
				AND show_in_website = 1
			""", (item_group.lft, item_group.rgt), pluck="name")
			
			# Count products in this group and all descendants
			all_groups = [item_group.name] + list(descendants)
			total_count = frappe.db.sql("""
				SELECT COUNT(*) as count
				FROM `tabWebsite Item`
				WHERE published = 1 AND item_group IN %(groups)s
			""", {"groups": all_groups}, as_dict=True)[0].count
			
			item_counts[item_group.name] = total_count
		
		# Build the hierarchical structure
		root_groups = []
		group_children = {}
		
		
		
		# Identify root groups and prepare child structure
		for group in all_item_groups:
			if not group.parent_item_group or group.parent_item_group not in [g.name for g in all_item_groups]:
				root_groups.append(group)
			else:
				if group.parent_item_group not in group_children:
					group_children[group.parent_item_group] = []
				group_children[group.parent_item_group].append(group)
		
		# Recursive function to build the tree
		def build_tree(groups):
			# Sort groups alphabetically before processing
			sorted_groups = sorted(groups, key=lambda x: x.name.lower())
			result = []
			for group in sorted_groups:
				group_data = {
					"name": group.name,
					"count": item_counts.get(group.name, 0),
					"children": []
				}
				
				# Add children if any
				if group.name in group_children:
					group_data["children"] = build_tree(group_children[group.name])
				
				result.append(group_data)
			return result
		
		# Build the tree from root groups
		hierarchical_groups = build_tree(root_groups)
		
		
		return hierarchical_groups

	def get_brands_with_counts(self, brand_values):
		"""Get brands with their product counts"""
		brands_with_counts = []
		
		# Get the number of products for each brand
		for brand in brand_values:
			count = frappe.db.count(
				"Website Item",
				filters={
					"published": 1,
					"brand": brand
				}
			)
			
			# Create brand data with count
			brand_data = {
				"name": brand,
				"count": count
			}
			brands_with_counts.append(brand_data)
		
		# Sort brands alphabetically
		brands_with_counts.sort(key=lambda x: x["name"].lower() if x["name"] else "")
		
		return brands_with_counts

	def get_filtered_link_doctype_records(self, field):
		"""
		Get valid link doctype records depending on filters.
		Apply enable/disable/show_in_website filter.
		Returns:
		        set: A set containing valid record names
		"""
		link_doctype = field.get_link_doctype()
		meta = frappe.get_meta(link_doctype, cached=True) if link_doctype else None
		if meta:
			filters = self.get_link_doctype_filters(meta)
			link_doctype_values = set(d.name for d in frappe.get_all(link_doctype, filters))

		return link_doctype_values if meta else set()

	def get_link_doctype_filters(self, meta):
		"Filters for Link Doctype eg. 'show_in_website'."
		filters = {}
		if not meta:
			return filters

		if meta.has_field("enabled"):
			filters["enabled"] = 1
		if meta.has_field("disabled"):
			filters["disabled"] = 0
		if meta.has_field("show_in_website"):
			filters["show_in_website"] = 1

		return filters

	def get_attribute_filters(self):
		if not self.doc.enable_attribute_filters:
			return

		attributes = [row.attribute for row in self.doc.filter_attributes]

		if not attributes:
			return []

		result = frappe.get_all(
			"Item Variant Attribute",
			filters={"attribute": ["in", attributes], "attribute_value": ["is", "set"]},
			fields=["attribute", "attribute_value"],
			distinct=True,
		)

		attribute_value_map = {}
		for d in result:
			attribute_value_map.setdefault(d.attribute, []).append(d.attribute_value)

		out = []
		for attribute in attributes:
			if attribute not in attribute_value_map:
				continue

			values = attribute_value_map[attribute]
			# Sort attribute values alphabetically
			sorted_values = sorted(values, key=lambda x: x.lower() if isinstance(x, str) else str(x))
			out.append(frappe._dict(name=attribute, item_attribute_values=sorted_values))

		return out

	def get_discount_filters(self, discounts):
		discount_filters = []

		# [25.89, 60.5] min max
		min_discount, max_discount = discounts[0], discounts[1]
		# [25, 60] rounded min max
		min_range_absolute, max_range_absolute = floor(min_discount), floor(max_discount)

		min_range = int(min_discount - (min_range_absolute % 10))  # 20
		max_range = int(max_discount - (max_range_absolute % 10))  # 60

		min_range = (
			(min_range + 10) if min_range != min_range_absolute else min_range
		)  # 30 (upper limit of 25.89 in range of 10)
		max_range = (max_range + 10) if max_range != max_range_absolute else max_range  # 60

		for discount in range(min_range, (max_range + 1), 10):
			label = f"{discount}% and below"
			discount_filters.append([discount, label])

		return discount_filters

	def get_price_filters(self, field_filters=None, attribute_filters=None, filtered_items=None):
		"""Get price ranges for filtering products by price.
		
		Args:
			field_filters (dict): Field filters to apply (brand, etc.)
			attribute_filters (dict): Attribute filters to apply
			filtered_items (list): List of item codes currently displayed after all filters
		"""
		enable_price_filter = frappe.db.get_single_value("Webshop Settings", "enable_price_filter")
		
		if not self.item_group and not enable_price_filter:
			return None

		item_filters, item_or_filters = {"published": 1}, []

		# Apply item group filter if specified
		if self.item_group:
			from webshop.webshop.doctype.override_doctype.item_group import get_child_groups_for_website
			include_child = frappe.db.get_value("Item Group", self.item_group, "include_descendants")
			if include_child:
				include_groups = get_child_groups_for_website(self.item_group, include_self=True)
				include_groups = [x.name for x in include_groups]
				item_or_filters.extend(
					[
						["item_group", "in", include_groups],
						["Website Item Group", "item_group", "=", self.item_group],  # consider website item groups
					]
				)
			else:
				item_or_filters.extend(
					[
						["item_group", "=", self.item_group],
						["Website Item Group", "item_group", "=", self.item_group],  # consider website item groups
					]
				)

		# Exclude variants if mentioned in settings
		if frappe.db.get_single_value("Webshop Settings", "hide_variants"):
			item_filters["variant_of"] = ["is", "not set"]

		# Apply additional field filters if provided
		additional_conditions = []
		if field_filters:
			# Handle brand filter
			if field_filters.get("brand"):
				brands = field_filters["brand"]
				if isinstance(brands, list) and brands:
					placeholders = ", ".join(["%s"] * len(brands))
					additional_conditions.append(f"wi.brand IN ({placeholders})")
		
		# Apply attribute filters if provided
		item_codes_with_attributes = None
		if attribute_filters:
			# Get items that match ALL attribute filters
			item_codes_sets = []
			for attribute, values in attribute_filters.items():
				if not isinstance(values, list):
					values = [values]
				
				# Get items with this attribute and value
				item_codes = frappe.db.sql_list("""
					SELECT DISTINCT i.item_code
					FROM `tabItem` i
					INNER JOIN `tabItem Variant Attribute` iva ON i.name = iva.parent
					WHERE iva.attribute = %s
					AND iva.attribute_value IN ({})
					AND i.published_in_website = 1
				""".format(", ".join(["%s"] * len(values))), [attribute] + values)
				
				if item_codes:
					item_codes_sets.append(set(item_codes))
			
			# Get intersection of all attribute filters
			if item_codes_sets:
				item_codes_with_attributes = list(set.intersection(*item_codes_sets))

		# Build SQL query to get min and max price
		# Check if we have an item group either from self or from field_filters
		item_group_to_use = self.item_group
		if not item_group_to_use and field_filters and field_filters.get("item_group"):
			# Get the first item group from the filter
			item_group_filter = field_filters.get("item_group")
			if isinstance(item_group_filter, list) and item_group_filter:
				item_group_to_use = item_group_filter[0]
			elif isinstance(item_group_filter, str):
				item_group_to_use = item_group_filter
		
		if item_group_to_use:
			# First, get child groups for this item group
			from webshop.webshop.doctype.override_doctype.item_group import get_child_groups_for_website
			
			include_groups = get_child_groups_for_website(item_group_to_use, include_self=True)
			item_groups = [x.name for x in include_groups] if include_groups else [item_group_to_use]
			
			# Get default price list from settings
			default_price_list = frappe.db.get_single_value("Webshop Settings", "price_list")
			
			# Build the SQL query with all filters
			sql_conditions = ["wi.published = 1", "wi.item_group IN %(groups)s", "ip.selling = 1"]
			sql_params = {"groups": item_groups}
			
			if default_price_list:
				sql_conditions.append("ip.price_list = %(price_list)s")
				sql_params["price_list"] = default_price_list
			
			# Add brand filter if present
			if field_filters and field_filters.get("brand"):
				brands = field_filters["brand"]
				if isinstance(brands, list) and brands:
					sql_conditions.append("wi.brand IN %(brands)s")
					sql_params["brands"] = brands
			
			# Add stock filter if present
			if field_filters and field_filters.get("in_stock") == ["1"]:
				sql_conditions.append("wi.on_backorder = 0")
			
			# First, get all item codes that match the current filters (without pagination)
			# This ensures we get prices for ALL filtered products, not just the current page
			item_sql_conditions = ["wi.published = 1", "wi.item_group IN %(groups)s"]
			item_sql_params = {"groups": item_groups}
			
			# Add brand filter
			if field_filters and field_filters.get("brand"):
				brands = field_filters["brand"]
				if isinstance(brands, list) and brands:
					item_sql_conditions.append("wi.brand IN %(brands)s")
					item_sql_params["brands"] = brands
			
			# Add stock filter
			if field_filters and field_filters.get("in_stock") == ["1"]:
				item_sql_conditions.append("wi.on_backorder = 0")
			
			# Add discount filter
			if field_filters and field_filters.get("discount") == ["100"]:
				# Filter only items with active pricing rules that provide discounts
				item_sql_conditions.append("""EXISTS (
					SELECT 1 
					FROM `tabPricing Rule` pr
					LEFT JOIN `tabPricing Rule Item Code` pric ON pr.name = pric.parent
					LEFT JOIN `tabPricing Rule Item Group` prig ON pr.name = prig.parent  
					LEFT JOIN `tabPricing Rule Brand` prb ON pr.name = prb.parent
					WHERE pr.disable = 0
					AND pr.selling = 1
					AND (pr.valid_from IS NULL OR pr.valid_from <= CURDATE())
					AND (pr.valid_upto IS NULL OR pr.valid_upto >= CURDATE())
					AND (
						(pr.apply_on = 'Item Code' AND pric.item_code = wi.item_code)
						OR (pr.apply_on = 'Item Group' AND prig.item_group = wi.item_group)
						OR (pr.apply_on = 'Brand' AND prb.brand = wi.brand)
					)
					AND (pr.discount_percentage > 0 OR pr.discount_amount > 0)
				)""")
			
			# Add attribute filter
			if item_codes_with_attributes is not None:
				if item_codes_with_attributes:
					item_sql_conditions.append("wi.item_code IN %(attr_items)s")
					item_sql_params["attr_items"] = item_codes_with_attributes
				else:
					# No items match the attribute filters
					return [{
						"min_value": 0,
						"max_value": 0
					}]
			
			# Get all item codes matching the filters
			item_where_clause = " AND ".join(item_sql_conditions)
			filtered_item_codes = frappe.db.sql_list(f"""
				SELECT DISTINCT wi.item_code
				FROM `tabWebsite Item` wi
				WHERE {item_where_clause}
			""", item_sql_params)
			
			if not filtered_item_codes:
				return [{
					"min_value": 0,
					"max_value": 0
				}]
			
			# Now get prices for these filtered items
			# Try with default price list first
			if default_price_list:
				price_range = frappe.db.sql("""
					SELECT 
						MIN(ip.price_list_rate) as min_price, 
						MAX(ip.price_list_rate) as max_price 
					FROM `tabItem Price` ip
					WHERE ip.item_code IN %(items)s
					AND ip.selling = 1
					AND ip.price_list = %(price_list)s
					AND ip.price_list_rate > 0
				""", {"items": filtered_item_codes, "price_list": default_price_list}, as_dict=True)
			else:
				price_range = None
			
			# If no prices found with price list, try without
			if not price_range or not price_range[0].min_price:
				price_range = frappe.db.sql("""
					SELECT 
						MIN(ip.price_list_rate) as min_price, 
						MAX(ip.price_list_rate) as max_price 
					FROM `tabItem Price` ip
					WHERE ip.item_code IN %(items)s
					AND ip.selling = 1
					AND ip.price_list_rate > 0
				""", {"items": filtered_item_codes}, as_dict=True)

		else:
			# No item group filter, get all prices
			default_price_list = frappe.db.get_single_value("Webshop Settings", "price_list")
			
			# Get all item codes that match the current filters (without pagination)
			item_sql_conditions = ["wi.published = 1"]
			item_sql_params = {}
			
			# Add brand filter
			if field_filters and field_filters.get("brand"):
				brands = field_filters["brand"]
				if isinstance(brands, list) and brands:
					item_sql_conditions.append("wi.brand IN %(brands)s")
					item_sql_params["brands"] = brands
			
			# Add stock filter
			if field_filters and field_filters.get("in_stock") == ["1"]:
				item_sql_conditions.append("wi.on_backorder = 0")
			
			# Add discount filter
			if field_filters and field_filters.get("discount") == ["100"]:
				# Filter only items with active pricing rules that provide discounts
				item_sql_conditions.append("""EXISTS (
					SELECT 1 
					FROM `tabPricing Rule` pr
					LEFT JOIN `tabPricing Rule Item Code` pric ON pr.name = pric.parent
					LEFT JOIN `tabPricing Rule Item Group` prig ON pr.name = prig.parent  
					LEFT JOIN `tabPricing Rule Brand` prb ON pr.name = prb.parent
					WHERE pr.disable = 0
					AND pr.selling = 1
					AND (pr.valid_from IS NULL OR pr.valid_from <= CURDATE())
					AND (pr.valid_upto IS NULL OR pr.valid_upto >= CURDATE())
					AND (
						(pr.apply_on = 'Item Code' AND pric.item_code = wi.item_code)
						OR (pr.apply_on = 'Item Group' AND prig.item_group = wi.item_group)
						OR (pr.apply_on = 'Brand' AND prb.brand = wi.brand)
					)
					AND (pr.discount_percentage > 0 OR pr.discount_amount > 0)
				)""")
			
			# Add attribute filter
			if item_codes_with_attributes is not None:
				if item_codes_with_attributes:
					item_sql_conditions.append("wi.item_code IN %(attr_items)s")
					item_sql_params["attr_items"] = item_codes_with_attributes
				else:
					# No items match the attribute filters
					return [{
						"min_value": 0,
						"max_value": 0
					}]
			
			# Get all item codes matching the filters
			item_where_clause = " AND ".join(item_sql_conditions)
			filtered_item_codes = frappe.db.sql_list(f"""
				SELECT DISTINCT wi.item_code
				FROM `tabWebsite Item` wi
				WHERE {item_where_clause}
			""", item_sql_params)

			if not filtered_item_codes:
				return [{
					"min_value": 0,
					"max_value": 0
				}]
			
			# Now get prices for these filtered items
			# Try with default price list first
			if default_price_list:
				price_range = frappe.db.sql("""
					SELECT 
						MIN(ip.price_list_rate) as min_price, 
						MAX(ip.price_list_rate) as max_price 
					FROM `tabItem Price` ip
					WHERE ip.item_code IN %(items)s
					AND ip.selling = 1
					AND ip.price_list = %(price_list)s
					AND ip.price_list_rate > 0
				""", {"items": filtered_item_codes, "price_list": default_price_list}, as_dict=True)
			else:
				price_range = None
			
			# If no prices found with price list, try without
			if not price_range or not price_range[0].min_price:
				price_range = frappe.db.sql("""
					SELECT 
						MIN(ip.price_list_rate) as min_price, 
						MAX(ip.price_list_rate) as max_price 
					FROM `tabItem Price` ip
					WHERE ip.item_code IN %(items)s
					AND ip.selling = 1
					AND ip.price_list_rate > 0
				""", {"items": filtered_item_codes}, as_dict=True)

		# If no price is found in the database, get prices without filters as fallback
		if not price_range or not price_range[0].min_price or not price_range[0].max_price:
			# Get prices for all products in this category without current filters
			fallback_conditions = ["wi.published = 1"]
			fallback_params = {}
			
			# Keep only item group filter for fallback
			if item_group_to_use:
				fallback_conditions.append("wi.item_group IN %(groups)s")
				fallback_params["groups"] = item_groups if 'item_groups' in locals() else [item_group_to_use]
			
			fallback_where_clause = " AND ".join(fallback_conditions)
			fallback_item_codes = frappe.db.sql_list(f"""
				SELECT DISTINCT wi.item_code
				FROM `tabWebsite Item` wi
				WHERE {fallback_where_clause}
			""", fallback_params)
			
			if fallback_item_codes:
				# Get prices for fallback items
				if default_price_list:
					price_range = frappe.db.sql("""
						SELECT 
							MIN(ip.price_list_rate) as min_price, 
							MAX(ip.price_list_rate) as max_price 
						FROM `tabItem Price` ip
						WHERE ip.item_code IN %(items)s
						AND ip.selling = 1
						AND ip.price_list = %(price_list)s
						AND ip.price_list_rate > 0
					""", {"items": fallback_item_codes, "price_list": default_price_list}, as_dict=True)
				else:
					price_range = frappe.db.sql("""
						SELECT 
							MIN(ip.price_list_rate) as min_price, 
							MAX(ip.price_list_rate) as max_price 
						FROM `tabItem Price` ip
						WHERE ip.item_code IN %(items)s
						AND ip.selling = 1
						AND ip.price_list_rate > 0
					""", {"items": fallback_item_codes}, as_dict=True)
			
			# No prices found for this category/filter combination
			# Return default range instead of 0-0
			return [{
				"min_value": 0,
				"max_value": 10000
			}]
		else:
			# Round prices to create sensible ranges
			min_price = int(price_range[0].min_price)
			max_price = int(price_range[0].max_price)

		# Create price ranges
		price_ranges = []
		
		# Determine step size based on price range
		if max_price - min_price > 1000:
			step = 500
		else:
			step = 100

		# Round min_price down to nearest step
		min_price = (min_price // step) * step
		
		# Round max_price up to nearest step
		max_price = ((max_price // step) + 1) * step

		# Create price ranges
		for start_price in range(min_price, max_price, step):
			end_price = start_price + step
			if end_price <= max_price:
				price_ranges.append({
					"start": start_price,
					"end": end_price,
					"label": f"{format_currency_value(start_price)} - {format_currency_value(end_price)}"
				})

		# Store the real min and max values for the slider
		# Use ceil for max to ensure we can select the highest priced item
		real_min_price = int(price_range[0].min_price) if price_range and price_range[0].min_price else 0
		real_max_price = int(frappe.utils.ceil(price_range[0].max_price)) if price_range and price_range[0].max_price else 10000
		
		# Add the real min and max values to the start of the list
		price_ranges.insert(0, {
			"min_value": real_min_price,
			"max_value": real_max_price
		})

		return price_ranges

	def get_tag_filters(self):
		"""Get all tags used in Website Items for filtering."""
		if not self.item_group and not frappe.db.get_single_value("Webshop Settings", "enable_tag_filters"):
			return []

		item_filters, item_or_filters = {"published": 1}, []

		# Apply item group filter if specified
		if self.item_group:
			from webshop.webshop.doctype.override_doctype.item_group import get_child_groups_for_website
			include_child = frappe.db.get_value("Item Group", self.item_group, "include_descendants")
			if include_child:
				include_groups = get_child_groups_for_website(self.item_group, include_self=True)
				include_groups = [x.name for x in include_groups]
				item_or_filters.extend(
					[
						["item_group", "in", include_groups],
						["Website Item Group", "item_group", "=", self.item_group],  # consider website item groups
					]
				)
			else:
				item_or_filters.extend(
					[
						["item_group", "=", self.item_group],
						["Website Item Group", "item_group", "=", self.item_group],  # consider website item groups
					]
				)

		# Exclude variants if mentioned in settings
		if frappe.db.get_single_value("Webshop Settings", "hide_variants"):
			item_filters["variant_of"] = ["is", "not set"]

		# Get all website items with tags
		website_items = frappe.get_all(
			"Website Item",
			fields=["name", "_user_tags"],
			filters=item_filters,
			or_filters=item_or_filters
		)

		# Process tags
		all_tags = []
		for item in website_items:
			if item._user_tags:
				# Process tags (remove leading comma if present)
				tags = item._user_tags
				if tags.startswith(","):
					tags = tags[1:]
				
				# Split tags and add to list
				item_tags = [tag.strip() for tag in tags.split(",") if tag.strip()]
				all_tags.extend(item_tags)

		# Count occurrences of each tag
		tag_counts = {}
		for tag in all_tags:
			tag_counts[tag] = tag_counts.get(tag, 0) + 1

		# Sort tags by count (most used first)
		sorted_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)

		# Return list of tags
		return [tag for tag, count in sorted_tags]


def diagnose_item_group_filters():
	"""Diagnostic function to check item group filter issues"""
	import json
	
	# Get webshop settings
	settings = frappe.get_doc("Webshop Settings")
	
	# Basic info
	result = {
		"enable_field_filters": settings.enable_field_filters,
		"filter_fields": [row.fieldname for row in settings.filter_fields] if settings.filter_fields else [],
		"item_groups_analysis": {}
	}
	
	if not settings.enable_field_filters:
		result["error"] = "Field filters are disabled in Webshop Settings"
		return json.dumps(result, indent=2)
	
	if "item_group" not in result["filter_fields"]:
		result["error"] = "item_group is not in configured filter fields"
		return json.dumps(result, indent=2)
	
	# Get all item groups with show_in_website
	all_with_show_in_website = frappe.get_all(
		"Item Group",
		fields=["name", "parent_item_group"],
		filters={"show_in_website": 1},
		order_by="name"
	)
	
	# Get item groups that have published products
	item_groups_with_products = frappe.db.sql("""
		SELECT DISTINCT item_group, COUNT(*) as product_count
		FROM `tabWebsite Item`
		WHERE published = 1 AND item_group IS NOT NULL
		GROUP BY item_group
		ORDER BY item_group
	""", as_dict=True)
	
	# Create a dict for easy lookup
	product_count_by_group = {row.item_group: row.product_count for row in item_groups_with_products}
	
	# Analyze
	groups_with_products = set(product_count_by_group.keys())
	all_groups_names = set([g.name for g in all_with_show_in_website])
	
	# Groups that will be displayed (intersection)
	displayed_groups = groups_with_products & all_groups_names
	
	# Missing groups (have show_in_website but no products)
	missing_groups = all_groups_names - groups_with_products
	
	# Groups with products but not show_in_website
	groups_without_show = groups_with_products - all_groups_names
	
	result["item_groups_analysis"] = {
		"total_with_show_in_website": len(all_groups_names),
		"total_with_products": len(groups_with_products),
		"total_displayed": len(displayed_groups),
		"missing_groups_count": len(missing_groups),
		"missing_groups_sample": list(missing_groups)[:20],  # First 20
		"groups_without_show_in_website": list(groups_without_show)[:20],
		"hierarchy_issues": []
	}
	
	# Check for hierarchy issues
	displayed_list = list(displayed_groups)
	parent_map = {g.name: g.parent_item_group for g in all_with_show_in_website}
	
	missing_parents = set()
	for group in displayed_list:
		parent = parent_map.get(group)
		if parent and parent not in displayed_list and parent != "All Item Groups":
			missing_parents.add(parent)
	
	if missing_parents:
		result["item_groups_analysis"]["hierarchy_issues"] = list(missing_parents)[:20]
		result["item_groups_analysis"]["hierarchy_issue_count"] = len(missing_parents)
	
	# Get sample of displayed groups with their product counts
	sample_displayed = {}
	for group in list(displayed_groups)[:20]:
		sample_displayed[group] = product_count_by_group.get(group, 0)
	result["item_groups_analysis"]["displayed_groups_sample"] = sample_displayed
	
	return json.dumps(result, indent=2)