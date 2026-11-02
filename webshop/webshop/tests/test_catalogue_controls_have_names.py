# //// Neoffice — added file (no upstream equivalent).
"""What a screen reader needs on the catalogue (maintenance#2090): an icon alone says nothing to it."""

import unittest
from pathlib import Path

import webshop

ROOT = Path(webshop.__file__).parent


def read(path):
	return (ROOT / path).read_text(encoding="utf-8")


class TestTheCatalogueControlsHaveNames(unittest.TestCase):
	def test_the_view_toggles_say_their_name(self):
		self.assertIn('aria-label="${ view_name }"', read("public/js/product_ui/views.js"))

	def test_the_sort_says_its_name(self):
		self.assertIn('id="product-sort-selector" aria-label="${sortByLabel}"', read("public/js/product_ui/views.js"))

	def test_the_words_reach_the_two_listing_pages(self):
		for page in ("www/all-products/index.html", "templates/generators/item_group.html"):
			text = read(page)
			self.assertIn('"List": {{ _("List")|json }}', text, page)
			self.assertIn('"Grid": {{ _("Grid")|json }}', text, page)

	def test_every_cart_link_of_a_tile_says_where_it_goes(self):
		card = read("templates/includes/product_card.html")
		self.assertNotIn('<a href="/cart">', card)
		self.assertIn("""<a href="/cart" aria-label="{{ _('Cart') }}">""", card)

	def test_the_play_mark_may_carry_a_label(self):
		self.assertIn('class="wsp-card__play" role="img"', read("templates/includes/product_card.html"))
