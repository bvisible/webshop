# //// Neoffice — added file (no upstream equivalent). Real tests for the brand
# //// carousel. The file used to hold two whitelisted debug endpoints named `test_*`:
# //// no assertions, no caller, reachable over the API on any site — and the runner
# //// reported "Ran 0 tests" as if the carousel were covered (0971ecdb0a, 2026-08-29).
# Copyright (c) 2026, bVisible and contributors
# License: GNU General Public License v3. See license.txt

"""Tests for the brand carousel.

This module used to hold two whitelisted debug endpoints named `test_*` — no
assertions, no caller anywhere in the app, but reachable over the API on any
site that installs webshop. The test runner collected the file, found no
TestCase, and reported "Ran 0 tests" as if the carousel were covered.
"""

import unittest
from urllib.parse import quote

import frappe

from webshop.webshop.tests.utils import leaf_item_group, make_test_item
from webshop.webshop.utils.brand_carousel_helper import (
	get_brands_with_product_count,
	get_top_brands,
)

PREFIX = "_WSTEST Brand"


class TestBrandCarousel(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		cls.item_group = leaf_item_group()
		# Two brands, unevenly stocked, so ordering by product count is testable:
		# Alpha carries two published items, Beta one.
		cls.marques = {f"{PREFIX} Alpha": 2, f"{PREFIX} Beta": 1}
		cls.articles = []

		for marque, nombre in cls.marques.items():
			if not frappe.db.exists("Brand", marque):
				frappe.get_doc(
					{"doctype": "Brand", "brand": marque, "description": "carousel test"}
				).insert(ignore_permissions=True)

			for i in range(nombre):
				code = f"{marque} Item {i}"
				make_test_item(code, brand=marque)
				if not frappe.db.exists("Website Item", {"item_code": code}):
					frappe.get_doc(
						{
							"doctype": "Website Item",
							"item_code": code,
							"web_item_name": code,
							"item_group": cls.item_group,
							"brand": marque,
							"published": 1,
							"route": f"products/{code.lower().replace(' ', '-')}",
						}
					).insert(ignore_permissions=True)
				cls.articles.append(code)

	@classmethod
	def tearDownClass(cls):
		for code in cls.articles:
			nom = frappe.db.get_value("Website Item", {"item_code": code}, "name")
			if nom:
				frappe.delete_doc("Website Item", nom, force=True, ignore_permissions=True)
			if frappe.db.exists("Item", code):
				frappe.delete_doc("Item", code, force=True, ignore_permissions=True)
		for marque in cls.marques:
			if frappe.db.exists("Brand", marque):
				frappe.delete_doc("Brand", marque, force=True, ignore_permissions=True)
		frappe.db.commit()

	def _notres(self, marques):
		return {b["brand_name"]: b for b in marques if b["brand_name"] in self.marques}

	def test_brands_carry_their_published_product_count(self):
		nos_marques = self._notres(get_brands_with_product_count(limit=500))

		self.assertEqual(len(nos_marques), 2)
		self.assertEqual(nos_marques[f"{PREFIX} Alpha"]["product_count"], 2)
		self.assertEqual(nos_marques[f"{PREFIX} Beta"]["product_count"], 1)

	def test_unpublished_items_are_not_counted(self):
		code = f"{PREFIX} Beta Item 0"
		nom = frappe.db.get_value("Website Item", {"item_code": code}, "name")
		frappe.db.set_value("Website Item", nom, "published", 0)
		self.addCleanup(frappe.db.set_value, "Website Item", nom, "published", 1)

		nos_marques = self._notres(get_brands_with_product_count(limit=500))

		# A brand left with nothing published drops out entirely (HAVING > 0).
		self.assertNotIn(f"{PREFIX} Beta", nos_marques)
		self.assertEqual(nos_marques[f"{PREFIX} Alpha"]["product_count"], 2)

	def test_sorting_by_product_count_puts_the_fuller_brand_first(self):
		marques = [
			b["brand_name"]
			for b in get_brands_with_product_count(limit=500, sort_by="product_count")
			if b["brand_name"] in self.marques
		]

		self.assertEqual(marques, [f"{PREFIX} Alpha", f"{PREFIX} Beta"])

	def test_route_filters_the_listing_on_that_brand(self):
		marque = self._notres(get_brands_with_product_count(limit=500))[f"{PREFIX} Alpha"]

		attendu = quote('{"brand":["' + f"{PREFIX} Alpha" + '"]}')
		self.assertEqual(marque["route"], f"all-products?field_filters={attendu}")

	def test_limit_is_honoured(self):
		self.assertLessEqual(len(get_brands_with_product_count(limit=1)), 1)

	def test_top_brands_reads_through_the_cache_twice(self):
		"""Second call must agree with the first — the cache is keyed per site."""
		premier = get_top_brands(limit=5, use_cache=True, cache_ttl=60)
		second = get_top_brands(limit=5, use_cache=True, cache_ttl=60)

		self.assertEqual(premier, second)
