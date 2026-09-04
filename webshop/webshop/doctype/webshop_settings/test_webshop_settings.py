# Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt
import unittest

import frappe

from webshop.webshop.doctype.webshop_settings.webshop_settings import (
	ShoppingCartSetupError,
)


class TestWebshopSettings(unittest.TestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_tax_rule_validation(self):
		#//// Neoffice — every shipping rule is put back exactly as it was. The previous version
		#//// re-enabled them all indiscriminately, so a shop that had a rule disabled on
		#//// purpose came out of the test suite with it enabled (0971ecdb0a, 2026-08-29 "réparer la suite Python et trois défauts qu'elle cachait").
		# Put every rule back the way it was, one by one. The previous version
		# committed `set use_for_shopping_cart = 0` across the table and then set
		# them ALL to 1 — on a live site that silently enrols every tax rule in
		# the shopping cart, including the ones deliberately kept out of it.
		#//// Neoffice — renamed to English identifiers (83f9f23aa "chore(webshop): English identifiers in test_webshop_settings"): this helper and its locals were in French (avant, _restaurer_regles, nom, valeur).
		before = {
			r.name: r.use_for_shopping_cart
			for r in frappe.get_all("Tax Rule", fields=["name", "use_for_shopping_cart"])
		}
		#//// Neoffice — renamed to English identifiers, see above (83f9f23aa).
		self.addCleanup(self._restore_tax_rules, before)

		frappe.db.sql("update `tabTax Rule` set use_for_shopping_cart = 0")
		frappe.db.commit()  # nosemgrep

		cart_settings = frappe.get_doc("Webshop Settings")
		cart_settings.enabled = 1
		if not frappe.db.get_value("Tax Rule", {"use_for_shopping_cart": 1}, "name"):
			self.assertRaises(ShoppingCartSetupError, cart_settings.validate_tax_rule)

	#//// Neoffice — see above.
	def _restore_tax_rules(self, before):
		for name, value in before.items():
			frappe.db.set_value("Tax Rule", name, "use_for_shopping_cart", value, update_modified=False)
		frappe.db.commit()

	def test_invalid_filter_fields(self):
		"Check if Item fields are blocked in Webshop Settings filter fields."
		from frappe.custom.doctype.custom_field.custom_field import create_custom_field

		setup_webshop_settings({"enable_field_filters": 1})

		create_custom_field(
			"Item",
			dict(owner="Administrator", fieldname="test_data", label="Test", fieldtype="Data"),
		)
		settings = frappe.get_doc("Webshop Settings")
		settings.append("filter_fields", {"fieldname": "test_data"})

		self.assertRaises(frappe.ValidationError, settings.save)


def setup_webshop_settings(values_dict):
	"Accepts a dict of values that updates Webshop Settings."
	if not values_dict:
		return

	doc = frappe.get_doc("Webshop Settings", "Webshop Settings")
	doc.update(values_dict)
	doc.save()


test_dependencies = ["Tax Rule"]
