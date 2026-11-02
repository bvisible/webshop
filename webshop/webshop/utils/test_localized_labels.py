# //// Neoffice — added file (no upstream equivalent).
"""The name of a category or a brand as the visitor reads it (multilingual lot 14).

The shop printed these names through `_()` alone, the interface's own translation list, so an added language never reached the
sidebar's facets, the tiles, the product page nor the category page: a German visitor read French category names. They go
through `webshop_label` now: the translation of content, else the interface's, else the name.

The helper's tests need no site (the theme is replaced by a stand-in); the templates are read as text, the way
`TestEveryOfferReadsSold` reads the modules, because the rule that matters is a negative one: **a label is only ever printed**.
Used as a value to filter on, link to or look up it would break the catalogue in every language but the first.
"""

import re
import unittest
from pathlib import Path
from unittest.mock import patch

import frappe

from webshop.webshop.utils import localized

APP = Path(__file__).resolve().parents[2]
TEMPLATES = APP / "templates"
LOCALIZED = "webshop.webshop.utils.localized"


class FakeTheme:
	"""What the theme answers: `found` = {name: translation} for the records a visitor may read."""

	def __init__(self, found=None, fail=False):
		self.found = found or {}
		self.fail = fail
		self.bulk_reads = []
		self.single_reads = []

	def get_translations(self, doctype, names, fieldnames, language=None):
		if self.fail:
			raise RuntimeError("the theme is down")
		self.bulk_reads.append((doctype, tuple(names), tuple(fieldnames), language))
		return {(name, "", "name"): self.found[name] for name in names if name in self.found}

	def localize_value(self, doctype, name, fieldname, default=None):
		self.single_reads.append((doctype, name))
		return self.found.get(name, default)


def interface(text, *args, **kwargs):
	return f"UI:{text}"


class LabelTestCase(unittest.TestCase):
	NAMES = ["Produits", "Cours et séances", "Lieux et hébergement"]

	def setUp(self):
		frappe.local.cache.pop("webshop_label_maps", None)
		self.addCleanup(frappe.local.cache.pop, "webshop_label_maps", None)

	def reading(self, found=None, language="de", names=None, fail=False):
		"""Patches in place: the theme, the language of the request, the interface's list and the table of names."""
		theme = FakeTheme(found, fail=fail)
		for patcher in (
			patch.object(localized, "_engine", return_value=theme),
			patch.object(localized, "content_language", return_value=language),
			patch("frappe._", side_effect=interface),
			patch("frappe.get_all", return_value=list(names if names is not None else self.NAMES)),
			patch("frappe.log_error"),
		):
			patcher.start()
			self.addCleanup(patcher.stop)
		return theme


