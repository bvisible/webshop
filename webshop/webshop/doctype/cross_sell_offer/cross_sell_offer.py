# //// Neoffice — added file (cross-sell offers, no upstream equivalent).
"""A cross-sell offer: "when the cart holds A, propose B with an advantage".

The offer is what the shop shows (utils/cross_sell.py). The advantage itself
is a Pricing Rule generated from the offer, so that ERPNext prices B in the
cart, on the order and on the invoice, and drops the discount by itself when
A leaves the cart. No second pricing engine.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

TRIGGER_FIELD = {"Item": "trigger_item", "Item Group": "trigger_item_group", "Brand": "trigger_brand"}
APPLY_ON = {"Item": "Item Code", "Item Group": "Item Group", "Brand": "Brand"}
RULE_TABLE = {
	"Item": ("items", "item_code"),
	"Item Group": ("item_groups", "item_group"),
	"Brand": ("brands", "brand"),
}


class CrossSellOffer(Document):
	def validate(self):
		self.validate_trigger()
		self.validate_offer()
		self.validate_advantage()
		self.warn_about_other_rules()

	def on_update(self):
		self.sync_pricing_rule()

	def on_trash(self):
		self.delete_pricing_rule()

	# --- what the offer says -------------------------------------------

	def trigger_value(self):
		return self.get(TRIGGER_FIELD.get(self.trigger_type, ""))

	def validate_trigger(self):
		field = TRIGGER_FIELD.get(self.trigger_type)
		if not field or not self.get(field):
			frappe.throw(_("Pick what triggers the offer: an item, an item group or a brand."))
		for other in TRIGGER_FIELD.values():
			if other != field:
				self.set(other, None)
		if self.trigger_type == "Item" and self.trigger_item == self.offer_item:
			frappe.throw(_("An item cannot be offered with itself."))

	def validate_offer(self):
		if not frappe.db.exists("Website Item", {"item_code": self.offer_item, "published": 1}):
			frappe.throw(_("The offered item must be published on the website."))
		if flt(self.offer_qty) <= 0:
			self.offer_qty = 1
		self.priority = min(max(cint(self.priority) or 5, 1), 20)

	def validate_advantage(self):
		if self.discount_type == "Percentage":
			if not 0 < flt(self.discount_percentage) <= 100:
				frappe.throw(_("The discount percentage must be between 1 and 100."))
			self.discount_amount = 0
		elif self.discount_type == "Amount":
			if flt(self.discount_amount) <= 0:
				frappe.throw(_("The discount amount must be positive."))
			self.discount_percentage = 0
		else:
			self.discount_percentage = 0
			self.discount_amount = 0

	def warn_about_other_rules(self):
		"""ERPNext applies ONE pricing rule per line: the higher priority wins."""
		if self.discount_type == "None":
			return
		codes = [self.offer_item]
		if self.trigger_type == "Item":
			codes.append(self.trigger_item)
		rows = frappe.db.sql(
			"""select distinct pr.name, pr.title, pr.priority, pric.item_code
			from `tabPricing Rule` pr
			join `tabPricing Rule Item Code` pric on pric.parent = pr.name
			where pr.selling = 1 and pr.disable = 0 and pr.apply_on = 'Item Code'
			  and pric.item_code in %(codes)s and pr.name != %(own)s""",
			{"codes": codes, "own": self.pricing_rule or ""},
			as_dict=True,
		)
		for row in rows:
			if cint(row.priority) >= cint(self.priority):
				frappe.msgprint(
					_("{0} already carries pricing rule {1} (priority {2}); on that line, the higher priority wins.").format(
						frappe.bold(row.item_code), frappe.bold(row.title or row.name), row.priority or 0
					),
					indicator="orange",
					alert=True,
				)

	# --- the pricing rule behind it ----------------------------------------

	def pricing_rule_data(self):
		settings = frappe.get_cached_doc("Webshop Settings")
		currency = (
			frappe.get_cached_value("Price List", settings.price_list, "currency")
			if settings.price_list
			else None
		) or frappe.get_cached_value("Company", settings.company, "default_currency")

		table, fieldname = RULE_TABLE[self.trigger_type]
		data = {
			"title": f"Cross-sell: {self.title}"[:140],
			"apply_on": APPLY_ON[self.trigger_type],
			"items": [],
			"item_groups": [],
			"brands": [],
			"selling": 1,
			"buying": 0,
			"currency": currency,
			"disable": 0 if self.enabled else 1,
			"valid_from": self.valid_from,
			"valid_upto": self.valid_upto,
			#//// Two offers on the same trigger ("ink" and "paper" with the
			#//// printer) are two rules on the same line; without this flag ERPNext
			#//// keeps one of them and, on equal priority, refuses the cart.
			"apply_multiple_pricing_rules": 1,
			"has_priority": 1,
			"priority": str(cint(self.priority) or 5),
			"min_qty": 0,
			"max_qty": 0,
			#//// a Link named `customer_group` gets the session default (Selling Settings)
			#//// the moment the document is inserted — hence the longer fieldname.
			"customer_group": self.only_customer_group,
			"applicable_for": "Customer Group" if self.only_customer_group else None,
		}
		data[table] = [{fieldname: self.trigger_value()}]

		if self.discount_type == "Free":
			data.update(
				{
					"price_or_product_discount": "Product",
					"apply_rule_on_other": None,
					"other_item_code": None,
					"same_item": 0,
					"free_item": self.offer_item,
					"free_qty": flt(self.offer_qty) or 1,
					"free_item_rate": 0,
					"dont_enforce_free_item_qty": 0,
				}
			)
		else:
			data.update(
				{
					"price_or_product_discount": "Price",
					"apply_rule_on_other": "Item Code",
					"other_item_code": self.offer_item,
					"rate_or_discount": "Discount Percentage"
					if self.discount_type == "Percentage"
					else "Discount Amount",
					"discount_percentage": flt(self.discount_percentage),
					"discount_amount": flt(self.discount_amount),
					"free_item": None,
					"free_qty": 0,
				}
			)
		return data

	def sync_pricing_rule(self):
		if self.discount_type == "None":
			self.delete_pricing_rule()
			return

		data = self.pricing_rule_data()
		if self.pricing_rule and frappe.db.exists("Pricing Rule", self.pricing_rule):
			rule = frappe.get_doc("Pricing Rule", self.pricing_rule)
		else:
			rule = frappe.new_doc("Pricing Rule")
		rule.update(data)
		rule.flags.ignore_permissions = True
		rule.save()
		if rule.name != self.pricing_rule:
			self.db_set("pricing_rule", rule.name, update_modified=False)
		frappe.clear_cache(doctype="Pricing Rule")

	def delete_pricing_rule(self):
		if self.pricing_rule and frappe.db.exists("Pricing Rule", self.pricing_rule):
			frappe.delete_doc("Pricing Rule", self.pricing_rule, ignore_permissions=True, force=True)
		if self.pricing_rule:
			self.db_set("pricing_rule", None, update_modified=False)
