# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt
import frappe
from frappe import _
# //// Neoffice — cint import: needed by gift_cards_hidden() below, the switch that
# //// keeps gift cards out of the catalogue and its facets
# //// (5100ecbe6d "fix(boutique): la case « cartes cadeaux » retire enfin la carte de la vitrine").
from frappe.utils import cint, floor
# //// Neoffice — the currency formatter honours the shop's "hide currency symbol"
# //// setting (0134ef756e, 2025-07-03).
from webshop.webshop.utils.utils import format_currency_value


# //// Neoffice — gift cards leave the facets too when the shop does not sell one.
# //// Filtering only the listing left a "Carte cadeau" checkbox, badge "1", that
# //// selected nothing — worse than showing the product, because the reader thinks
# //// the shop has one and the filter is broken. Same switch as the catalogue,
# //// `enable_gift_cards` on Webshop Settings.
# //// (2026-09-24) its SQL twin, gift_card_sql_condition, went with the facets' hand-written
# //// counts: they read ProductFiltersBuilder.scope() now.
def gift_cards_hidden():
	"""True when the shop's gift cards must not appear anywhere on the storefront."""
	return not cint(frappe.db.get_single_value("Webshop Settings", "enable_gift_cards"))


# //// Neoffice — the rule that decides whether a Select facet is worth drawing, pulled
# //// out of get_field_filters and named so that /shop-by-category can obey the SAME one.
# //// That page had no rule at all and offered a "Condition" tab holding the single card
# //// "New" on a shop that has never sold anything else (a reseller site, 2026-09-10) — while
# //// the sidebar, right next to it, showed no Condition facet.
def select_facet_is_useful(fieldname, values):
	"""Does this Select field offer the visitor a choice?

	Every item carries a condition, so a shop selling only new goods would get a
	one-value facet reading "New": a tick box that selects the whole catalogue.
	"""
	if fieldname == "item_condition":
		return bool([v for v in values if v and v != "New"])
	return bool([v for v in values if v])


class ProductFiltersBuilder:
	def __init__(self, item_group=None, locked_field_filters=None):  # //// Neoffice — locks, see below
		# //// Neoffice — upstream reads the filter configuration from the Item Group when there
		# //// is one, and from Webshop Settings otherwise, so two categories offered different
		# //// facets on the same shop. The shop's own configuration wins everywhere
		# //// (8ba1a7ab46, 2025-06-08).
		# Always use Webshop Settings for filters configuration
		# This ensures consistent filter display across all pages
		self.doc = frappe.get_doc("Webshop Settings")
		self.item_group = item_group
		# //// Neoffice — the listing's locked facets (a brand's page, /occasions: {fieldname:
		# //// [values]}, listing_context.build_listing_context): every facet counts inside them,
		# //// and a locked one is not offered at all — the visitor cannot untick it (2026-09-24).
		self.locked_field_filters = locked_field_filters or {}
		self._scope = None

	# //// Neoffice — added (2026-09-24, neoffice-maintenance#737): the Website Items the listing next to the facets shows.
	# //// Each facet built its own copy of that rule and none of them held: on a brand's page the
	# //// categories counted the whole catalogue ("Location de matériel 251" beside a grid of two
	# //// products), the brand facet counted the variants the grid hides (14 for a brand showing
	# //// 2), and a category page offered brands from its own level only while its grid lists its
	# //// sub-categories too. A tick on such a facet led to an empty grid, or to fewer products
	# //// than it promised.
	def scope(self):
		"""(filters, or_filters) of what the listing shows, as fresh copies: the catalogue's scope
		and the locked facets (catalogue_scope.visible_item_filters), and on a category page the
		category as its grid reads it (ProductQuery.item_group_or_filters)."""
		if self._scope is None:
			from webshop.webshop.product_data_engine.catalogue_scope import visible_item_filters
			from webshop.webshop.product_data_engine.query import ProductQuery

			self._scope = (
				visible_item_filters(self.locked_field_filters),
				ProductQuery.item_group_or_filters(self.item_group) if self.item_group else [],
			)
		filters, or_filters = self._scope
		return dict(filters), [list(condition) for condition in or_filters]

	def get_field_filters(self):
