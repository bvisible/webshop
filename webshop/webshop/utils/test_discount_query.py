# //// Neoffice — added file (no upstream equivalent). Covers the discounted-products
# //// query behind the "on sale" filter (6fea19b1fe, 2025-06-17). Fixtures are resolved
# //// from the site, never hard-coded, and are the module's own item and price list, so
# //// a run cannot be silently skipped by an empty catalogue (0971ecdb0a, 2026-08-29).
# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

"""Tests for the discounted-products queries.

Names are resolved from the site, never hard-coded: the previous version asked
for "Standard Selling" and "All Customer Groups", which do not exist on a site
installed in another language — every test errored before reaching an assertion.

The fixtures are the module's own item and price list rather than the first
published item found, so a run cannot be silently skipped by an empty catalogue
nor perturbed by whatever the shop happens to sell.
"""

import unittest

import frappe
from frappe.utils import add_days, nowdate

from webshop.webshop.tests.utils import (
	default_company,
	leaf_item_group,
	root_customer_group,
	selling_price_list,
)
from webshop.webshop.utils.discount_query import (
	get_discounted_items_count,
	get_discounted_items_query,
	get_items_with_pricing_rule_discount,
)

PREFIX = "_Test Discount Query"


class TestDiscountQuery(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.company = default_company()
		cls.price_list = selling_price_list()
		cls.customer_group = root_customer_group()
		cls.compare_at = f"{PREFIX} Compare At"
		cls.item_code = f"{PREFIX} Item"
		cls.item_group = leaf_item_group()

		cls._settings_avant = frappe.db.get_single_value(
			"Webshop Settings", "compare_at_price_list"
		)

		if not frappe.db.exists("Item", cls.item_code):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": cls.item_code,
					"item_name": cls.item_code,
					"item_group": cls.item_group,
					"stock_uom": frappe.db.get_value("UOM", {}, "name"),
					"is_stock_item": 0,
				}
			).insert(ignore_permissions=True)

		if not frappe.db.exists("Website Item", {"item_code": cls.item_code}):
			frappe.get_doc(
				{
					"doctype": "Website Item",
					"item_code": cls.item_code,
					"web_item_name": cls.item_code,
					"item_group": cls.item_group,
					"published": 1,
					"route": f"products/{PREFIX.lower().replace(' ', '-')}-item",
				}
			).insert(ignore_permissions=True)

		if not frappe.db.exists("Price List", cls.compare_at):
			frappe.get_doc(
				{
					"doctype": "Price List",
					"price_list_name": cls.compare_at,
					"enabled": 1,
					"selling": 1,
					"currency": frappe.db.get_value("Price List", cls.price_list, "currency"),
				}
			).insert(ignore_permissions=True)

		cls._prix(cls.price_list, 100)
		cls._prix(cls.compare_at, 125)

	@classmethod
	def _prix(cls, price_list, taux):
		existant = frappe.db.get_value(
			"Item Price", {"item_code": cls.item_code, "price_list": price_list}, "name"
		)
		if existant:
			frappe.db.set_value("Item Price", existant, "price_list_rate", taux)
			return
		frappe.get_doc(
			{
				"doctype": "Item Price",
				"item_code": cls.item_code,
				"price_list": price_list,
				"price_list_rate": taux,
				"selling": 1,
			}
		).insert(ignore_permissions=True)

	@classmethod
	def tearDownClass(cls):
		frappe.db.set_single_value(
			"Webshop Settings", "compare_at_price_list", cls._settings_avant or None
		)
		for doctype, filtres in (
			("Pricing Rule", {"title": ("like", f"{PREFIX}%")}),
			("Item Price", {"item_code": cls.item_code}),
			("Website Item", {"item_code": cls.item_code}),
			("Item", {"item_code": cls.item_code}),
			("Price List", {"name": cls.compare_at}),
		):
			for nom in frappe.get_all(doctype, filters=filtres, pluck="name"):
				frappe.delete_doc(doctype, nom, force=True, ignore_permissions=True)
		frappe.db.commit()

	def _regle(self, titre, **surcharges):
		"""A selling Pricing Rule targeting our item through its child table.

		The targets of a rule live in `Pricing Rule Item Code` and friends: a
		top-level "item_code" key is not a field of the doctype, so it is
		dropped on insert and the rule ends up applying to nothing at all.
		"""
		valeurs = {
			"doctype": "Pricing Rule",
			"title": f"{PREFIX} {titre}",
			"apply_on": "Item Code",
			"items": [{"item_code": self.item_code}],
			"selling": 1,
			"applicable_for": "Customer Group",
			"customer_group": self.customer_group,
			"rate_or_discount": "Discount Percentage",
			"discount_percentage": 10,
			"company": self.company,
			"valid_from": nowdate(),
			"valid_upto": add_days(nowdate(), 30),
			"price_or_product_discount": "Price",
		}
		valeurs.update(surcharges)
		regle = frappe.get_doc(valeurs)
		regle.insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.delete_doc("Pricing Rule", regle.name, force=True, ignore_permissions=True))
		return regle

	def _resultats(self, **kwargs):
		return get_discounted_items_query(
			price_list=self.price_list,
			company=self.company,
			customer_group=self.customer_group,
			limit=50,
			**kwargs,
		)

	def test_item_with_pricing_rule_is_listed(self):
		self._regle("Rule")

		trouve = [r for r in self._resultats() if r.item_code == self.item_code]

		self.assertTrue(trouve, "an item targeted by an active discount rule must be listed")
		self.assertEqual(trouve[0].discount_percent, 10)
		self.assertIn("pricing_rule", trouve[0].discount_sources)

	def test_transaction_rule_does_not_discount_the_catalogue(self):
		"""A whole-order rule targets no item, so it must not flag any.

		This is what the old query did: `OR pr.apply_on = 'Transaction'` matched
		every row, so a single "10% off orders over 500" rule would have shown
		the entire shop as on sale.
		"""
		self._regle("Transaction Rule", apply_on="Transaction", items=[], applicable_for=None, customer_group=None)

		codes = [r.item_code for r in self._resultats()]

		self.assertNotIn(self.item_code, codes)

	def test_expired_rule_is_ignored(self):
		self._regle(
			"Expired Rule",
			valid_from=add_days(nowdate(), -30),
			valid_upto=add_days(nowdate(), -1),
		)

		codes = [r.item_code for r in self._resultats()]

		self.assertNotIn(self.item_code, codes)

	def test_disabled_rule_is_ignored(self):
		self._regle("Disabled Rule", disable=1)

		codes = [r.item_code for r in self._resultats()]

		self.assertNotIn(self.item_code, codes)

	def test_compare_at_price_list_yields_a_discount(self):
		"""125 on the compare-at list against 100 charged is a 20% discount."""
		frappe.db.set_single_value("Webshop Settings", "compare_at_price_list", self.compare_at)
		self.addCleanup(
			frappe.db.set_single_value, "Webshop Settings", "compare_at_price_list", None
		)

		trouve = [r for r in self._resultats() if r.item_code == self.item_code]

		self.assertTrue(trouve, "an item priced below the compare-at list must be listed")
		self.assertAlmostEqual(trouve[0].discount_percent, 20.0, places=2)
		self.assertIn("price_list_diff", trouve[0].discount_sources)

	def test_no_compare_at_price_list_means_no_comparison(self):
		"""Unset, the two lists must not be compared — nothing is on sale here."""
		frappe.db.set_single_value("Webshop Settings", "compare_at_price_list", None)

		codes = [r.item_code for r in self._resultats()]

		self.assertNotIn(self.item_code, codes)

	def test_count_matches_the_listing(self):
		self._regle("Counted Rule")

		count = get_discounted_items_count(
			price_list=self.price_list,
			company=self.company,
			customer_group=self.customer_group,
		)

		self.assertIsInstance(count, int)
		self.assertGreaterEqual(count, len(self._resultats()))

	def test_promotional_query_returns_the_rule_it_applied(self):
		regle = self._regle("Promo Rule")

		trouve = [
			r
			for r in get_items_with_pricing_rule_discount(
				price_list=self.price_list,
				company=self.company,
				customer_group=self.customer_group,
				limit=50,
			)
			if r.item_code == self.item_code
		]

		self.assertTrue(trouve, "an item under an active discount rule must be promotable")
		self.assertEqual(trouve[0].pricing_rule_title, regle.title)
		self.assertEqual(trouve[0].effective_discount_percent, 10)

	def test_item_group_filter_restricts_results(self):
		self._regle("Filtered Rule")
		autre = frappe.db.get_value(
			"Item Group", {"is_group": 0, "name": ("!=", self.item_group)}, "name"
		)
		if not autre:
			self.skipTest("site has a single leaf item group")

		self.assertIn(self.item_code, [r.item_code for r in self._resultats(filters={"item_group": self.item_group})])
		self.assertNotIn(self.item_code, [r.item_code for r in self._resultats(filters={"item_group": autre})])
