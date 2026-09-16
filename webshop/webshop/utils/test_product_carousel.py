# //// Neoffice — added file (no upstream equivalent): the product carousel's filters.
# Copyright (c) 2026, bVisible and contributors
# License: GNU General Public License v3. See license.txt

"""What the product carousel is asked for, and what it actually queries.

`get_carousel_items` has two paths: an optimised SQL query for the newest articles, and the
general ProductQuery engine for everything else. The fast one is taken for the DEFAULT sort
("creation"), and it accepted an item group but silently dropped the brand — so a carousel
asked for one brand drew the whole shop's newest articles instead (2026-09-16). It draws
products, just the wrong ones, which is why nobody noticed: only the slow path honoured the
brand, so the filter appeared to work whenever the author had also changed the sort.

These tests read the query the fast path builds rather than counting cards on a page: the
filter either reaches the WHERE clause or it does not, and that is the whole question.

//// The spy below passes every other query through to the real database on purpose. Replacing
//// frappe.db.sql wholesale looks tidier and is a trap: everything underneath reads through it,
//// so the settings doc the function loads first comes back empty and frappe reports it as
//// "No module named frappe.core.doctype.webshop_settings" — an import error for a doctype that
//// is not missing at all. It passed locally only because Redis already held that doc.
"""

import unittest
from unittest.mock import patch

import frappe

from webshop.webshop.utils.product_carousel_helper import (
	_get_new_arrivals_optimized,
	get_carousel_items,
)

CAROUSEL_QUERY = "tabWebsite Item"


class TestCarouselFilters(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		# the fast path returns early on a disabled shop, and then queries nothing at all
		cls.was_enabled = frappe.db.get_single_value("Webshop Settings", "enabled")
		if not cls.was_enabled:
			frappe.db.set_single_value("Webshop Settings", "enabled", 1)
			frappe.clear_document_cache("Webshop Settings", "Webshop Settings")

	@classmethod
	def tearDownClass(cls):
		if not cls.was_enabled:
			frappe.db.set_single_value("Webshop Settings", "enabled", cls.was_enabled or 0)
			frappe.clear_document_cache("Webshop Settings", "Webshop Settings")
		frappe.db.rollback()

	def query_for(self, **kwargs):
		"""The SQL and the parameters the fast path runs, with every other query left alone."""
		real = frappe.db.sql
		seen = []

		def spy(query, values=None, *args, **kwargs_):
			if CAROUSEL_QUERY in str(query) and "ORDER BY wi.creation" in str(query):
				seen.append((str(query), values))
				return []
			return real(query, values, *args, **kwargs_)

		with patch.object(frappe.db, "sql", side_effect=spy):
			_get_new_arrivals_optimized(8, **kwargs)
		self.assertEqual(1, len(seen), "the fast path did not run its own query exactly once")
		return seen[0]

	def where(self, query):
		return query.split("WHERE", 1)[1].split("ORDER BY", 1)[0]

	def test_a_carousel_asked_for_one_brand_queries_that_brand(self):
		query, params = self.query_for(brand="Alpha")
		self.assertIn("wi.brand = %(brand)s", self.where(query))
		self.assertEqual("Alpha", params["brand"])

	def test_a_carousel_asked_for_nothing_does_not_narrow_itself(self):
		query, params = self.query_for()
		self.assertNotIn("wi.brand", self.where(query))
		self.assertNotIn("brand", params)

	def test_a_brand_and_a_group_narrow_together(self):
		query, params = self.query_for(brand="Alpha", item_group="Shoes")
		where = self.where(query)
		self.assertIn("wi.brand = %(brand)s", where)
		self.assertIn("wi.item_group = %(item_group)s", where)
		self.assertEqual(("Alpha", "Shoes"), (params["brand"], params["item_group"]))

	def test_the_default_sort_still_carries_the_brand_to_the_query(self):
		"""The regression itself: get_carousel_items chooses the fast path for the default sort,
		so the brand has to survive that choice — not only the slow one."""
		with patch(
			"webshop.webshop.utils.product_carousel_helper._get_new_arrivals_optimized", return_value=[]
		) as fast:
			get_carousel_items(brand="Alpha", limit=8)
		self.assertTrue(fast.called, "the default sort no longer takes the fast path — update this test")
		passed = fast.call_args[1].get("brand") or (fast.call_args[0][3] if len(fast.call_args[0]) > 3 else None)
		self.assertEqual("Alpha", passed)
