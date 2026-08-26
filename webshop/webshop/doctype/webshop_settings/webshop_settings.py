# -*- coding: utf-8 -*-
# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

from webshop.webshop.redisearch_utils import is_search_module_loaded
from webshop.webshop.utils.frequently_bought_together import calculate_frequently_bought_together


class ShoppingCartSetupError(frappe.ValidationError):
	pass


class WebshopSettings(Document):
	def onload(self):
		self.get("__onload").quotation_series = frappe.get_meta("Quotation").get_options("naming_series")

		# flag >> if redisearch is installed and loaded
		self.is_redisearch_loaded = is_search_module_loaded()

	def validate(self):
		self.validate_field_filters(self.filter_fields, self.enable_field_filters)
		self.validate_attribute_filters()
		self.validate_checkout()
		#//// Neoffice — multi-warehouse: validate the source table and, on
		#//// activation, set the two ERPNext prerequisites (Selling and Buying
		#//// "allow multiple items"), without which a two-line order of the
		#//// same item is rejected. Done here so activating the feature is
		#//// self-contained instead of relying on a fleet-wide patch.
		self.validate_multi_warehouse()

		# Désactiver les options en cascade
		if not self.enabled:
			self.enable_checkout = 0
			self.enable_checkout_page = 0
			self.enable_guest_cart = 0
		elif not self.enable_checkout:
			self.enable_checkout_page = 0
			self.enable_guest_cart = 0
		elif not self.enable_checkout_page:
			self.enable_guest_cart = 0

		if self.enabled:
			self.validate_price_list_exchange_rate()

		frappe.clear_document_cache("Webshop Settings", "Webshop Settings")

		# Save current state of enable_gift_cards for comparison in after_save
		self.enable_gift_cards_pre_save = frappe.db.get_single_value(
			"Webshop Settings", "enable_gift_cards"
		)

		# Save current state of enable_loyalty_points for comparison
		self.enable_loyalty_points_pre_save = frappe.db.get_single_value(
			"Webshop Settings", "enable_loyalty_points"
		)

		self.update_gift_card_template()
		self.update_gift_cards_menu()
		self.update_loyalty_points_menu()

	#//// Neoffice — added method (multi-warehouse feature).
	def validate_multi_warehouse(self):
		if not self.enable_multi_warehouse:
			return

		seen = set()
		item_meta = frappe.get_meta("Item")
		for row in self.warehouse_sources or []:
			if row.warehouse in seen:
				frappe.throw(
					_("Warehouse Source row #{0}: warehouse {1} is listed twice").format(
						row.idx, row.warehouse
					)
				)
			seen.add(row.warehouse)

			if row.stock_basis == "Item Field":
				if not row.stock_field or not item_meta.has_field(row.stock_field):
					frappe.throw(
						_(
							"Warehouse Source row #{0}: field {1} does not exist on Item"
						).format(row.idx, row.stock_field or "?")
					)
				field_type = item_meta.get_field(row.stock_field).fieldtype
				if field_type not in ("Int", "Float"):
					frappe.throw(
						_(
							"Warehouse Source row #{0}: field {1} must be numeric (Int or Float), not {2}"
						).format(row.idx, row.stock_field, field_type)
					)

			if row.order_day_of_month and not (1 <= cint(row.order_day_of_month) <= 28):
				frappe.throw(
					_(
						"Warehouse Source row #{0}: Order Day of Month must be between 1 and 28"
					).format(row.idx)
				)

		# Two lines of the same item (one per source) require these two
		# ERPNext settings; set them on activation and tell the merchant.
		for doctype in ("Selling Settings", "Buying Settings"):
			if not cint(frappe.db.get_single_value(doctype, "allow_multiple_items")):
				frappe.db.set_single_value(doctype, "allow_multiple_items", 1)
				frappe.msgprint(
					_(
						"Multi-warehouse: enabled \"Allow Item to Be Added Multiple Times in a Transaction\" in {0}"
					).format(_(doctype)),
					alert=True,
				)

		# Reserving received goods for the customer order is entirely native:
		# turn on the two Stock Settings that drive it.
		if cint(self.reserve_stock_on_receipt):
			for fieldname in (
				"enable_stock_reservation",
				"auto_reserve_stock_for_sales_order_on_purchase",
			):
				if not frappe.get_meta("Stock Settings").has_field(fieldname):
					frappe.msgprint(
						_(
							"Stock reservation is not available in this ERPNext version; received goods will not be reserved."
						),
						alert=True,
					)
					break
				if not cint(frappe.db.get_single_value("Stock Settings", fieldname)):
					frappe.db.set_single_value("Stock Settings", fieldname, 1)
					frappe.msgprint(
						_("Multi-warehouse: enabled {0} in Stock Settings").format(
							frappe.get_meta("Stock Settings").get_label(fieldname)
						),
						alert=True,
					)

	def after_save(self):
		# Clear currency symbol cache when settings change
		frappe.cache().delete_value("webshop_hide_currency_symbol")
	
	def update_gift_cards_menu(self):
		"""Updates gift cards menu in Portal Settings based on enable_gift_cards"""
		if self.enable_gift_cards == self.enable_gift_cards_pre_save:
			return

		# Check if entry already exists (check both old and new routes)
		exists = frappe.db.exists("Portal Menu Item", {
			"route": "/gift_cards",
			"parenttype": "Portal Settings"
		})

		# Also check for old route with hyphen
		old_exists = frappe.db.exists("Portal Menu Item", {
			"route": "/gift-cards",
			"parenttype": "Portal Settings"
		})

		if self.enable_gift_cards and not exists:
			# Delete old route if exists
			if old_exists:
				frappe.db.delete("Portal Menu Item", {
					"route": "/gift-cards",
					"parenttype": "Portal Settings"
				})

			# Get last idx
			last_idx = frappe.db.sql("""
				SELECT MAX(idx)
				FROM `tabPortal Menu Item`
				WHERE parenttype='Portal Settings'
			""")[0][0] or 0

			# Create menu entry with new route
			portal_settings = frappe.get_doc("Portal Settings")
			portal_settings.append("menu", {
				"title": "Gift cards",
				"enabled": 1,
				"route": "/gift_cards",
				"role": "Customer",
				"idx": last_idx + 1
			})

			portal_settings.save()

		elif not self.enable_gift_cards:
			# Delete both old and new routes if they exist
			if exists:
				frappe.db.delete("Portal Menu Item", {
					"route": "/gift_cards",
					"parenttype": "Portal Settings"
				})
			if old_exists:
				frappe.db.delete("Portal Menu Item", {
					"route": "/gift-cards",
					"parenttype": "Portal Settings"
				})
			frappe.db.commit()

	def update_loyalty_points_menu(self):
		"""Updates loyalty points menu in Portal Settings based on enable_loyalty_points"""
		if self.enable_loyalty_points == self.enable_loyalty_points_pre_save:
			return

		# Check if entry already exists
		exists = frappe.db.exists("Portal Menu Item", {
			"route": "/loyalty_points",
			"parenttype": "Portal Settings"
		})

		if self.enable_loyalty_points and not exists:
			# Get last idx
			last_idx = frappe.db.sql("""
				SELECT MAX(idx)
				FROM `tabPortal Menu Item`
				WHERE parenttype='Portal Settings'
			""")[0][0] or 0

			# Create menu entry
			portal_settings = frappe.get_doc("Portal Settings")
			portal_settings.append("menu", {
				"title": "Loyalty Points",
				"enabled": 1,
				"route": "/loyalty_points",
				"role": "Customer",
				"idx": last_idx + 1
			})

			portal_settings.save()

		elif not self.enable_loyalty_points and exists:
			# Delete menu entry
			frappe.db.delete("Portal Menu Item", {
				"route": "/loyalty_points",
				"parenttype": "Portal Settings"
			})
			frappe.db.commit()

	@staticmethod
	def validate_field_filters(filter_fields, enable_field_filters):
		if not (enable_field_filters and filter_fields):
			return

		web_item_meta = frappe.get_meta("Website Item")
		valid_fields = [
			df.fieldname for df in web_item_meta.fields if df.fieldtype in ["Link", "Table MultiSelect"]
		]

		for row in filter_fields:
			if row.fieldname not in valid_fields:
				frappe.throw(
					_(
						"Filter Fields Row #{0}: Fieldname {1} must be of type 'Link' or 'Table MultiSelect'"
					).format(row.idx, frappe.bold(row.fieldname))
				)

	def validate_attribute_filters(self):
		if not (self.enable_attribute_filters and self.filter_attributes):
			return

		# if attribute filters are enabled with filter_attributes configured,
		# hide_variants cannot be enabled - they are mutually exclusive features
		if self.hide_variants:
			frappe.throw(
				_("Cannot enable 'Hide Variants' when 'Attribute Filters' are enabled with filter attributes configured. "
				  "These features are mutually exclusive: Attribute filters allow customers to filter by variant attributes "
				  "(like Size, Color), which requires variants to be visible. "
				  "Please disable 'Enable Attribute Filters' or remove all Filter Attributes first."),
				title=_("Configuration Conflict")
			)

	def validate_checkout(self):
		if self.enable_checkout and not self.payment_gateway_account:
			self.enable_checkout = 0

	def validate_price_list_exchange_rate(self):
		"Check if exchange rate exists for Price List currency (to Company's currency)."
		from erpnext.setup.utils import get_exchange_rate

		if not self.enabled or not self.company or not self.price_list:
			return  # this function is also called from hooks, check values again

		company_currency = frappe.get_cached_value("Company", self.company, "default_currency")
		price_list_currency = frappe.db.get_value("Price List", self.price_list, "currency")

		if not company_currency:
			msg = f"Please specify currency in Company {self.company}"
			frappe.throw(_(msg), title=_("Missing Currency"), exc=ShoppingCartSetupError)

		if not price_list_currency:
			msg = f"Please specify currency in Price List {frappe.bold(self.price_list)}"
			frappe.throw(_(msg), title=_("Missing Currency"), exc=ShoppingCartSetupError)

		if price_list_currency != company_currency:
			from_currency, to_currency = price_list_currency, company_currency

			# Get exchange rate checks Currency Exchange Records too
			exchange_rate = get_exchange_rate(from_currency, to_currency, args="for_selling")

			if not flt(exchange_rate):
				msg = f"Missing Currency Exchange Rates for {from_currency}-{to_currency}"
				frappe.throw(_(msg), title=_("Missing"), exc=ShoppingCartSetupError)

	def validate_tax_rule(self):
		if not frappe.db.get_value("Tax Rule", {"use_for_shopping_cart": 1}, "name"):
			frappe.throw(frappe._("Set Tax Rule for shopping cart"), ShoppingCartSetupError)

	def get_name_from_territory(self, territory, fieldname, doctype):
		"""Gets document name for a given territory"""
		name = None
		if territory:
			name = frappe.db.get_value(
				doctype,
				{fieldname: territory, "is_default": 1},
				"name"
			)
			if not name:
				name = frappe.db.get_value(
					doctype,
					{fieldname: territory},
					"name"
				)
		return name

	def get_tax_master(self, billing_territory):
		"""Gets tax template for a given territory"""
		tax_master = None
		if billing_territory:
			tax_master = frappe.db.get_value(
				"Sales Taxes and Charges Template",
				{"territory": billing_territory, "is_default": 1},
				"name"
			)
			if not tax_master:
				tax_master = frappe.db.get_value(
					"Sales Taxes and Charges Template",
					{"territory": billing_territory},
					"name"
				)
		return tax_master

	def get_shipping_rules(self, shipping_territory):
		"""Gets shipping rules for a given territory"""
		shipping_rules = []
		if shipping_territory:
			shipping_rules = frappe.db.sql(
				"""select * from `tabShipping Rule`
				where disabled != 1
					and territory = %(territory)s
					or territory = ''
				order by name asc""",
				{"territory": shipping_territory},
				as_dict=True,
			)

		return shipping_rules

	@frappe.whitelist()
	def calculate_frequently_bought_together_items(self):
		"""Manually trigger calculation of frequently bought together items"""
		if not self.enable_frequently_bought_together:
			frappe.throw(_("Please enable 'Frequently Bought Together' first"))
		
		return calculate_frequently_bought_together()
	
	@frappe.whitelist()
	def regenerate_sitemap(self):
		"""Clear sitemap cache and regenerate all sitemaps"""
		from frappe.utils import now_datetime

		# List of cache keys to clear
		cache_keys = [
			"webshop.www.sitemap.get_published_doctype_pages",
			"webshop.www.sitemap.get_builder_pages",
			"webshop.www.sitemap.get_web_pages",
			"webshop.www.sitemap_products.get_product_links",
			"webshop.www.sitemap_categories.get_category_links",
			"webshop.www.sitemap_brands.get_brand_links",
			"webshop.www.sitemap_blog.get_blog_links",
			"webshop.www.sitemap_pages.get_builder_page_links",
			"webshop.www.sitemap_pages.get_web_page_links"
		]

		# Clear each cache using frappe.cache()
		cache = frappe.cache()
		for key in cache_keys:
			try:
				cache.delete_key(key)
			except Exception:
				pass
		
		# Update last generated timestamp
		self.db_set("sitemap_last_generated", now_datetime())
		
		frappe.msgprint(
			_("Sitemap cache has been cleared successfully. The sitemaps will be regenerated on next access."),
			alert=True,
			indicator="green"
		)
		
		return True

	def update_gift_card_template(self):
		"""Updates is_gift_card field on Website Items when gift card template changes"""
		old_doc = None
		if self.name:
			old_doc = frappe.get_doc("Webshop Settings", self.name)

		if old_doc and ((old_doc.enable_gift_cards and not self.enable_gift_cards) or \
			(old_doc.gift_card_template and old_doc.gift_card_template != self.gift_card_template)):
			# If gift cards are disabled or if template has changed,
			# disable old template
			if (old_doc.enable_gift_cards and not self.enable_gift_cards) or \
				(old_doc and old_doc.gift_card_template and old_doc.gift_card_template != self.gift_card_template):
				frappe.db.set_value('Website Item', old_doc.gift_card_template, 'is_gift_card', 0)
		
		# Enable new template only if gift cards are enabled
		if self.enable_gift_cards and self.gift_card_template:
			frappe.db.set_value('Website Item', self.gift_card_template, 'is_gift_card', 1)


