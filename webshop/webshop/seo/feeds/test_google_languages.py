# //// Neoffice — added file (no upstream equivalent). Multilingual lot 5 (neoffice-maintenance#2033).
"""The Merchant Center feed of a language: German text, German addresses, the machine's mark, and what is still French."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from webshop.webshop.seo.feeds import google, google_languages

DOC = frappe._dict(name="WEB-1", item_code="A1", web_item_name="Encre", web_long_description="<p>Longue</p>")
ENTRY = {
	"id": "A1",
	"title": "Encre",
	"description": "Longue",
	"link": "https://shop.test/products/encre",
	"canonical_link": "https://shop.test/products/modele",
	"structured_description": {"digital_source_type": "trained_algorithmic_media", "content": "Longue"},
}


class TestTheItemInGerman(FrappeTestCase):
	def test_the_address_goes_under_the_language(self):
		self.assertEqual(
			google_languages.in_language("https://shop.test/products/a?x=1", "de"),
			"https://shop.test/de/products/a?x=1",
		)
		self.assertEqual(google_languages.in_language("https://shop.test/", "de"), "https://shop.test/de")

	def test_a_machine_translation_is_declared_and_a_persons_is_not(self):
		machine = {
			("WEB-1", "web_item_name"): ("Tinte", False),
			("WEB-1", "web_long_description"): ("<p>Lang</p>", False),
		}
		out = google_languages.localize_entry(ENTRY, DOC, "de", machine)
		self.assertEqual((out["title"], out["description"]), ("Tinte", "Lang"))
		self.assertEqual(out["link"], "https://shop.test/de/products/encre")
		self.assertEqual(out["canonical_link"], "https://shop.test/de/products/modele")
		self.assertEqual(out["structured_title"]["digital_source_type"], "trained_algorithmic_media")
		self.assertEqual(out["structured_description"]["content"], "Lang")
		people = {
			("WEB-1", "web_item_name"): ("Tinte", True),
			("WEB-1", "web_long_description"): ("<p>Lang</p>", True),
		}
		out = google_languages.localize_entry(ENTRY, DOC, "de", people)
		self.assertNotIn("structured_title", out)
		self.assertNotIn(
			"structured_description", out
		)  # the French flag said the French text was a model's: not this one
		self.assertEqual(ENTRY["link"], "https://shop.test/products/encre")  # the French item is not changed

	def test_a_product_with_no_long_text_sends_its_short_one_and_then_its_name(self):
		texts = {("WEB-1", "web_item_name"): ("Tinte", True), ("WEB-1", "short_description"): ("Kurz", False)}
		out = google_languages.localize_entry(ENTRY, DOC, "de", texts)
		self.assertEqual(out["description"], "Kurz")
		self.assertEqual(out["structured_description"]["content"], "Kurz")
		out = google_languages.localize_entry(ENTRY, DOC, "de", {("WEB-1", "web_item_name"): ("Tinte", True)})
		self.assertEqual(out["description"], "Tinte")


class TestReadiness(FrappeTestCase):
	def _readiness(self, sent, untranslated, pages=()):
		with patch.object(google_languages.localized, "untranslated_legal_pages", return_value=list(pages)):
			return google_languages.readiness("de", sent, untranslated)

	def test_a_language_whose_journey_is_translated_is_ready(self):
		self.assertEqual(self._readiness(38, 0), [])

	def test_what_is_still_in_the_site_s_language_is_named(self):
		self.assertEqual(len(self._readiness(0, 0)), 1)  # no product
		missing = self._readiness(30, 8, pages=["terms-conditions", "privacy-policy"])
		self.assertEqual(len(missing), 2)
		self.assertIn("8", missing[0])
		self.assertIn("terms-conditions", missing[1])

	def test_a_language_the_shop_has_no_strings_for_is_not_ready(self):
		with patch.object(google_languages.localized, "untranslated_legal_pages", return_value=[]):
			self.assertEqual(len(google_languages.readiness("zz", 5, 0)), 1)

	def test_the_report_says_ready_or_what_is_missing(self):
		ready = frappe._dict(
			url="https://shop.test/feeds/google-de.xml",
			sent=3,
			left_out={"not_translated": 2},
			refusal=None,
			missing=[],
			ready=True,
		)
		lines = google_languages.describe([ready], "TOKEN")
		self.assertEqual(lines[0], "https://shop.test/feeds/google-de.xml?token=TOKEN")
		self.assertIn("  Ready for Merchant Center", lines)
		self.assertTrue(any("not translated" in line for line in lines))
		not_ready = frappe._dict(
			**{**ready, "ready": False, "missing": ["legal pages still in the site's language: cgv"]}
		)
		self.assertTrue(
			any(line.startswith("  Not ready") for line in google_languages.describe([not_ready], "T"))
		)


class TestTheRoute(FrappeTestCase):
	def test_the_feed_of_a_language_has_a_route_and_nothing_else_does(self):
		for path, answer in (
			("feeds/google.xml", True),
			("feeds/google-de.xml", True),
			("feeds/google-pt-BR.xml", True),
			("feeds/google-../x.xml", False),
			("feeds/google-german.xml", False),
			("feeds/google-de.xml/x", False),
		):
			self.assertEqual(google.FeedRenderer(path, 200).can_render(), answer, path)

	def test_only_a_language_the_site_speaks_is_handed_out(self):
		with (
			patch.object(google_languages.localized, "site_languages", return_value={"de": {}}),
			patch("os.path.exists", return_value=True),
		):
			self.assertTrue(google_languages.served_file("shop", "de").endswith("google-shop-de.xml"))
			self.assertIsNone(google_languages.served_file("shop", "it"))
