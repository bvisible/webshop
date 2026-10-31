# //// Neoffice — added file (no upstream equivalent). Multilingual lot 3 (neoffice-maintenance#2031).
"""What a sitemap, a robots.txt and IndexNow say about the languages of a site.

The rules are pinned with the theme's answers scripted: whether a page is translated is the theme's business
(neoffice_theme.localized.translated_documents), and tested there. Here: a page is listed once per language it exists in
and every entry names all the others, the private pages are closed under every prefix, and a site with no additional
language is served exactly as before.
"""

import xml.dom.minidom
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.seo import language_links, robots

LANGS = {"de": {"hreflang": "de-CH", "publication": "Publish at once"}}
FACADE = "webshop.webshop.utils.localized"


def link(name, route):
	return {
		"loc": f"https://shop.example.test/{route}",
		"name": name,
		"route": route,
		"lastmod": "2026-10-31",
	}


def loc_for(route, prefix):
	return f"https://shop.example.test{prefix}/{route}"


class TestSitemapLanguages(FrappeTestCase):
	def _expand(self, links, translated, languages=LANGS):
		with (
			patch(f"{FACADE}.site_languages", return_value=languages),
			patch(f"{FACADE}.translated_documents", return_value=translated),
			patch(f"{FACADE}.source_hreflang", return_value="fr-CH"),
			patch(
				f"{FACADE}.hreflang_of",
				side_effect=lambda code: (languages.get(code) or {}).get("hreflang") or code,
			),
		):
			return language_links.expand(links, "Website Item", loc_for)

	def test_a_translated_page_is_listed_in_each_language_and_every_entry_names_the_others(self):
		out = self._expand([link("A", "a"), link("B", "b")], {"de": {"A"}})
		self.assertEqual(
			[entry["loc"] for entry in out],
			["https://shop.example.test/a", "https://shop.example.test/de/a", "https://shop.example.test/b"],
		)
		expected = [
			{"hreflang": "fr-CH", "href": "https://shop.example.test/a"},
			{"hreflang": "de-CH", "href": "https://shop.example.test/de/a"},
			{"hreflang": "x-default", "href": "https://shop.example.test/a"},
		]
		self.assertEqual(out[0]["alternates"], expected)
		self.assertEqual(out[1]["alternates"], expected)
		self.assertNotIn("alternates", out[2])  # not translated: never an alternate, never a copy

	def test_without_an_additional_language_the_links_come_back_untouched(self):
		links = [link("A", "a")]
		self.assertIs(self._expand(links, {"de": {"A"}}, languages={}), links)

	def test_the_home_page_has_a_copy_too_its_route_being_empty(self):
		# multilingual lot 4: the site's home page is a Builder page whose address is the root, "/de" in German
		home = {"loc": "https://shop.example.test/", "name": "HOME", "route": "", "lastmod": "2026-10-31"}
		out = self._expand([home], {"de": {"HOME"}})
		self.assertEqual([entry["loc"] for entry in out], ["https://shop.example.test/", "https://shop.example.test/de/"])
		self.assertEqual(out[1]["alternates"][1], {"hreflang": "de-CH", "href": "https://shop.example.test/de/"})

	def test_a_link_with_no_route_is_left_alone(self):
		entry = {"loc": "https://shop.example.test/x", "name": "A"}
		self.assertEqual(self._expand([entry], {"de": {"A"}}), [entry])

	def test_the_sitemap_templates_print_the_alternates_and_stay_well_formed(self):
		links = self._expand([link("A", "cours-et-s%C3%A9ances"), link("B", "b")], {"de": {"A"}})
		for template in ("sitemap_products.xml", "sitemap_categories.xml", "sitemap_pages.xml"):
			path = frappe.get_app_path("webshop", "www", template)
			with open(path) as handle:
				xml_text = frappe.render_template(handle.read(), {"links": links})
			document = xml.dom.minidom.parseString(xml_text.encode())
			self.assertEqual(len(document.getElementsByTagName("url")), 3, template)
			self.assertEqual(len(document.getElementsByTagName("xhtml:link")), 6, template)
			self.assertIn('xmlns:xhtml="http://www.w3.org/1999/xhtml"', xml_text)

	def test_a_sitemap_with_no_language_prints_no_alternate(self):
		path = frappe.get_app_path("webshop", "www", "sitemap_products.xml")
		with open(path) as handle:
			xml_text = frappe.render_template(handle.read(), {"links": [link("A", "a")]})
		self.assertNotIn("xhtml:link", xml_text.replace('xmlns:xhtml="http://www.w3.org/1999/xhtml"', ""))

	def test_indexnow_hears_of_the_languages_a_page_is_translated_in(self):
		with (
			patch(f"{FACADE}.page_identity", return_value=("Website Item", "A")),
			patch(f"{FACADE}.translated_languages", return_value=["de", "it"]),
		):
			self.assertEqual(
				language_links.language_urls("products/a/"), ["/de/products/a", "/it/products/a"]
			)
		with patch(f"{FACADE}.page_identity", return_value=None):
			self.assertEqual(language_links.language_urls("cart"), [])


class TestRobotsLanguages(FrappeTestCase):
	def test_the_private_pages_are_closed_under_every_prefix(self):
		with patch(f"{FACADE}.site_languages", return_value=LANGS):
			text = robots.default_robots_txt()
		for path in ("/de/cart$", "/de/cart?", "/de/checkout$", "/de/login$", "/de/my-addresses$"):
			self.assertIn(f"Disallow: {path}", text)
		self.assertNotIn("/de/app", text)  # the desk is no page of the site
		self.assertIn("Disallow: /cart$", text)

	def test_a_site_with_no_additional_language_gets_the_same_file_as_before(self):
		with patch(f"{FACADE}.site_languages", return_value={}):
			text = robots.default_robots_txt()
		self.assertNotIn("/de/", text)
