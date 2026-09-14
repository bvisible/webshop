# //// Neoffice — added file (no upstream equivalent).
"""The sidebar's "second-hand only" toggle: one key, resolved by the engine to the
conditions of utils/used_items.py, in both query paths (the ORM one and the discount SQL
one both read `self.filters`)."""

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.product_data_engine.query import ProductQuery
from webshop.webshop.utils.used_items import SECOND_HAND_CONDITIONS


class TestSecondHandToggle(FrappeTestCase):
	def test_the_key_becomes_a_condition_filter(self):
		query = ProductQuery()
		before = len(query.filters)
		query.build_fields_filters({"second_hand": ["1"]})
		added = query.filters[before:]
		self.assertEqual(added, [["item_condition", "in", list(SECOND_HAND_CONDITIONS)]])

	def test_an_empty_value_adds_nothing(self):
		query = ProductQuery()
		before = len(query.filters)
		query.build_fields_filters({"second_hand": []})
		self.assertEqual(query.filters[before:], [])


# //// (2026-09-14) the figures next to the two toggles, and the sold units' exclusion
class TestSidebarCounts(FrappeTestCase):
	def test_the_listing_never_shows_a_sold_unit(self):
		self.assertIn(["sold", "=", 0], ProductQuery().filters)
		where, values = ProductQuery().base_where_clause()
		self.assertIn("wi.`sold` = %s", where)
		self.assertIn("wi.`published` = %s", where)

	def test_the_discount_count_is_an_integer_and_is_cached(self):
		from webshop.webshop.product_data_engine.listing_context import (
			DISCOUNT_COUNT_CACHE,
			clear_discount_count,
			count_discounted,
		)
		from webshop.webshop.product_data_engine.query import count_discounted_items

		clear_discount_count()
		live = count_discounted_items()
		self.assertIsInstance(live, int)
		self.assertGreaterEqual(live, 0)
		self.assertEqual(count_discounted(), live)
		keys = [k for k in frappe.cache().get_keys(DISCOUNT_COUNT_CACHE)]
		self.assertTrue(keys, "the figure is kept in the cache")
		clear_discount_count()
		self.assertFalse([k for k in frappe.cache().get_keys(DISCOUNT_COUNT_CACHE)])