def validate_cart_settings(doc=None, method=None):
	frappe.get_doc("Webshop Settings", "Webshop Settings").run_method("validate")

@frappe.whitelist(allow_guest=True)
def get_shopping_cart_settings():
    settings = frappe.get_cached_doc("Webshop Settings")
    settings_dict = settings.as_dict()
    #//// Neoffice multi-site: non-empty Website Profile fields shadow the global
    #//// Single (per-site price list / guest customer); everything else falls
    #//// back to the Single, so instances without profiles are untouched.
    profile = getattr(frappe.local, "website_profile_doc", None)
    if profile:
        for field in ("price_list", "guest_customer"):
            if profile.get(field):
                settings_dict[field] = profile[field]
    return settings_dict

@frappe.whitelist(allow_guest=True)
def is_cart_enabled():
	return get_shopping_cart_settings().enabled


def show_quantity_in_website():
	return get_shopping_cart_settings().show_quantity_in_website


def check_shopping_cart_enabled():
	if not get_shopping_cart_settings().enabled:
		frappe.throw(_("You need to enable Shopping Cart"), ShoppingCartSetupError)


def show_attachments():
	return get_shopping_cart_settings().show_attachments


@frappe.whitelist()
def get_category_tree():
	"""
	Get all Item Groups in a tree structure for ordering.
	Returns hierarchical data with current weightage values.
	"""
	# Get all item groups that are shown on website
	item_groups = frappe.get_all(
		"Item Group",
		filters={"show_in_website": 1},
		fields=["name", "item_group_name", "parent_item_group", "weightage", "is_group", "lft", "rgt"],
		order_by="lft"
	)

	# Build tree structure
	tree = []
	group_map = {g.name: g for g in item_groups}

	# Find root groups (parent not in visible groups = root level for this tree)
	for group in item_groups:
		parent = group.parent_item_group
		# If parent is not in our visible groups, this is a root node for our tree
		if not parent or parent not in group_map:
			tree.append(build_tree_node(group, group_map, item_groups))

	# Sort root level by weightage desc
	tree.sort(key=lambda x: (-(x.get("weightage") or 0), x.get("name", "")))

	return tree


