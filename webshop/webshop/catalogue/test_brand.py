# //// Neoffice — added file (no upstream equivalent).
"""What a reseller may write in the settings of their brand, and the ink that reads on their colour.

Pure functions, no site: every field is checked here, once, for the doctype and for the page alike.
"""

import unittest

from webshop.webshop.catalogue import brand


def refused(values):
	with unittest.TestCase().assertRaises(brand.BrandRefused) as caught:
		brand.clean_brand(values)
	return caught.exception.field, caught.exception.reason


class TestCleanBrand(unittest.TestCase):
	def test_what_is_valid_comes_back_normalised(self):
		clean = brand.clean_brand(
			{
				"brand_name": "  Alpine   Distribution SA ",
				"primary_colour": "#0B6E4F",
				"default_markup_percent": "30",
				"price_rounding": "0.05",
				"price_display": "Including VAT",
				"vat_rate": "8.1",
				"contact_email": "orders@alpine-distribution.example",
				"contact_website": "www.alpine-distribution.example",
			}
		)
		self.assertEqual(clean["brand_name"], "Alpine Distribution SA")
		self.assertEqual(clean["primary_colour"], "#0b6e4f")
		self.assertEqual(clean["default_markup_percent"], 30.0)
		self.assertEqual(clean["vat_rate"], 8.1)
		self.assertEqual(clean["contact_website"], "www.alpine-distribution.example")

	def test_only_the_fields_sent_come_back_and_the_others_are_ignored(self):
		clean = brand.clean_brand({"brand_name": "A", "customer": "Somebody Else", "owner": "x", "logo": "/y"})
		self.assertEqual(clean, {"brand_name": "A"})

	def test_an_address_may_run_over_a_few_lines(self):
		clean = brand.clean_brand({"contact_address": "Rue du Rhône 12\n1950 Sion\nSuisse"})
		self.assertEqual(clean["contact_address"], "Rue du Rhône 12\n1950 Sion\nSuisse")

	def test_a_text_that_is_too_long_is_refused(self):
		self.assertEqual(refused({"brand_name": "x" * 81}), ("brand_name", "too_long"))
		self.assertEqual(refused({"footer_text": "x" * 141}), ("footer_text", "too_long"))
		self.assertEqual(refused({"contact_address": "a\nb\nc\nd\ne"}), ("contact_address", "too_long"))

	def test_a_control_character_is_refused(self):
		self.assertEqual(refused({"brand_name": "Alpine\x00"}), ("brand_name", "control_characters"))
		self.assertEqual(refused({"contact_address": "Rue\x07 12"}), ("contact_address", "control_characters"))

	def test_a_colour_is_six_hexadecimal_digits(self):
		for bad in ("red", "#fff", "0b6e4f", "#0b6e4g", "#0b6e4f00", "url(x)", "", None):
			with self.subTest(value=bad):
				self.assertEqual(refused({"primary_colour": bad}), ("primary_colour", "bad_colour"))

	def test_an_email_is_one_address(self):
		for bad in ("not an address", "a@b", "a@b.c, d@e.f", "<a@b.cd>", 'a"b@c.de'):
			with self.subTest(value=bad):
				self.assertEqual(refused({"contact_email": bad}), ("contact_email", "bad_email"))

	def test_a_website_is_a_web_address_and_nothing_that_runs(self):
		for ok in ("https://www.example.ch", "http://example.ch/shop?a=1", "example.ch", "www.example.ch/fr"):
			with self.subTest(value=ok):
				self.assertEqual(brand.clean_brand({"contact_website": ok})["contact_website"], ok)
		for bad in ("javascript:alert(1)", "https://exa mple.ch", 'https://example.ch"onload="x', "ftp://example.ch", "localhost"):
			with self.subTest(value=bad):
				self.assertEqual(refused({"contact_website": bad}), ("contact_website", "bad_website"))

	def test_the_markup_the_rounding_and_the_vat_follow_the_pricing_rules(self):
		self.assertEqual(refused({"default_markup_percent": "301"}), ("default_markup_percent", "bad_markup"))
		self.assertEqual(refused({"default_markup_percent": "x"}), ("default_markup_percent", "bad_markup"))
		self.assertEqual(refused({"price_rounding": "0.01"}), ("price_rounding", "bad_rounding"))
		self.assertEqual(refused({"price_display": "Whatever"}), ("price_display", "bad_display"))
		self.assertEqual(refused({"vat_rate": "101"}), ("vat_rate", "bad_vat"))

	def test_an_empty_optional_text_is_allowed(self):
		clean = brand.clean_brand({"contact_phone": "", "footer_text": None, "vat_number": "   "})
		self.assertEqual(clean, {"contact_phone": "", "footer_text": "", "vat_number": ""})


class TestReadableInk(unittest.TestCase):
	def test_a_dark_colour_gets_white_ink(self):
		self.assertEqual(brand.readable_ink("#0b6e4f"), "#ffffff")
		self.assertEqual(brand.readable_ink("#1f2933"), "#ffffff")

	def test_a_light_colour_gets_dark_ink(self):
		self.assertEqual(brand.readable_ink("#ffd400"), "#111111")
		self.assertEqual(brand.readable_ink("#f5f5f5"), "#111111")

	def test_the_middle_greys_take_whichever_ink_reads_better(self):
		# #808080 is 3.9:1 against white and 4.8:1 against the dark ink
		self.assertEqual(brand.readable_ink("#808080"), "#111111")

	def test_the_contrast_of_the_chosen_ink_is_reported(self):
		self.assertGreaterEqual(brand.contrast_ratio("#0b6e4f", "#ffffff"), 4.5)
		self.assertAlmostEqual(brand.contrast_ratio("#000000", "#ffffff"), 21.0, places=1)


if __name__ == "__main__":
	unittest.main()
