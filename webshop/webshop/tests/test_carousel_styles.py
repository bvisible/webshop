# //// Neoffice — added file (no upstream equivalent): what the stylesheets of the two carousels may reach.
"""Both carousels print their stylesheet inline on the same Builder page and share their class names (`carousel-wrapper`, `carousel-inner`,
`carousel-indicators`, `indicator`). A rule of one written without its own root reached the other: `.carousel-wrapper { overflow: visible
!important }` of the products let the row of the brands run past the edge of the page. And each must stand alone: the site's Bootstrap sets
`.carousel-indicators` absolute and hides what leaves `.carousel-inner`, and a page may hold only one of the two."""

import re
import unittest
from pathlib import Path

SCSS = Path(__file__).resolve().parents[2] / "public" / "scss"
SHARED = ("carousel-wrapper", "carousel-inner", "carousel-indicators", "indicator")


def rules_of(name: str) -> dict[str, str]:
	"""{selector: declarations} of the flat rules of a component's stylesheet, comments left out."""
	text = re.sub(r"/\*.*?\*/", "", (SCSS / name).read_text(encoding="utf-8"), flags=re.DOTALL)
	text = re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)
	return {m.group(1).strip(): m.group(2) for m in re.finditer(r"([^{};]+)\{([^{}]*)\}", text)}


class TestEachCarouselKeepsToItself(unittest.TestCase):
	def test_no_rule_of_a_carousel_reaches_a_shared_class_outside_its_own_root(self):
		for name, root in (
			("webshop_product_carousel.bundle.scss", ".product-carousel"),
			("webshop_brand_carousel.bundle.scss", ".brand-carousel"),
		):
			for selector in rules_of(name):
				for part in selector.split(","):
					if re.search(rf"\.(?:{'|'.join(SHARED)})\b", part):
						with self.subTest(sheet=name, selector=part.strip()):
							self.assertTrue(part.strip().startswith(root))


class TestEachCarouselStandsAlone(unittest.TestCase):
	def test_the_brands_bring_their_own_dots_and_keep_their_row_visible(self):
		rules = rules_of("webshop_brand_carousel.bundle.scss")
		self.assertIn("overflow: visible", rules[".brand-carousel .carousel-inner"])
		self.assertIn("overflow: hidden", rules[".brand-carousel .carousel-wrapper"])
		self.assertIn("width: 10px", rules[".brand-carousel .indicator"])

	def test_the_dots_of_each_carousel_are_in_the_flow_of_the_page(self):
		for name, root in (
			("webshop_product_carousel.bundle.scss", ".product-carousel"),
			("webshop_brand_carousel.bundle.scss", ".brand-carousel"),
		):
			with self.subTest(root):
				self.assertIn("position: static", rules_of(name)[f"{root} .carousel-indicators"])

	def test_the_products_leave_no_minimum_height_for_the_dots_to_fall_to(self):
		self.assertNotIn("min-height", rules_of("webshop_product_carousel.bundle.scss")[".product-carousel"])


class TestOnlyTheProductsWithAPhotograph(unittest.TestCase):
	"""The head of product_carousel.html, rendered alone: what it asks the helper for and what it keeps."""

	TEMPLATE = Path(__file__).resolve().parents[2] / "templates" / "includes" / "product_carousel.html"

	def render(self, **context):
		from jinja2 import Environment

		text = self.TEMPLATE.read_text(encoding="utf-8")
		head = text[: text.index("{% set unique_carousel_id")]
		asked = {}

		def get_carousel_items(**kwargs):
			asked.update(kwargs)
			# every third row is pictured
			return [{"item_code": str(i), "website_image": "/files/p.jpg" if i % 3 == 0 else None} for i in range(kwargs["limit"])]

		kept = Environment().from_string(head + "{{ website_items|map(attribute='item_code')|join(',') }}")
		return kept.render(get_carousel_items=get_carousel_items, **context).strip(), asked["limit"]

	def test_without_the_option_nothing_changes(self):
		kept, limit = self.render()
		self.assertEqual(8, limit)
		self.assertEqual("0,1,2,3,4,5,6,7", kept)

	def test_with_the_option_the_row_holds_pictured_products_only_and_stays_full(self):
		kept, limit = self.render(hide_without_image=True)
		self.assertEqual(24, limit)
		self.assertEqual("0,3,6,9,12,15,18,21", kept)

	def test_the_option_keeps_to_the_number_of_products_asked_for(self):
		kept, limit = self.render(hide_without_image=True, carousel_limit=4)
		self.assertEqual(12, limit)
		self.assertEqual("0,3,6,9", kept)

