# //// Neoffice — added file (no upstream equivalent): the product carousel's filters.
# Copyright (c) 2026, bVisible and contributors
# License: GNU General Public License v3. See license.txt

"""What the product carousel is asked for, and what it actually queries.

`get_carousel_items` has two paths: an optimised SQL query for the newest
articles, and the general ProductQuery engine for everything else. The fast one
is taken for the DEFAULT sort ("creation"), and it accepted an item group but
silently dropped the brand — so a carousel asked for one brand drew the whole
shop's newest articles instead (2026-09-16). It draws products, just the wrong
ones, which is why nobody noticed: only the slow path honoured the brand, so
the filter appeared to work whenever the author had also changed the sort.

These tests read the query the fast path builds, rather than counting cards on
a page: the filter either reaches the WHERE clause or it does not, and that is
the whole question.
"""

import unittest
from unittest.mock import patch

from webshop.webshop.utils.product_carousel_helper import (
	_get_new_arrivals_optimized,
	get_carousel_items,
)


class TestCarouselFilters(unittest.TestCase):
	def query_for(self, **kwargs):
		"""The SQL and the parameters the fast path would run."""
		with patch("frappe.db.sql", return_value=[]) as sql, patch(
			"webshop.webshop.utils.variant_image.inherit_template_images"
		):
			_get_new_arrivals_optimized(8, **kwargs)
		self.assertTrue(sql.called, "the fast path did not query anything")
		return sql.call_args[0][0], sql.call_args[0][1]

	def test_a_carousel_asked_for_one_brand_queries_that_brand(self):
		query, params = self.query_for(brand="Alpha")
		self.assertIn("wi.brand = %(brand)s", query)
		self.assertEqual("Alpha", params["brand"])

	def test_a_carousel_asked_for_nothing_does_not_narrow_itself(self):
		query, params = self.query_for()
		self.assertNotIn("wi.brand", query.split("WHERE", 1)[1].split("ORDER BY", 1)[0])
		self.assertNotIn("brand", params)

	def test_a_brand_and_a_group_narrow_together(self):
		query, params = self.query_for(brand="Alpha", item_group="Shoes")
		where = query.split("WHERE", 1)[1].split("ORDER BY", 1)[0]
		self.assertIn("wi.brand = %(brand)s", where)
		self.assertIn("wi.item_group = %(item_group)s", where)
		self.assertEqual(("Alpha", "Shoes"), (params["brand"], params["item_group"]))

	def test_the_default_sort_still_carries_the_brand_to_the_query(self):
		"""The regression itself: get_carousel_items chooses the fast path for the default
		sort, so the brand has to survive that choice — not only the slow one."""
		with patch(
			"webshop.webshop.utils.product_carousel_helper._get_new_arrivals_optimized", return_value=[]
		) as fast:
			get_carousel_items(brand="Alpha", limit=8)
		self.assertTrue(fast.called, "the default sort no longer takes the fast path — update this test")
		# the brand is the fourth positional argument, or a keyword
		passed = fast.call_args[1].get("brand") or (fast.call_args[0][3] if len(fast.call_args[0]) > 3 else None)
		self.assertEqual("Alpha", passed)
