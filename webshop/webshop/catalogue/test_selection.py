# //// Neoffice — added file (no upstream equivalent).
"""What a catalogue holds: the cleaning of what a browser sends, and which products a selection stands for.

The first half is pure; the second runs on the small shop of `fixtures.py` (a tree of item groups, two
brands, a model with variants, a product that is not published and one that is sold).
"""

import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.catalogue import fixtures as shop
from webshop.webshop.catalogue import selection
from webshop.webshop.catalogue.selection import SelectionRefused, clean_selection


class TestCleaning(unittest.TestCase):
	def test_the_three_lists_are_kept_trimmed_and_without_repeats(self):
		clean = clean_selection(
			{"item_groups": [" Shoes ", "Shoes", ""], "brands": ["Acme"], "items": ["A-1", "A-1", "A-2"], "price": 1}
		)
		self.assertEqual(clean, {"item_groups": ["Shoes"], "brands": ["Acme"], "items": ["A-1", "A-2"]})

	def test_the_json_text_of_a_selection_is_read_too(self):
		self.assertEqual(clean_selection('{"items": ["A-1"]}')["items"], ["A-1"])

	def test_a_missing_list_is_an_empty_one(self):
		self.assertEqual(clean_selection({"brands": ["Acme"]}), {"item_groups": [], "brands": ["Acme"], "items": []})

	def test_what_is_not_a_selection_is_refused_with_a_reason(self):
		for raw, reason in (
			(None, "not_a_selection"),
			("not json", "not_a_selection"),
			(["Shoes"], "not_a_selection"),
			({"items": "A-1"}, "not_a_list"),
			({"items": [["A-1"]]}, "not_text"),
			({"items": [1]}, "not_text"),
			({"items": ["x" * 141]}, "too_long"),
			({"items": [f"A-{n}" for n in range(301)]}, "too_many"),
			({}, "empty"),
			({"items": [], "brands": [" "]}, "empty"),
		):
			with self.subTest(raw=str(raw)[:30]):
				with self.assertRaises(SelectionRefused) as caught:
					clean_selection(raw)
				self.assertEqual(caught.exception.reason, reason)

	def test_the_longest_name_and_the_longest_list_are_still_accepted(self):
		clean = clean_selection({"items": ["x" * 140], "brands": [f"B-{n}" for n in range(300)]})
		self.assertEqual(len(clean["items"][0]), 140)
		self.assertEqual(len(clean["brands"]), 300)


