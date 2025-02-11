# -*- coding: utf-8 -*-
# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import comma_and, flt, unique

from webshop.webshop.redisearch_utils import (
	create_website_items_index,
	define_autocomplete_dictionary,
	get_indexable_web_fields,
	is_search_module_loaded,
)


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
		self.validate_search_index_fields()

		if self.enabled:
			self.validate_price_list_exchange_rate()

		frappe.clear_document_cache("Webshop Settings", "Webshop Settings")

		self.is_redisearch_enabled_pre_save = frappe.db.get_single_value(
			"Webshop Settings", "is_redisearch_enabled"
		)
		
		# Save current state of enable_gift_cards for comparison in after_save
		self.enable_gift_cards_pre_save = frappe.db.get_single_value(
			"Webshop Settings", "enable_gift_cards"
		)

		self.update_gift_card_template()
		self.update_gift_cards_menu()

	def after_save(self):
		self.create_redisearch_indexes()
	
	def update_gift_cards_menu(self):
		"""Updates gift cards menu in Portal Settings based on enable_gift_cards"""
		if self.enable_gift_cards == self.enable_gift_cards_pre_save:
			return

		# Check if entry already exists
		exists = frappe.db.exists("Portal Menu Item", {
			"route": "/gift-cards",
			"parenttype": "Portal Settings"
		})

		if self.enable_gift_cards and not exists:
			# Get last idx
			last_idx = frappe.db.sql("""
				SELECT MAX(idx) 
				FROM `tabPortal Menu Item` 
				WHERE parenttype='Portal Settings'
			""")[0][0] or 0

			# Create menu entry
			portal_settings = frappe.get_doc("Portal Settings")
			portal_settings.append("menu", {
				"title": "Gift cards",
				"enabled": 1,
				"route": "/gift-cards",
				"reference_doctype": "Coupon Code",
				"role": "Customer",
				"idx": last_idx + 1
			})
			
			portal_settings.save()

		elif not self.enable_gift_cards and exists:
			# Delete menu entry
			frappe.db.delete("Portal Menu Item", {
				"route": "/gift-cards",
				"parenttype": "Portal Settings"
			})
			frappe.db.commit()

	def create_redisearch_indexes(self):
		# if redisearch is enabled (value changed) create indexes and dictionary
		value_changed = self.is_redisearch_enabled != self.is_redisearch_enabled_pre_save
		if self.is_redisearch_loaded and self.is_redisearch_enabled and value_changed:
			define_autocomplete_dictionary()
			create_website_items_index()

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

		# if attribute filters are enabled, hide_variants should be disabled
		self.hide_variants = 0

	def validate_checkout(self):
		if self.enable_checkout and not self.payment_gateway_account:
			self.enable_checkout = 0

	def validate_search_index_fields(self):
		if not self.search_index_fields:
			return

		fields = self.search_index_fields.replace(" ", "")
		fields = unique(fields.strip(",").split(","))  # Remove extra ',' and remove duplicates

		# All fields should be indexable
		allowed_indexable_fields = get_indexable_web_fields()

		if not (set(fields).issubset(allowed_indexable_fields)):
			invalid_fields = list(set(fields).difference(allowed_indexable_fields))
			num_invalid_fields = len(invalid_fields)
			invalid_fields = comma_and(invalid_fields)

			if num_invalid_fields > 1:
				frappe.throw(
					_("{0} are not valid options for Search Index Field.").format(frappe.bold(invalid_fields))
				)
			else:
				frappe.throw(
					_("{0} is not a valid option for Search Index Field.").format(frappe.bold(invalid_fields))
				)

		self.search_index_fields = ",".join(fields)

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

	def on_change(self):
		old_doc = self.get_doc_before_save()

		if old_doc:
			old_fields = old_doc.search_index_fields
			new_fields = self.search_index_fields

			# if search index fields get changed
			if not (new_fields == old_fields):
				create_website_items_index()

	def update_gift_card_template(self):
		"""Updates is_gift_card field on Website Items when gift card template changes"""
		if not self.is_new():
			old_doc = self.get_doc_before_save()
			
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
    return settings.as_dict()

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
