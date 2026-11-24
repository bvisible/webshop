# //// Neoffice — added file (no upstream equivalent). neoffice-maintenance#3346.
"""The chip of an active filter says what its facet says.

A Select field facet (the gender, the condition, a field of the shop's own) draws each value through the translation, in the
`.label-area` of the label that holds the checkbox. The chip of the active-filters bar looked for the label with
`$checkbox.next('label')`: the checkbox is INSIDE its label, so it found none and fell back to the value stored on the item
("Women" in a chip next to a facet that read "Femme"). The chip reads the label the facet draws; the page keeps no table of words.

The drawing is tested here through the template, as the shop renders it; the script is read as text, as the other tests of
`views.js` do. What the visitor sees is replayed on screen by the scenario `shop-model-filters` of the devops repository.
"""

import unittest
from pathlib import Path

import frappe
from bs4 import BeautifulSoup

APP = Path(__file__).resolve().parents[2]
VIEWS = APP / "public" / "js" / "product_ui" / "views.js"
FIELD = "wstest_gender"
RENDER = (
	"{% from 'webshop/templates/includes/macros.html' import field_filter_section %}{{ field_filter_section(filters) }}"
)


def drawn_facet(values=("Men", "Women")):
	"""The sidebar block of a Select field, as the shop renders it."""
	filters = [[frappe._dict(label="Gender", fieldname=FIELD), list(values)]]
	return BeautifulSoup(frappe.render_template(RENDER, {"filters": filters}), "html.parser")


def chip_source():
	"""The code, comments left out, of the part of `update_active_filters_display` that builds the chip of a field filter."""
	script = VIEWS.read_text(encoding="utf-8")
	start = script.index("// Field filters from URL")
	part = script[start : script.index("// Attribute filters from URL", start)]
	return "\n".join(line for line in part.splitlines() if not line.strip().startswith("//"))


class TestTheChipSaysWhatTheFacetSays(unittest.TestCase):
	def test_the_checkbox_sits_inside_its_label_and_the_label_area_holds_what_the_facet_reads(self):
		soup = drawn_facet()
		for value in ("Men", "Women"):
			with self.subTest(value):
				box = soup.select_one(f'input.field-filter[data-filter-name="{FIELD}"][data-filter-value="{value}"]')
				self.assertIsNotNone(box)
				label = box.find_parent("label")
				self.assertIsNotNone(label, "the checkbox is inside its label")
				self.assertEqual(label.select_one(".label-area").get_text(strip=True), frappe._(value))

	def test_no_label_follows_the_checkbox_so_the_old_lookup_found_nothing(self):
		box = drawn_facet().select_one(f'input.field-filter[data-filter-name="{FIELD}"][data-filter-value="Women"]')
		self.assertIsNone(box.find_next_sibling("label"))

	def test_the_chip_reads_the_label_area_of_the_checkboxs_own_label(self):
		source = chip_source()
		self.assertRegex(source, r"closest\('label'\)\.find\('\.label-area'\)")
		self.assertNotRegex(source, r"\.next\('label'\)")

	def test_the_label_the_facet_draws_comes_before_the_stored_value(self):
		source = chip_source()
		self.assertRegex(source, r"const displayLabel = facetLabel \|\| drawnLabel \|\| translated;")

	def test_the_brand_keeps_its_own_label_first(self):
		# a brand's label is a translation of content, carried by data-label on its wrapper (utils/localized.py)
		self.assertRegex(chip_source(), r"closest\('\[data-label\]'\)\.attr\('data-label'\)")
