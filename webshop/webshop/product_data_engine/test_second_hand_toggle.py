# //// Neoffice — added file (no upstream equivalent).
"""The sidebar's "second-hand only" toggle: one key, resolved by the engine to the
conditions of utils/used_items.py, in both query paths (the ORM one and the discount SQL
one both read `self.filters`)."""

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