class TestTheLabelAVisitorReads(LabelTestCase):
	def test_a_translation_of_content_wins_over_the_interface_s_list_which_wins_over_the_name(self):
		self.reading({"Produits": "Produkte"})
		self.assertEqual(localized.webshop_label("Item Group", "Produits"), "Produkte")
		# nothing in the content: what the interface's list says (Frappe's Translation), the way it was printed before
		self.assertEqual(localized.webshop_label("Item Group", "Cours et séances"), "UI:Cours et séances")
		# a surface that never went through _() keeps the stored name
		self.assertEqual(localized.webshop_label("Item Group", "Cours et séances", interface=False), "Cours et séances")
		# and the translation wins on it too
		self.assertEqual(localized.webshop_label("Item Group", "Produits", interface=False), "Produkte")

	def test_in_the_site_s_own_language_nothing_changes_and_the_theme_is_not_asked(self):
		theme = self.reading({"Produits": "Produkte"}, language=None)
		self.assertEqual(localized.webshop_label("Item Group", "Produits"), "UI:Produits")
		self.assertEqual(localized.webshop_label("Item Group", "Produits", interface=False), "Produits")
		self.assertEqual(theme.bulk_reads + theme.single_reads, [])

	def test_without_the_theme_the_shop_prints_what_it_always_printed(self):
		self.reading({"Produits": "Produkte"})
		with patch.object(localized, "_engine", return_value=None):
			self.assertEqual(localized.webshop_label("Item Group", "Produits"), "UI:Produits")
			self.assertEqual(localized.webshop_label("Brand", "Acme", interface=False), "Acme")

	def test_a_translation_that_says_the_name_is_no_translation(self):
		self.reading({"Produits": "Produits"})
		self.assertEqual(localized.webshop_label("Item Group", "Produits"), "UI:Produits")

	def test_no_name_prints_nothing(self):
		theme = self.reading({"Produits": "Produkte"})
		for name in ("", None):
			self.assertEqual(localized.webshop_label("Item Group", name), "")
		self.assertEqual(theme.bulk_reads, [])

	def test_a_page_of_labels_costs_one_read_of_the_theme_not_one_per_label(self):
		theme = self.reading({"Produits": "Produkte"})
		for _tile in range(25):
			for name in self.NAMES:
				localized.webshop_label("Item Group", name)
		self.assertEqual(len(theme.bulk_reads), 1)
		self.assertEqual(theme.single_reads, [])
		self.assertEqual(theme.bulk_reads[0][0:3:2], ("Item Group", ("name",)))
		self.assertEqual(sorted(theme.bulk_reads[0][1]), sorted(self.NAMES))

	def test_the_read_is_kept_by_language_and_by_doctype(self):
		theme = self.reading({"Produits": "Produkte"})
		localized.webshop_label("Item Group", "Produits")
		localized.webshop_label("Brand", "Produits")
		self.assertEqual([read[0] for read in theme.bulk_reads], ["Item Group", "Brand"])
		with patch.object(localized, "content_language", return_value="it"):
			localized.webshop_label("Item Group", "Produits")
		self.assertEqual([read[3] for read in theme.bulk_reads], ["de", "de", "it"])

	def test_a_doctype_with_too_many_records_is_read_name_by_name_never_all_at_once(self):
		theme = self.reading({"Produits": "Produkte"})
		with patch.object(localized, "LABEL_MAP_LIMIT", 2):
			self.assertEqual(localized.webshop_label("Item Group", "Produits"), "Produkte")
		self.assertEqual(theme.bulk_reads, [])
		self.assertEqual(theme.single_reads, [("Item Group", "Produits")])

	def test_a_failure_of_the_theme_costs_the_translation_never_the_page(self):
		self.reading({"Produits": "Produkte"}, fail=True)
		self.assertEqual(localized.webshop_label("Item Group", "Produits"), "UI:Produits")
		self.assertEqual(localized.webshop_label("Item Group", "Produits", interface=False), "Produits")
		frappe.log_error.assert_called_once()  # logged once: the failure is remembered for the request

	def test_the_name_a_label_stands_for_is_never_changed(self):
		self.reading({"Produits": "Produkte"})
		rows = [frappe._dict(name="Produits"), {"name": "Cours et séances"}, {"title": "no name"}, frappe._dict(name="")]
		self.assertIs(localized.label_rows("Item Group", rows), rows)
		self.assertEqual([row.get("name") for row in rows], ["Produits", "Cours et séances", None, ""])
		self.assertEqual([row.get("label") for row in rows], ["Produkte", "Cours et séances", None, None])
		# a surface that reads the label under another key
		other = [{"name": "Produits"}]
		localized.label_rows("Item Group", other, into="shown")
		self.assertEqual(other, [{"name": "Produits", "shown": "Produkte"}])
		self.assertEqual(localized.label_rows("Item Group", None), None)

	def test_a_row_label_does_not_go_through_the_interface_s_list(self):
		"""A card that printed the stored name keeps it: only the surfaces that used _() read Frappe's list."""
		self.reading({})
		rows = [{"name": "Produits"}]
		localized.label_rows("Item Group", rows)
		self.assertEqual(rows[0]["label"], "Produits")


class TestTheMethodIsRegistered(unittest.TestCase):
	def test_templates_can_call_webshop_label(self):
		hooks = (APP / "hooks.py").read_text(encoding="utf-8")
		self.assertIn(f'"{LOCALIZED}.webshop_label"', hooks)
		self.assertTrue(callable(getattr(localized, "webshop_label")))


