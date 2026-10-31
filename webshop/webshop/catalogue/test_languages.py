# //// Neoffice — added file (no upstream equivalent).
"""The language of a catalogue's texts (reseller catalogue, lot 5c).

The translations are the multilingual project's and live in the theme: these tests hand `translation_rows` what the theme
would answer, so they run on a site without it (the CI) and say what the catalogue does with the answer: which texts it
puts in place of the source's, when it leaves the source alone, and as whom it asks.
"""

import unittest
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.catalogue import jobs, languages


class TestTheCode(unittest.TestCase):
	def test_nothing_is_the_sites_own_language_and_a_code_is_kept(self):
		for empty in (None, ""):
			self.assertEqual(languages.clean(empty), "")
		for code in ("de", "fr", "it", "pt-BR", " de "):
			with self.subTest(code=code):
				self.assertEqual(languages.clean(code), code.strip())

	def test_what_is_not_a_language_code_is_refused(self):
		for refused in ("German", "DE", "d", "de; drop table", "../de", "de fr", 5, ["de"], {"de": 1}):
			with self.subTest(value=str(refused)), self.assertRaises(ValueError):
				languages.clean(refused)


class TestTheTexts(FrappeTestCase):
	ROWS = [
		{"ref_name": "WEB-1", "fieldname": "web_item_name", "text": "Wanderschuh", "human": False},
		{"ref_name": "WEB-1", "fieldname": "short_description", "text": "  Leicht.  ", "human": True},
		{"ref_name": "WEB-1", "fieldname": "web_long_description", "text": "   ", "human": False},
		{"ref_name": "WEB-2", "fieldname": "web_item_name", "text": "Tasche", "human": False},
	]

	def test_the_texts_are_those_of_each_product_and_an_empty_one_is_not_a_text(self):
		with mock.patch.object(languages.localized, "translation_rows", return_value=self.ROWS):
			found = languages.texts(["WEB-1", "WEB-2", "WEB-3"], "de")
		self.assertEqual(found["WEB-1"], {"web_item_name": "Wanderschuh", "short_description": "  Leicht.  "})
		self.assertEqual(found["WEB-2"], {"web_item_name": "Tasche"})
		self.assertNotIn("WEB-3", found)

	def test_nothing_is_asked_without_a_language_or_without_products(self):
		with mock.patch.object(languages.localized, "translation_rows") as asked:
			self.assertEqual(languages.texts(["WEB-1"], ""), {})
			self.assertEqual(languages.texts([], "de"), {})
		asked.assert_not_called()

	def test_the_translations_are_asked_for_the_three_texts_of_a_product_in_the_language(self):
		with mock.patch.object(languages.localized, "translation_rows", return_value=[]) as asked:
			languages.texts(["WEB-1"], "de")
		self.assertEqual(asked.call_args.args, ("Website Item", ["WEB-1"], languages.FIELDS, "de"))
		self.assertEqual(set(languages.FIELDS), {"web_item_name", "short_description", "web_long_description"})

	def test_a_job_asks_as_a_visitor_so_that_staff_s_preview_of_unreviewed_texts_does_not_leak_in(self):
		"""The theme shows System Managers the machine translations a site holds back: a job that runs as staff must
		not print them."""
		seen = []

		def ask(*args):
			seen.append(frappe.session.user)
			return []

		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		with mock.patch.object(languages.localized, "translation_rows", side_effect=ask):
			languages.texts(["WEB-1"], "de")
		self.assertEqual(seen, ["Guest"])
		self.assertEqual(frappe.session.user, "Administrator", "and the job's own identity is given back")

	def test_a_web_request_keeps_the_identity_of_its_caller(self):
		"""frappe.set_user rewrites the live session of a request: nothing is switched there."""
		seen = []
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		with mock.patch.object(frappe.local, "session_obj", object(), create=True), mock.patch.object(
			languages.localized, "translation_rows", side_effect=lambda *a: seen.append(frappe.session.user) or []
		):
			languages.texts(["WEB-1"], "de")
		self.assertEqual(seen, ["Administrator"])

	def test_the_languages_offered_are_those_the_site_enabled_with_their_names(self):
		with mock.patch.object(languages.localized, "site_languages", return_value={"de": {}, "xx-nothing": {}}):
			offered = languages.offered()
			self.assertEqual([entry["code"] for entry in offered], ["de", "xx-nothing"])
			self.assertTrue(all(entry["name"] for entry in offered), "a code with no name is its own name")
			self.assertTrue(languages.is_offered("de"))
			self.assertFalse(languages.is_offered("it"))
		with mock.patch.object(languages.localized, "site_languages", return_value={}):
			self.assertEqual(languages.offered(), [])

	def test_a_page_of_the_shop_is_reached_under_the_prefix_of_the_language(self):
		self.assertEqual(languages.in_language("https://shop.example/products/a", "de"), "https://shop.example/de/products/a")
		self.assertEqual(languages.in_language("https://shop.example/products/a", ""), "https://shop.example/products/a")
		self.assertEqual(languages.in_language("", "de"), "")


class TestTheJob(FrappeTestCase):
	def test_the_words_around_the_products_follow_the_language_a_catalogue_asks_for(self):
		self.addCleanup(setattr, frappe.local, "lang", frappe.local.lang)
		frappe.local.lang = "en"
		jobs.speak({"markup_percent": 30.0, "prices": "customers"})
		self.assertEqual(frappe.local.lang, "en", "no language asked: the owner's stays")
		jobs.speak({"markup_percent": 30.0, "prices": "customers", "language": "de"})
		self.assertEqual(frappe.local.lang, "de")


if __name__ == "__main__":
	unittest.main()