# //// Neoffice — see above.

		if not self.doc.enable_field_filters:
			return

		fields, filter_data = [], []
		filter_fields = [row.fieldname for row in self.doc.filter_fields]  # fields in settings
		# //// Neoffice — a locked facet is not offered (see __init__); build_listing_context used to
		# //// build it, count it, then drop it
		filter_fields = [field for field in filter_fields if field not in self.locked_field_filters]

		# filter valid field filters i.e. those that exist in Website Item
		web_item_meta = frappe.get_meta("Website Item", cached=True)
		fields = [
			web_item_meta.get_field(field) for field in filter_fields if web_item_meta.has_field(field)
		]

		for df in fields:
			# //// Neoffice — every facet reads the listing's own scope (scope() above): published,
			# //// not sold, this site's, hidden gift cards and hidden variants out, the locked
			# //// facets, and on a category page the category WITH its sub-categories — the grid
			# //// always descends (query.py item_group_or_filters), upstream's facets only when the
			# //// group ticks `include_descendants`, and its Select facets ignored the category.
			item_filters, item_or_filters = self.scope()
			# //// Neoffice — second-hand: a Select field has no linked doctype;
			# //// its facet is the set of values the published items carry.
			link_doctype_values = (
				self.get_filtered_link_doctype_records(df) if df.fieldtype == "Link" else set()
			)

			if df.fieldtype == "Select":
				# //// Neoffice — the hidden variants and the category are in the scope above
				values = [
					v
					for v in frappe.get_all(
						"Website Item",
						fields=[df.fieldname],
						filters=item_filters,
						or_filters=item_or_filters,  # //// Neoffice — the category (scope())
						distinct="True",
						pluck=df.fieldname,
					)
					if v
				]
			elif df.fieldtype == "Link":
				# //// Neoffice — the category and the hidden variants are in the scope above

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
				# //// Neoffice — added: the price facet (min/max of the current result set) and the
				# //// discount facet, neither of which upstream has (6fea19b1fe, 2025-06-17;
				# //// 8ba1a7ab46, 2025-06-08).
				
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

			# //// Neoffice — second-hand: show a Select facet once there is a choice to
			# //// make. The rule lives in select_facet_is_useful() above, because
			# //// /shop-by-category has to draw its tabs by the same one.
			if df.fieldtype == "Select" and not select_facet_is_useful(df.fieldname, values):
				continue

			if values:
				# If it's a category filter, get the hierarchical structure
				if df.fieldname == 'item_group':
					hierarchical_item_groups = self.get_hierarchical_item_groups(values)
					filter_data.append([df, hierarchical_item_groups])
				# If it's a brand filter, get brands with counts
				elif df.fieldname == 'brand':
					brands_with_counts = self.get_brands_with_counts(values)
					filter_data.append([df, brands_with_counts])
				elif df.fieldtype == "Select":
					# //// Neoffice — a Select keeps the order its options declare
					options = (df.options or "").split("\n")
					sorted_values = sorted(values, key=lambda v: options.index(v) if v in options else len(options))
					filter_data.append([df, sorted_values])
				else:
					# Sort values alphabetically
					sorted_values = sorted(values, key=lambda x: x.lower() if isinstance(x, str) else str(x))
					filter_data.append([df, sorted_values])

		return filter_data
		
	def get_hierarchical_item_groups(self, item_group_values):
		"""Get categories with their hierarchical structure parent-child"""
		# //// Neoffice — the site and gift-card conditions it built here are in scope() now
		# Get all categories with their parent/child information
		all_item_groups = frappe.get_all(
			"Item Group",
			fields=["name", "parent_item_group", "lft", "rgt", "weightage"],
			filters={
				"show_in_website": 1,
				"name": ["in", item_group_values]
			},
			order_by="lft asc"
		)

		# //// Neoffice — each group counts what a tick on it lists (query.build_fields_filters:
		# //// the group and its sub-categories shown on the website), inside the listing's scope
		# //// (scope() above: gift cards, sold units, hidden variants, other sites' items, the
		# //// locked facets and the category page all out). Two queries, where it ran two per
		# //// group over the whole catalogue whatever the page (2026-09-24).
		item_counts = self.item_group_counts(all_item_groups)

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
			# Sort groups by weightage descending (higher = first), then alphabetically
			sorted_groups = sorted(groups, key=lambda x: (-(x.weightage or 0), x.name.lower()))
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

	# //// Neoffice — added (2026-09-24), see get_hierarchical_item_groups.
	def item_group_counts(self, groups):
		"""{group: the listing's items in it and in its sub-categories shown on the website}."""
		filters, or_filters = self.scope()
		direct = {
			row.item_group: row.total
			for row in frappe.get_all(
				"Website Item",
				fields=["item_group", "count(name) as total"],
				filters=filters,
				or_filters=or_filters,
				group_by="item_group",
			)
			if row.item_group
		}
		if not direct:
			return {}
		shown = frappe.get_all(
			"Item Group", filters={"show_in_website": 1, "name": ["in", list(direct)]}, fields=["name", "lft"]
		)
		return {
			group.name: direct.get(group.name, 0)
			+ sum(direct[row.name] for row in shown if group.lft < row.lft < group.rgt)
			for group in groups
		}

	def get_brands_with_counts(self, brand_values):
		"""Get brands with their product counts"""
		# //// Neoffice — counted inside the listing's scope (scope() above), in one query: it ran
		# //// one count per brand over the whole catalogue, the variants a shop hides included —
		# //// 14 beside a brand whose grid shows 2 (2026-09-24).
		filters, or_filters = self.scope()
		filters["brand"] = ["in", list(brand_values)]
		counts = {
			row.brand: row.total
			for row in frappe.get_all(
				"Website Item",
				fields=["brand", "count(name) as total"],  # //// Neoffice — one grouped count
				filters=filters,
				or_filters=or_filters,
				group_by="brand",
			)
		}
		# //// Neoffice — a brand the scope does not carry counts 0
		brands_with_counts = [{"name": brand, "count": counts.get(brand, 0)} for brand in brand_values]

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
		# //// Neoffice — the attribute facets are gated on Webshop Settings; a shop that hides
		# //// variants must not offer attribute filters at all, and the two settings are
		# //// mutually exclusive (b103d68868 / 0c15976673, 2025-11-30).
		if not self.doc.enable_attribute_filters:
			return

		attributes = [row.attribute for row in self.doc.filter_attributes]

		if not attributes:
			return []

		# //// Neoffice — the values the listing's own items carry (scope() above), not every value
		# //// of every variant of the instance, published or not: a value no product of the page
		# //// carries led to an empty grid (2026-09-24). The attribute filter finds Website Items
		# //// by their item code (query.query_items_with_attributes), so the scope is read the same way.
		filters, or_filters = self.scope()
		item_codes = frappe.get_all("Website Item", filters=filters, or_filters=or_filters, pluck="item_code")
		if not item_codes:
			return []

		result = frappe.get_all(
			"Item Variant Attribute",
			filters={
				"attribute": ["in", attributes],
				"attribute_value": ["is", "set"],
				"parent": ["in", item_codes],  # //// Neoffice — the listing's own items
			},
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
			# //// Neoffice — attribute values are sorted alphabetically; upstream returns them in
			# //// the order the Item Attribute happens to list them.
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
			label = _("{0}% and below").format(discount)
			discount_filters.append([discount, label])

		return discount_filters

	# //// Neoffice — added (2026-09-24): the slider's two queries read the brand, the stock, the
	# //// discount and the category, nothing else. On /occasions, under the condition or the
	# //// collection facet, the second-hand toggle or a tag, the slider spanned the whole catalogue
	# //// and its ends led to an empty grid; a gift card the shop hides stretched it too.
	PRICE_FILTER_OWN_KEYS = ("brand", "item_group", "in_stock", "discount")

	def price_scope_conditions(self, field_filters):
		"""SQL conditions on `wi` and their named values, for what the grid filters on and the
		price slider's own conditions do not handle."""
		conditions, params = [], {}
		if gift_cards_hidden():
			conditions.append("IFNULL(wi.is_gift_card, 0) = 0")
		meta = frappe.get_meta("Website Item", cached=True)
		for index, (fieldname, values) in enumerate(sorted((field_filters or {}).items())):
			values = values if isinstance(values, (list, tuple, set)) else [values]
			values = [value for value in values if value not in (None, "")]
			if not values or fieldname in self.PRICE_FILTER_OWN_KEYS:
				continue
			key = f"scope_{index}"
			if fieldname == "second_hand":
				from webshop.webshop.utils.used_items import SECOND_HAND_CONDITIONS

				conditions.append(f"wi.item_condition IN %({key})s")
				params[key] = list(SECOND_HAND_CONDITIONS)
			elif fieldname == "_user_tags":
				# the grid's rule (query.build_fields_filters): any of the ticked tags
				likes = []
				for position, tag in enumerate(values):
					likes.append(f"wi._user_tags LIKE %({key}_{position})s")
					params[f"{key}_{position}"] = f"%{tag}%"
				conditions.append("(" + " OR ".join(likes) + ")")
			else:
				df = meta.get_field(fieldname)
				if df and df.fieldtype in ("Link", "Select", "Data"):
					conditions.append(f"wi.`{df.fieldname}` IN %({key})s")
					params[key] = list(values)
		return conditions, params

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

		# //// Neoffice — the listing's locked facets bound the slider like a ticked one: nobody
		# //// sends them at the page's first render (2026-09-24). A block of filters that nothing
		# //// read (item_filters, item_or_filters, additional_conditions) stood here: the queries
		# //// below build their own conditions.
		field_filters = {**(field_filters or {}), **self.locked_field_filters}

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
			# //// Neoffice multi-site — the site's price list wins (price filters).
			from webshop.webshop.multi_site import effective_price_list

			default_price_list = effective_price_list()
			
			# Build the SQL query with all filters
			# //// Neoffice — a sold used unit is out of the catalogue: every surface shows what the listing shows (2026-09-14)
			sql_conditions = ["wi.published = 1", "wi.sold = 0", "wi.item_group IN %(groups)s", "ip.selling = 1"]
			# //// Neoffice multi-site: scope to the current site
			from webshop.webshop.multi_site import site_sql_predicate
			_site_pred = site_sql_predicate("wi")
			if _site_pred:
				sql_conditions.append(_site_pred)
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
			# //// Neoffice — a sold used unit is out of the catalogue: every surface shows what the listing shows (2026-09-14)
			item_sql_conditions = ["wi.published = 1", "wi.sold = 0", "wi.item_group IN %(groups)s"]
			# //// Neoffice multi-site: scope to the current site
			from webshop.webshop.multi_site import site_sql_predicate
			_site_pred = site_sql_predicate("wi")
			if _site_pred:
				item_sql_conditions.append(_site_pred)
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
			
			# //// Neoffice — what the grid filters on and the conditions above do not read
			# //// (price_scope_conditions below, 2026-09-24)
			scope_conditions, scope_params = self.price_scope_conditions(field_filters)
			item_sql_conditions += scope_conditions
			item_sql_params.update(scope_params)

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
			# //// Neoffice multi-site — the site's price list wins (price filters).
			from webshop.webshop.multi_site import effective_price_list

			default_price_list = effective_price_list()
			
			# Get all item codes that match the current filters (without pagination)
			# //// Neoffice — a sold used unit is out of the catalogue: every surface shows what the listing shows (2026-09-14)
			item_sql_conditions = ["wi.published = 1", "wi.sold = 0"]
			# //// Neoffice multi-site: scope to the current site
			from webshop.webshop.multi_site import site_sql_predicate
			_site_pred = site_sql_predicate("wi")
			if _site_pred:
				item_sql_conditions.append(_site_pred)
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
			
			# //// Neoffice — what the grid filters on and the conditions above do not read
			# //// (price_scope_conditions below, 2026-09-24)
			scope_conditions, scope_params = self.price_scope_conditions(field_filters)
			item_sql_conditions += scope_conditions
			item_sql_params.update(scope_params)

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
			# //// Neoffice — a sold used unit is out of the catalogue: every surface shows what the listing shows (2026-09-14)
			fallback_conditions = ["wi.published = 1", "wi.sold = 0"]
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

		# //// Neoffice — the tags of the listing's own items (scope() above, 2026-09-24): it read the
		# //// whole catalogue on a brand's page and on /occasions, and a category's own level only
		item_filters, item_or_filters = self.scope()

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
		-- //// Neoffice — a sold used unit is out of the catalogue: every surface shows what the listing shows (2026-09-14)
		WHERE published = 1 AND sold = 0 AND item_group IS NOT NULL
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