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
		cls.brands = {f"{PREFIX} Alpha": 2, f"{PREFIX} Beta": 1}
		cls.items = []

		for brand, count in cls.brands.items():
			if not frappe.db.exists("Brand", brand):
				frappe.get_doc(
					{"doctype": "Brand", "brand": brand, "description": "carousel test"}
				).insert(ignore_permissions=True)

			for i in range(count):
				code = f"{brand} Item {i}"
				make_test_item(code, brand=brand)
				if not frappe.db.exists("Website Item", {"item_code": code}):
					frappe.get_doc(
						{
							"doctype": "Website Item",
							"item_code": code,
							"web_item_name": code,
							"item_group": cls.item_group,
							"brand": brand,
							"published": 1,
							"route": f"products/{code.lower().replace(' ', '-')}",
						}
					).insert(ignore_permissions=True)
				cls.items.append(code)

	@classmethod
	def tearDownClass(cls):
		for code in cls.items:
			name = frappe.db.get_value("Website Item", {"item_code": code}, "name")
			if name:
				frappe.delete_doc("Website Item", name, force=True, ignore_permissions=True)
			if frappe.db.exists("Item", code):
				frappe.delete_doc("Item", code, force=True, ignore_permissions=True)
		for brand in cls.brands:
			if frappe.db.exists("Brand", brand):
				frappe.delete_doc("Brand", brand, force=True, ignore_permissions=True)
		frappe.db.commit()

	def _ours(self, brands):
		return {b["brand_name"]: b for b in brands if b["brand_name"] in self.brands}

	def test_brands_carry_their_published_product_count(self):
		our_brands = self._ours(get_brands_with_product_count(limit=500))

		self.assertEqual(len(our_brands), 2)
		self.assertEqual(our_brands[f"{PREFIX} Alpha"]["product_count"], 2)
		self.assertEqual(our_brands[f"{PREFIX} Beta"]["product_count"], 1)

	def test_unpublished_items_are_not_counted(self):
		code = f"{PREFIX} Beta Item 0"
		name = frappe.db.get_value("Website Item", {"item_code": code}, "name")
		frappe.db.set_value("Website Item", name, "published", 0)
		self.addCleanup(frappe.db.set_value, "Website Item", name, "published", 1)

		our_brands = self._ours(get_brands_with_product_count(limit=500))

		# A brand left with nothing published drops out entirely (HAVING > 0).
		self.assertNotIn(f"{PREFIX} Beta", our_brands)
		self.assertEqual(our_brands[f"{PREFIX} Alpha"]["product_count"], 2)

	def test_sorting_by_product_count_puts_the_fuller_brand_first(self):
		brands = [
			b["brand_name"]
			for b in get_brands_with_product_count(limit=500, sort_by="product_count")
			if b["brand_name"] in self.brands
		]

		self.assertEqual(brands, [f"{PREFIX} Alpha", f"{PREFIX} Beta"])

	def test_a_brand_links_to_its_own_page(self):
		"""A brand carrying a published item has a page, /brands/<slug> (#691 lot 2): the carousel
		links it there, no longer to the catalogue filtered on it, which robots.txt closes."""
		brand = self._ours(get_brands_with_product_count(limit=500))[f"{PREFIX} Alpha"]

		self.assertEqual(brand["route"], "brands/wstest-brand-alpha")

	def test_limit_is_honoured(self):
		self.assertLessEqual(len(get_brands_with_product_count(limit=1)), 1)

	def test_top_brands_reads_through_the_cache_twice(self):
		"""Second call must agree with the first — the cache is keyed per site."""
		first = get_top_brands(limit=5, use_cache=True, cache_ttl=60)
		second = get_top_brands(limit=5, use_cache=True, cache_ttl=60)

		self.assertEqual(first, second)


# //// Neoffice ▼▼▼ — added tests (2026-09-16): the component defends its own input.
class TestACallerVariableDoesNotTakeTheComponentOver(unittest.TestCase):
	"""A page whose data script set `data.brands = [{"name": …}]` silently took this component's
	input over: frappe exposes every key of a page's data into the template context, the component
	skipped its own fetch, and the loop read rows carrying no brand_name — jinja raised
	UndefinedError and the WHOLE page answered 417 on a live client site."""

	TEMPLATE = "webshop/templates/includes/brand_carousel.html"

	def render(self, **context):
		return frappe.render_template(f'{{% include "{self.TEMPLATE}" %}}', context)

	def test_rows_without_the_keys_the_cards_need_do_not_take_the_page_down(self):
		# exactly the shape the page data script produced
		foreign = [{"name": "_WSTEST One", "desc": "Vêtements"}, {"name": "_WSTEST Two", "desc": "Optique"}]
		html = self.render(brands=foreign)
		self.assertIn("brand-carousel", html)

	def test_a_single_bad_row_is_enough_to_refuse_the_whole_list(self):
		mixed = [{"brand_name": "_WSTEST One", "logo": "/files/one.png"}, {"name": "_WSTEST Two"}]
		self.assertIn("brand-carousel", self.render(brands=mixed))

	def test_a_string_or_a_number_is_not_a_list_of_brands(self):
		for junk in ("a brand name", 3, {"brand_name": "not a list"}):
			self.assertIn("brand-carousel", self.render(brands=junk))

	def test_a_caller_that_really_passes_brands_is_still_honoured(self):
		mine = [{"brand_name": "ZZ Test Brand", "logo": "/files/zz.png", "route": "all-products", "description": "", "product_count": 0}]
		html = self.render(brands=mine)
		self.assertIn("ZZ Test Brand", html)
