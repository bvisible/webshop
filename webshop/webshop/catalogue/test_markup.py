# //// Neoffice — added file (no upstream equivalent).
"""The reseller's selling price: markup, rounding, VAT.

Pure functions: no site, no fixture. They run anywhere, which is why they are
blocking in CI from their first push.
"""

import unittest
from decimal import Decimal

from webshop.webshop.catalogue import markup


class TestSellingPrice(unittest.TestCase):
	def test_a_markup_of_thirty_percent_on_a_round_price(self):
		self.assertEqual(markup.selling_price(100, 30, "none"), Decimal("130.00"))

	def test_the_default_rounding_is_to_five_centimes(self):
		# 99.80 + 30 % = 129.74, and 129.74 is closest to 129.75
		self.assertEqual(markup.selling_price("99.80", 30), Decimal("129.75"))

	def test_half_a_step_rounds_up(self):
		# 10.025 / 0.05 = 200.5: the shop rounds a half up, never to the even neighbour
		self.assertEqual(markup.selling_price("10.025", 0, "0.05"), Decimal("10.05"))

	def test_rounding_to_ten_centimes(self):
		self.assertEqual(markup.selling_price("99.80", 30, "0.10"), Decimal("129.70"))

	def test_rounding_to_the_franc(self):
		self.assertEqual(markup.selling_price("99.80", 30, "1.00"), Decimal("130.00"))
		self.assertEqual(markup.selling_price("99.20", 30, "1.00"), Decimal("129.00"))

	def test_no_rounding_keeps_the_centimes(self):
		self.assertEqual(markup.selling_price("99.80", 30, "none"), Decimal("129.74"))
		self.assertEqual(markup.selling_price("129.745", 0, "none"), Decimal("129.75"))

	def test_a_float_sum_carries_no_binary_noise(self):
		# 0.1 + 0.2 is 0.30000000000000004 as a float
		self.assertEqual(markup.selling_price(0.1 + 0.2, 0, "none"), Decimal("0.30"))

	def test_vat_is_added_after_the_markup_when_asked(self):
		# 100 + 30 % = 130, + 8.1 % = 140.53, rounded to 140.55
		self.assertEqual(
			markup.selling_price(100, 30, "0.05", vat_rate="8.1", include_vat=True), Decimal("140.55")
		)

	def test_vat_is_ignored_when_prices_are_shown_without_it(self):
		self.assertEqual(
			markup.selling_price(100, 30, "0.05", vat_rate="8.1", include_vat=False), Decimal("130.00")
		)

	def test_a_markup_may_be_a_decimal_or_a_numeric_string(self):
		self.assertEqual(markup.selling_price(100, "12.5", "none"), Decimal("112.50"))
		self.assertEqual(markup.selling_price(100, Decimal("12.5"), "none"), Decimal("112.50"))

	def test_no_cost_gives_no_price(self):
		self.assertIsNone(markup.selling_price(None, 30))

	def test_a_free_item_stays_free(self):
		self.assertEqual(markup.selling_price(0, 30), Decimal("0.00"))

	def test_a_negative_cost_is_refused(self):
		with self.assertRaises(ValueError):
			markup.selling_price(-1, 30)


class TestWhatTheCallerMayChoose(unittest.TestCase):
	def test_the_markup_stays_between_zero_and_three_hundred_percent(self):
		self.assertEqual(markup.clean_markup_percent(0), Decimal("0"))
		self.assertEqual(markup.clean_markup_percent(300), Decimal("300"))
		for out_of_range in (-0.01, 300.01, -50, 1000):
			with self.subTest(value=out_of_range), self.assertRaises(ValueError):
				markup.clean_markup_percent(out_of_range)

	def test_a_markup_that_is_not_a_number_is_refused(self):
		for not_a_number in (None, "", "abc", "30 %", float("nan"), float("inf"), "NaN", "Infinity"):
			with self.subTest(value=not_a_number), self.assertRaises(ValueError):
				markup.clean_markup_percent(not_a_number)

	def test_the_rounding_comes_from_a_closed_list(self):
		for allowed in markup.ROUNDINGS:
			markup.selling_price(100, 10, allowed)
		for refused in ("0.01", "5", "", None, "0.05; drop table"):
			with self.subTest(value=refused), self.assertRaises(ValueError):
				markup.selling_price(100, 10, refused)

	def test_a_vat_rate_outside_zero_and_a_hundred_is_refused(self):
		for refused in (-1, 101, "abc", None):
			with self.subTest(value=refused), self.assertRaises(ValueError):
				markup.selling_price(100, 10, "0.05", vat_rate=refused, include_vat=True)