# What each template prints through the helper, at the least: the visible names of a tile, a facet, a page, a pill, a carousel.
SURFACES = {
	"includes/product_card.html": {"Item Group": 4, "Brand": 1},
	"includes/macros.html": {"Item Group": 2, "Brand": 2},
	"generators/item/item_details.html": {"Item Group": 1, "Brand": 1},
	"generators/item_group.html": {"Item Group": 1},
	"includes/sub_categories.html": {"Item Group": 1},
	"includes/brand_carousel.html": {"Brand": 2},
	"includes/brand_intro.html": {"Brand": 1},
}
# What these templates printed before: a stored name, or a name through _() alone. None of them may come back.
OLD_WAYS = {
	"includes/product_card.html": [r"\{\{\s*_\(item\.item_group\)", r"\{\{\s*item\.item_group\s*\|\s*e", r"\{\{\s*item\.brand\s*\|\s*e"],
	"includes/macros.html": [r"\{\{\s*_\(group\.name\)", r"_\(value\.name if item_field\.fieldname == 'brand' else value\)"],
	"generators/item/item_details.html": [r"\{\{\s*_\(doc\.brand\)", r"\{\{\s*_\(doc\.item_group\)"],
	"generators/item_group.html": [r"\{\{\s*_\(item_group_name\)"],
	"includes/sub_categories.html": [r"\{\{\s*category\.name\s*\|\s*e"],
	"includes/brand_carousel.html": [r"\{\{\s*_\(brand\.brand_name\)", r'alt="\{\{\s*brand\.brand_name\s*\}\}"'],
}
# An attribute a script, a link or a lookup reads as the thing itself: a label there would filter on a translation.
VALUE_ATTRIBUTES = ("data-value", "data-filter-value", "data-filter-name", "data-name", "data-item-code", "id", "for", "href", "value", "name")


def read(relative):
	return (TEMPLATES / relative).read_text(encoding="utf-8")


class TestEveryNameTheShopPrintsGoesThroughTheLabel(unittest.TestCase):
	def test_each_surface_prints_its_names_through_the_helper(self):
		for relative, wanted in SURFACES.items():
			text = read(relative)
			for doctype, at_least in wanted.items():
				found = len(re.findall(r'webshop_label\(\s*"%s"' % doctype, text))
				with self.subTest(template=relative, doctype=doctype):
					self.assertGreaterEqual(found, at_least)

	def test_the_old_ways_of_printing_a_category_or_a_brand_do_not_come_back(self):
		for relative, patterns in OLD_WAYS.items():
			text = read(relative)
			# a Jinja comment may quote the old line
			text = re.sub(r"\{#.*?#\}", "", text, flags=re.DOTALL)
			for pattern in patterns:
				with self.subTest(template=relative, old=pattern):
					self.assertIsNone(re.search(pattern, text), relative)

	def test_a_label_is_never_a_value_a_link_or_an_identifier(self):
		forbidden = re.compile(r'(?:%s)\s*=\s*"[^"]*webshop_label' % "|".join(re.escape(a) for a in VALUE_ATTRIBUTES))
		for relative in SURFACES:
			for number, line in enumerate(read(relative).splitlines(), start=1):
				with self.subTest(template=relative, line=number):
					self.assertIsNone(forbidden.search(line), line.strip())

	def test_the_facets_still_filter_on_the_stored_name(self):
		macros = read("includes/macros.html")
		for fragment in (
			'data-value="{{ group.name }}"',
			'data-filter-value="{{ group.name }}"',
			'id="{{ group.name }}"',
			'data-filter-value="{{ value.name if item_field.fieldname == \'brand\' else value }}"',
		):
			with self.subTest(fragment=fragment):
				self.assertIn(fragment, macros)

	def test_a_translated_label_is_escaped_where_it_is_printed(self):
		"""Content a model wrote or a person typed: never trusted as markup."""
		for relative in SURFACES:
			for line in read(relative).splitlines():
				if "webshop_label(" in line and "{{" in line and "data-label" not in line:
					with self.subTest(template=relative, line=line.strip()):
						self.assertRegex(line, r"webshop_label\([^}]*\)\s*\)?\s*\|\s*e")


