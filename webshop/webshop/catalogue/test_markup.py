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


if __name__ == "__main__":
	unittest.main()