def rule(kind, target, percent):
	return {"rule_type": kind, "target": target, "markup_percent": percent}


class TestCleanRules(unittest.TestCase):
	"""What a reseller may write as a markup of their own: a closed list of kinds, a name, a percentage."""

	def test_nothing_is_no_rule(self):
		for empty in (None, "", []):
			self.assertEqual(markup.clean_rules(empty), [])

	def test_a_rule_is_kept_with_its_name_trimmed_and_its_percentage_a_number(self):
		clean = markup.clean_rules([rule("Item Group", "  Shoes ", "35"), rule("Brand", "Alpine", 12.5), rule("Item", "SKU-1", 0)])
		self.assertEqual(
			clean, [rule("Item Group", "Shoes", 35.0), rule("Brand", "Alpine", 12.5), rule("Item", "SKU-1", 0.0)]
		)

	def test_the_kind_comes_from_a_closed_list(self):
		for refused in ("item", "Customer", "", None, "Item Group; drop"):
			with self.subTest(kind=refused), self.assertRaises(markup.RuleRefused) as caught:
				markup.clean_rules([rule(refused, "x", 10)])
			self.assertEqual((caught.exception.reason, caught.exception.index), ("bad_kind", 0))

	def test_a_name_is_not_empty_nor_long_nor_a_number(self):
		for refused in ("", "   ", None, 12, "x" * (markup.MAX_TARGET + 1)):
			with self.subTest(target=refused), self.assertRaises(markup.RuleRefused) as caught:
				markup.clean_rules([rule("Brand", refused, 10)])
			self.assertEqual(caught.exception.reason, "bad_target")

	def test_a_percentage_outside_zero_and_three_hundred_is_refused_and_a_price_never_enters(self):
		for refused in (-1, 301, "abc", None, "", float("nan"), "1e999"):
			with self.subTest(percent=refused), self.assertRaises(markup.RuleRefused) as caught:
				markup.clean_rules([rule("Brand", "A", refused)])
			self.assertEqual(caught.exception.reason, "bad_percent")

	def test_a_target_has_one_rule_and_the_row_of_the_second_is_named(self):
		with self.assertRaises(markup.RuleRefused) as caught:
			markup.clean_rules([rule("Brand", "A", 10), rule("Item Group", "A", 20), rule("Brand", " A", 30)])
		self.assertEqual((caught.exception.reason, caught.exception.index), ("duplicate", 2))
		# the same name for two different kinds is two targets
		self.assertEqual(len(markup.clean_rules([rule("Brand", "A", 10), rule("Item Group", "A", 20)])), 2)

	def test_the_number_of_rules_is_bounded(self):
		many = [rule("Item", f"SKU-{number}", 5) for number in range(markup.MAX_RULES + 1)]
		with self.assertRaises(markup.RuleRefused) as caught:
			markup.clean_rules(many)
		self.assertEqual(caught.exception.reason, "too_many")
		self.assertEqual(len(markup.clean_rules(many[: markup.MAX_RULES])), markup.MAX_RULES)

	def test_what_is_not_a_list_of_rules_is_refused(self):
		for refused in ("Brand", {"rule_type": "Brand"}, 5, ["Brand"], [None]):
			with self.subTest(value=refused), self.assertRaises(markup.RuleRefused):
				markup.clean_rules(refused)