class TestTheCatalogueSearchesAndNamesWhatTheVisitorReads(unittest.TestCase):
	def test_the_facet_lookup_box_matches_the_translated_label_as_well_as_the_name(self):
		script = (APP / "public" / "js" / "product_ui" / "views.js").read_text(encoding="utf-8")
		self.assertRegex(script, r"\$el\.attr\('data-label'\)")
		self.assertRegex(script, r"value\.includes\(keyword\)\s*\|\|\s*label\.includes\(keyword\)")

	def test_the_active_filter_chips_say_the_facet_s_label_first(self):
		script = (APP / "public" / "js" / "product_ui" / "views.js").read_text(encoding="utf-8")
		self.assertRegex(script, r"closest\('\[data-label\]'\)\.attr\('data-label'\)")

	def test_the_sub_category_pills_the_script_draws_say_the_label_the_server_gives(self):
		script = (APP / "public" / "js" / "product_ui" / "views.js").read_text(encoding="utf-8")
		self.assertRegex(script, r"category\.label\s*\|\|\s*category\.name")

	def test_the_category_page_s_cards_say_the_label_and_filter_on_the_stored_name(self):
		card = (APP / "www" / "shop-by-category" / "category_card_section.html").read_text(encoding="utf-8")
		self.assertIn('row.get("label") or row.name', card)
		self.assertIn('row.get("value") or row.name', card)
		index = (APP / "www" / "shop-by-category" / "index.py").read_text(encoding="utf-8")
		self.assertIn('label_rows("Item Group", kept)', index)
		self.assertIn('label_rows(doctype, rows)', index)

	def test_the_sub_categories_the_listing_offers_carry_their_label(self):
		source = (APP / "webshop" / "product_data_engine" / "listing_context.py").read_text(encoding="utf-8")
		self.assertIn('label_rows("Item Group", shown)', source)


class TestRenderedThroughTheEnvironment(unittest.TestCase):
	"""The Jinja environment with the shop's methods: only where a site is up (the helper's own tests need none)."""

	@classmethod
	def setUpClass(cls):
		if not hasattr(frappe, "render_template") or not getattr(frappe.local, "site", None):
			raise unittest.SkipTest("needs a site: the helper's tests above run without one")

	def setUp(self):
		frappe.local.cache.pop("webshop_label_maps", None)
		self.addCleanup(frappe.local.cache.pop, "webshop_label_maps", None)

	def test_the_category_page_s_cards_print_the_label_and_keep_the_name_as_their_value(self):
		rows = [
			frappe._dict(name="Produits", label="Produkte", route="all-products?x=1", count=3),
			frappe._dict(name="Cours", route="cours"),
			frappe._dict(name="Second-hand", value="Second-hand", label="Gebraucht", route="occasions"),
		]
		html = frappe.render_template(
			"webshop/www/shop-by-category/category_card_section.html", {"data": rows, "type": "item_group"}
		)
		self.assertIn('data-name="Produkte" data-value="Produits"', html)
		self.assertIn('data-name="Cours" data-value="Cours"', html)
		self.assertIn('data-name="Gebraucht" data-value="Second-hand"', html)
		self.assertIn(">Produkte<", html)

	def test_the_pills_are_drawn_with_the_label_by_the_registered_method(self):
		with patch.object(localized, "label_map", return_value={"Produits": "Produkte & Co <b>"}):
			html = frappe.render_template(
				"webshop/templates/includes/sub_categories.html",
				{"sub_categories": [frappe._dict(name="Produits", route="produits")]},
			)
		self.assertIn('href="/produits"', html)
		self.assertIn("Produkte &amp; Co &lt;b&gt;", html)  # escaped
		self.assertNotIn(">Produits<", html)


if __name__ == "__main__":
	unittest.main()
