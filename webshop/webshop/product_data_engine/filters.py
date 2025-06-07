# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt
import frappe
from frappe.utils import floor


class ProductFiltersBuilder:
	def __init__(self, item_group=None):
		if not item_group:
			self.doc = frappe.get_doc("Webshop Settings")
		else:
			self.doc = frappe.get_doc("Item Group", item_group)

		self.item_group = item_group

	def get_field_filters(self):
		from webshop.webshop.doctype.override_doctype.item_group import get_child_groups_for_website

		if not self.item_group and not self.doc.enable_field_filters:
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
				else:
					filter_data.append([df, values])

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
		
		# Get the number of products for each category
		item_counts = {}
		for item_group in all_item_groups:
			count = frappe.db.count(
				"Website Item",
				filters={
					"published": 1,
					"item_group": item_group.name
				}
			)
			item_counts[item_group.name] = count
		
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
			result = []
			for group in groups:
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
		if not self.item_group and not self.doc.enable_attribute_filters:
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
			out.append(frappe._dict(name=attribute, item_attribute_values=values))

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

	def get_price_filters(self):
		"""Get price ranges for filtering products by price."""
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

		# Get min and max price from website items
		price_range = frappe.db.sql("""
			SELECT 
				MIN(price_list_rate) as min_price, 
				MAX(price_list_rate) as max_price 
			FROM `tabItem Price` 
			WHERE `tabItem Price`.item_code IN (
				SELECT item_code FROM `tabWebsite Item` 
				WHERE published = 1
			)
		""", as_dict=True)

		# If no price is found in the database, use default values
		if not price_range or not price_range[0].min_price or not price_range[0].max_price:
			min_price = 0
			max_price = 10000  # Default maximum price
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
					"label": f"{frappe.utils.fmt_money(start_price)} - {frappe.utils.fmt_money(end_price)}"
				})

		# Store the real min and max values for the slider
		real_min_price = int(price_range[0].min_price) if price_range and price_range[0].min_price else 0
		real_max_price = int(price_range[0].max_price) if price_range and price_range[0].max_price else 10000
		
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
