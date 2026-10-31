# //// Neoffice — added file (no upstream equivalent). Multilingual lot 5 (neoffice-maintenance#2033).
"""A buyer's cart, order, wishlist, mails and assistant in the buyer's language.

The theme is scripted (``FakeEngine``): what is a translation, and who may read it, is its business and is tested there. Here:
a line is named in the language it is read in and its saved name is never touched, a document is stamped by a request that
speaks and by no other, a mail is written in the language of the purchase, and a site with no language is served as before.
"""

import sys
import types
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from webshop.webshop.utils import localized


class FakeEngine:
	HUMAN_STATUSES = ("Reviewed", "Edited")
	MACHINE_STATUSES = ("Machine", "Stale")

	def __init__(self, language="de", explicit="de", texts=None):
		self.language, self._explicit, self.texts = language, explicit, texts or {}

	def document_language(self, doc=None):
		if self._explicit == "":  # a page of the site's own language
			return None
		return self._explicit or (doc.get("language") if doc else None) or None

	def explicit_language(self):
		return self._explicit or None

	def site_languages(self):
		return {"de": {"hreflang": "de-CH", "publication": "Publish at once"}}

	def get_translations(self, doctype, names, fieldnames, language=None):
		return {
			(name, "", field): self.texts[(name, field)]
			for name in names
			for field in fieldnames
			if (name, field) in self.texts
		}


def lines(*codes):
	return frappe._dict(
		language=None,
		items=[frappe._dict(item_code=c, item_name=f"Nom {c}", description=f"Texte {c}") for c in codes],
	)


class TestLinesAreNamedInTheLanguageTheyAreReadIn(FrappeTestCase):
	def _localize(self, doc, engine, **kwargs):
		with (
			patch.object(localized, "_engine", return_value=engine),
			patch.object(frappe, "get_all", return_value=[("A", "WEB-A")]),
		):
			return localized.localize_lines(doc, **kwargs)

	def test_a_line_gets_a_display_name_and_keeps_the_name_that_was_sold(self):
		doc = self._localize(
			lines("A", "B"),
			FakeEngine(texts={("WEB-A", "web_item_name"): "Tinte", ("WEB-A", "short_description"): "Kurz"}),
		)
		first, second = doc["items"]
		self.assertEqual((first.display_name, first.display_description), ("Tinte", "Kurz"))
		self.assertEqual(
			(first.item_name, first.description), ("Nom A", "Texte A")
		)  # what was sold, never rewritten
		self.assertNotIn(
			"display_name", second
		)  # a variant or an item with no translation keeps the line's own

	def test_nothing_is_added_in_the_sites_own_language(self):
		doc = self._localize(lines("A"), FakeEngine(explicit="", texts={("WEB-A", "web_item_name"): "Tinte"}))
		self.assertNotIn("display_name", doc["items"][0])

	def test_the_language_of_a_mail_is_given_not_read_from_a_request(self):
		doc = self._localize(
			lines("A"), FakeEngine(explicit="", texts={("WEB-A", "web_item_name"): "Tinte"}), language="de"
		)
		self.assertEqual(doc["items"][0].display_name, "Tinte")

	def test_without_the_theme_everything_is_left_alone(self):
		doc = lines("A")
		with patch.object(localized, "_engine", return_value=None):
			self.assertIs(localized.localize_lines(doc), doc)
		self.assertNotIn("display_name", doc["items"][0])
		self.assertIsNone(localized.localize_lines(None))


class TestAStampComesFromARequestThatSpeaks(FrappeTestCase):
	def _doc(self, language=None):
		return frappe._dict(
			language=language, meta=types.SimpleNamespace(has_field=lambda name: name == "language")
		)

	def test_a_german_request_stamps_the_cart_and_a_french_page_stamps_it_back(self):
		with patch.object(localized, "_engine", return_value=FakeEngine(explicit="de")):
			self.assertEqual(localized.stamp_language(self._doc()).language, "de")
		fake = FakeEngine()
		fake.explicit_language = lambda: "fr"  # a page asked with no prefix: the site's own language
		with patch.object(localized, "_engine", return_value=fake):
			self.assertEqual(localized.stamp_language(self._doc("de")).language, "fr")

	def test_a_request_that_says_nothing_leaves_the_language_as_it_was(self):
		with patch.object(localized, "_engine", return_value=FakeEngine(explicit=None)):
			self.assertEqual(localized.stamp_language(self._doc("de")).language, "de")

	def test_a_document_without_a_language_field_and_a_bench_without_the_theme_are_left_alone(self):
		bare = frappe._dict(meta=types.SimpleNamespace(has_field=lambda name: False))
		with patch.object(localized, "_engine", return_value=FakeEngine()):
			self.assertNotIn("language", localized.stamp_language(bare))
		with patch.object(localized, "_engine", return_value=None):
			self.assertEqual(localized.stamp_language(self._doc("de")).language, "de")


class TestMails(FrappeTestCase):
	def _theme(self, languages):
		units = types.ModuleType("neoffice_theme.translation.units")
		units.enabled_languages = lambda profile=None: list(languages)
		package = types.ModuleType("neoffice_theme")
		translation = types.ModuleType("neoffice_theme.translation")
		return patch.dict(
			sys.modules,
			{
				"neoffice_theme": package,
				"neoffice_theme.translation": translation,
				"neoffice_theme.translation.units": units,
			},
		)

	def test_a_mail_is_written_in_the_first_language_the_site_speaks(self):
		with self._theme(["de", "it"]):
			self.assertEqual(
				localized.mail_language("fr", "de", "it"), "de"
			)  # the site's own language is no choice
			self.assertEqual(localized.mail_language(None, "", "it"), "it")
			self.assertIsNone(localized.mail_language("fr", None))
		with self._theme([]):
			self.assertIsNone(localized.mail_language("de"))  # a site with no language writes as before

	def test_the_texts_of_a_template_are_those_of_its_kind(self):
		rows = [
			{"ref_name": "T", "fieldname": "subject", "text": "Betreff", "human": False},
			{"ref_name": "T", "fieldname": "response", "text": "<p>Text</p>", "human": False},
			{"ref_name": "T", "fieldname": "response_html", "text": "<b>Html</b>", "human": False},
		]
		with patch.object(localized, "translation_rows", return_value=rows):
			self.assertEqual(
				localized.mail_texts(frappe._dict(name="T", use_html=0), "de"), ("Betreff", "<p>Text</p>")
			)
			self.assertEqual(
				localized.mail_texts(frappe._dict(name="T", use_html=1), "de"), ("Betreff", "<b>Html</b>")
			)
		with patch.object(localized, "translation_rows", return_value=[]):
			self.assertEqual(localized.mail_texts(frappe._dict(name="T", use_html=0), "de"), (None, None))

	def test_a_link_in_a_mail_leads_to_the_page_in_the_language(self):
		self.assertEqual(
			localized.address_in("https://shop.test/products/a?x=1#w", "de"),
			"https://shop.test/de/products/a?x=1#w",
		)
		self.assertEqual(localized.address_in("https://shop.test/", "de"), "https://shop.test/de")
		self.assertEqual(localized.address_in("/cart", "de"), "/de/cart")
		self.assertEqual(localized.address_in("https://shop.test/cart", None), "https://shop.test/cart")
		self.assertIsNone(localized.address_in(None, "de"))