class TestMarkups(unittest.TestCase):
	"""The most specific rule that names a product decides its markup."""

	TREE = {"Trail": ["Trail", "Shoes", "All"], "Shoes": ["Shoes", "All"], "Bags": ["Bags", "All"]}

	def book(self, *rules, default=10.0):
		return markup.Markups(list(rules), default, lambda group: self.TREE.get(group, [group] if group else []))

	def test_nothing_named_takes_the_catalogues_markup(self):
		self.assertEqual(self.book().percent(["SKU"], "Trail", "Alpine"), 10.0)
		self.assertEqual(self.book(rule("Brand", "Other", 99)).percent(["SKU"], "Trail", "Alpine"), 10.0)

	def test_a_rule_of_zero_is_a_rule_not_a_missing_one(self):
		self.assertEqual(self.book(rule("Brand", "Alpine", 0)).percent(["SKU"], "Trail", "Alpine"), 0.0)

	def test_a_brand_rule_applies_to_the_products_of_the_brand(self):
		self.assertEqual(self.book(rule("Brand", "Alpine", 25)).percent(["SKU"], "Bags", "Alpine"), 25.0)

	def test_a_category_rule_reaches_the_categories_under_it(self):
		book = self.book(rule("Item Group", "Shoes", 30))
		self.assertEqual(book.percent(["SKU"], "Trail", None), 30.0)
		self.assertEqual(book.percent(["SKU"], "Shoes", None), 30.0)
		self.assertEqual(book.percent(["SKU"], "Bags", None), 10.0)

	def test_the_closest_category_wins(self):
		book = self.book(rule("Item Group", "Shoes", 30), rule("Item Group", "Trail", 45))
		self.assertEqual(book.percent(["SKU"], "Trail", None), 45.0)
		self.assertEqual(book.percent(["SKU"], "Shoes", None), 30.0)

	def test_a_category_beats_a_brand_and_a_product_beats_both(self):
		book = self.book(rule("Brand", "Alpine", 5), rule("Item Group", "Shoes", 30), rule("Item", "SKU-1", 70))
		self.assertEqual(book.percent(["SKU-2"], "Trail", "Alpine"), 30.0)
		self.assertEqual(book.percent(["SKU-1"], "Trail", "Alpine"), 70.0)
		self.assertEqual(book.percent(["SKU-2"], "Bags", "Alpine"), 5.0)

	def test_a_rule_on_a_model_covers_its_variants_and_a_rule_on_the_variant_wins(self):
		book = self.book(rule("Item", "MODEL", 40), rule("Item", "MODEL-RED", 55))
		self.assertEqual(book.percent(["MODEL-BLUE", "MODEL"], "Trail", None), 40.0)
		self.assertEqual(book.percent(["MODEL-RED", "MODEL"], "Trail", None), 55.0)

	def test_a_product_with_no_category_or_brand_is_not_an_error(self):
		self.assertEqual(self.book(rule("Brand", "Alpine", 25)).percent(["SKU"], None, None), 10.0)
		self.assertEqual(self.book().percent([], None, None), 10.0)

	def test_a_loop_in_the_tree_ends(self):
		looped = markup.Markups([rule("Item Group", "A", 20)], 10.0, lambda group: ["B", "A", "B"] if group else [])
		self.assertEqual(looped.percent(["SKU"], "B", None), 20.0)

	def test_how_many_rules_there_are(self):
		self.assertEqual(len(self.book()), 0)
		self.assertEqual(len(self.book(rule("Brand", "A", 1), rule("Item", "B", 2))), 2)

	def test_a_price_is_marked_up_by_the_percentage_of_its_product(self):
		book = self.book(rule("Item Group", "Shoes", 30))
		trail = markup.selling_price(100, book.percent(["SKU"], "Trail", None), "none")
		bag = markup.selling_price(100, book.percent(["SKU"], "Bags", None), "none")
		self.assertEqual((trail, bag), (Decimal("130.00"), Decimal("110.00")))


if __name__ == "__main__":
	unittest.main()