class TestWhatASelectionHolds(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		shop.make()

	@classmethod
	def tearDownClass(cls):
		shop.purge()
		super().tearDownClass()

	def codes(self, **lists):
		clean = clean_selection({"item_groups": [], "brands": [], "items": [], **lists})
		return [row.item_code for row in selection.product_rows(clean)]

	def test_a_group_brings_its_sub_groups(self):
		codes = self.codes(item_groups=[shop.PARENT_GROUP])
		self.assertIn(shop.SECOND, codes, "a product of the group itself")
		self.assertIn(shop.FIRST, codes, "a product of a sub-group")
		self.assertNotIn(shop.THIRD, codes)

	def test_a_sub_group_does_not_bring_its_parent(self):
		codes = self.codes(item_groups=[shop.CHILD_GROUP])
		self.assertIn(shop.FIRST, codes)
		self.assertNotIn(shop.SECOND, codes)

	def test_a_brand_and_a_single_product_are_each_enough(self):
		by_brand = set(self.codes(brands=[shop.BRAND_B]))
		self.assertTrue({shop.THIRD, shop.MODEL} <= by_brand)
		self.assertFalse({shop.FIRST, shop.SECOND} & by_brand)
		self.assertEqual(self.codes(items=[shop.SECOND]), [shop.SECOND])

	def test_the_three_lists_add_up_without_repeating_a_product(self):
		codes = self.codes(item_groups=[shop.CHILD_GROUP], brands=[shop.BRAND_A], items=[shop.FIRST, shop.THIRD])
		self.assertEqual(len(codes), len(set(codes)))
		self.assertTrue({shop.FIRST, shop.SECOND, shop.THIRD, shop.MODEL} <= set(codes))

	def test_what_the_shop_does_not_show_is_never_in_a_selection(self):
		codes = self.codes(item_groups=[shop.PARENT_GROUP], items=[shop.HIDDEN, shop.SOLD])
		self.assertNotIn(shop.HIDDEN, codes, "not published")
		self.assertNotIn(shop.SOLD, codes, "sold")

	def test_a_name_the_shop_does_not_know_holds_nothing(self):
		self.assertEqual(self.codes(item_groups=["no such group"], brands=["no such brand"], items=["no such item"]), [])
		clean = clean_selection({"items": ["no such item"]})
		self.assertEqual(selection.count_products(clean), 0)

	def test_the_products_come_by_item_group_then_name(self):
		rows = selection.product_rows(clean_selection({"item_groups": [shop.PARENT_GROUP, shop.OTHER_GROUP]}))
		keys = [(row.item_group, row.web_item_name) for row in rows]
		# the database sorts without regard to case: so does the check
		self.assertEqual(keys, sorted(keys, key=lambda key: (key[0].lower(), key[1].lower())))
		groups = [group for group, _name in keys]
		self.assertEqual(groups, sorted(groups, key=str.lower), "each group's products come together")

	def test_the_count_is_the_number_of_rows(self):
		clean = clean_selection({"item_groups": [shop.PARENT_GROUP]})
		self.assertEqual(selection.count_products(clean), len(selection.product_rows(clean)))

	def test_the_limit_is_one_above_the_cap_so_that_too_many_can_be_told_from_exactly_enough(self):
		clean = clean_selection({"item_groups": [shop.PARENT_GROUP]})
		self.assertEqual(len(selection.product_rows(clean, limit=2)), 2)

	def test_a_variant_is_not_offered_on_its_own_when_the_shop_hides_variants(self):
		from unittest import mock

		with mock.patch.object(frappe.db, "get_single_value", side_effect=lambda dt, f: 1 if f == "hide_variants" else 0):
			codes = self.codes(brands=[shop.BRAND_B])
		self.assertIn(shop.MODEL, codes)
		self.assertFalse(set(shop.variants()) & set(codes))

	# --- what the page offers to tick -------------------------------------------------------

	def test_the_groups_are_listed_in_tree_order_with_the_figures_of_their_subtree(self):
		groups = {row["name"]: row for row in selection.choices()["groups"]}
		parent, child = groups[shop.PARENT_GROUP], groups[shop.CHILD_GROUP]
		self.assertGreater(parent["count"], child["count"], "a parent answers for what its sub-groups carry")
		self.assertEqual(child["depth"], parent["depth"] + 1)
		names = [row["name"] for row in selection.choices()["groups"]]
		self.assertLess(names.index(shop.PARENT_GROUP), names.index(shop.CHILD_GROUP))

	def test_the_brands_are_listed_with_what_they_carry(self):
		brands = {row["name"]: row["count"] for row in selection.choices()["brands"]}
		self.assertEqual(brands[shop.BRAND_A], 2, "first and second: hidden and sold are not counted")

	# --- the picker ---------------------------------------------------------------------------

	def test_the_picker_finds_a_product_by_name_reference_or_brand(self):
		for text in ("Cat First", shop.FIRST.lower()[-9:], shop.BRAND_A):
			with self.subTest(text=text):
				found = {row["item_code"] for row in selection.search(text)}
				self.assertIn(shop.FIRST, found)

	def test_the_picker_hides_what_the_shop_hides_and_ignores_a_short_or_odd_text(self):
		found = {row["item_code"] for row in selection.search("Cat Hidden")} | {row["item_code"] for row in selection.search("Cat Sold")}
		self.assertFalse(found)
		for text in (None, "", "a", 5, ["Cat"], "x" * 141):
			self.assertEqual(selection.search(text), [])