def build_tree_node(group, group_map, all_groups):
	"""Build a tree node with children recursively."""
	node = {
		"name": group.name,
		"label": group.item_group_name or group.name,
		"weightage": group.weightage or 0,
		"is_group": group.is_group,
		"children": []
	}

	# Find children
	for g in all_groups:
		if g.parent_item_group == group.name:
			child_node = build_tree_node(g, group_map, all_groups)
			node["children"].append(child_node)

	# Sort children by weightage desc
	node["children"].sort(key=lambda x: (-(x.get("weightage") or 0), x.get("name", "")))

	return node


@frappe.whitelist()
def save_category_order(order_data):
	"""
	Save the category order by updating weightage on Item Groups.

	Args:
		order_data: JSON string with array of {name, weightage} objects
	"""
	import json

	if isinstance(order_data, str):
		order_data = json.loads(order_data)

	# Validate permissions
	if not frappe.has_permission("Item Group", "write"):
		frappe.throw(_("You don't have permission to modify Item Groups"))

	updated = []
	for item in order_data:
		name = item.get("name")
		weightage = item.get("weightage", 0)

		if name and frappe.db.exists("Item Group", name):
			frappe.db.set_value("Item Group", name, "weightage", weightage, update_modified=False)
			updated.append(name)

	frappe.db.commit()

	return {
		"success": True,
		"message": _("{0} categories updated").format(len(updated)),
		"updated": updated
	}


@frappe.whitelist()
def regenerate_sitemap():
	"""Standalone wrapper for the document method - required for frm.call()"""
	doc = frappe.get_doc("Webshop Settings")
	return doc.regenerate_sitemap()
