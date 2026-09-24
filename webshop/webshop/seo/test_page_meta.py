# //// Neoffice — added file (no upstream equivalent). neoffice-maintenance#691, lot 6.
"""The title and description a product, a category and a brand page tell search engines
(seo/page_meta.py): the merchant's own words win, the page's computation stays the default, and
the desk's preview reads the same code."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.seo import page_meta

SHOP = "webshop.webshop.seo.site.shop_name"


def product(**overrides):
	doc = frappe._dict(
		web_item_name="Ridge Runner",
		brand="Trailhead",
		web_long_description="<p>A trail shoe made for the mountains, with a rock plate.</p>",
		description="",
		seo_title="",
		seo_description="",
	)
	doc.update(overrides)
	return doc


class TestProductPage(FrappeTestCase):
	def test_left_empty_the_page_says_what_it_always_said(self):
		with patch(SHOP, return_value="Atelier"):
			meta = page_meta.product_meta(product())
		self.assertEqual(meta.heading, "Ridge Runner - Trailhead")
		self.assertEqual(meta.title, "Ridge Runner - Trailhead")
		self.assertEqual(meta.html_title, "Ridge Runner - Trailhead | Atelier")
		self.assertEqual(meta.description, "A trail shoe made for the mountains, with a rock plate.")

	def test_the_merchants_words_win_and_the_heading_stays_the_products(self):
		doc = product(seo_title="Trail running shoe Ridge Runner", seo_description="  Grip on wet rock.  ")
		with patch(SHOP, return_value="Atelier"):
			meta = page_meta.product_meta(doc)
		self.assertEqual(meta.heading, "Ridge Runner - Trailhead")
		self.assertEqual(meta.title, "Trail running shoe Ridge Runner")
		self.assertEqual(meta.html_title, "Trail running shoe Ridge Runner | Atelier")
		self.assertEqual(meta.description, "Grip on wet rock.")
		with patch(SHOP, return_value="Atelier"):
			self.assertEqual(page_meta.product_meta(doc, own=False).title, "Ridge Runner - Trailhead")

	def test_a_title_that_already_names_the_shop_is_not_suffixed_twice(self):
		with patch(SHOP, return_value="Atelier"):
			self.assertEqual(page_meta.with_shop_name("Ridge Runner at Atelier"), "Ridge Runner at Atelier")
			self.assertEqual(page_meta.with_shop_name("Ridge Runner"), "Ridge Runner | Atelier")
		with patch(SHOP, return_value=""):
			self.assertEqual(page_meta.with_shop_name("Ridge Runner"), "Ridge Runner")

	def test_a_product_without_text_is_described_by_its_name(self):
		meta = page_meta.product_meta(product(web_long_description="", brand=None))
		self.assertEqual((meta.heading, meta.description), ("Ridge Runner", "Ridge Runner"))


class TestCategoryAndBrandPages(FrappeTestCase):
	def test_a_category_says_its_own_text_then_what_it_holds(self):
		group = frappe._dict(name="Shoes", website_title="", description="", seo_title="", seo_description="")
		with (
			patch("webshop.webshop.seo.meta.subtree_groups", return_value=["Shoes"]),
			patch("webshop.webshop.seo.meta.catalogue_summary", return_value=(12, ["Trailhead"])),
			patch(SHOP, return_value="Atelier"),
		):
			computed = page_meta.item_group_meta(group)
			written = page_meta.item_group_meta(frappe._dict(group, seo_title="Trail shoes", seo_description="For the hills."))
		self.assertEqual(computed.title, "Shoes")
		self.assertIn("12", computed.description)
		self.assertEqual((written.heading, written.title, written.description), ("Shoes", "Trail shoes", "For the hills."))
		self.assertEqual(written.html_title, "Trail shoes | Atelier")

	def test_a_brand_says_its_own_words_or_its_description(self):
		record = frappe._dict(description="Made in the Alps since 1920.", seo_title="", seo_description="")
		with patch("frappe.db.get_value", return_value=record), patch(SHOP, return_value="Atelier"):
			meta = page_meta.brand_meta("Trailhead")
		self.assertEqual((meta.title, meta.html_title), ("Trailhead", "Trailhead | Atelier"))
		self.assertEqual(meta.description, "Made in the Alps since 1920.")
		record.update(seo_title="Trailhead trail shoes", seo_description="Every Trailhead model.")
		with patch("frappe.db.get_value", return_value=record), patch(SHOP, return_value="Atelier"):
			meta = page_meta.brand_meta("Trailhead")
		self.assertEqual((meta.title, meta.description), ("Trailhead trail shoes", "Every Trailhead model."))


class TestThePreview(FrappeTestCase):
	def test_it_shows_the_pages_own_values_whatever_the_fields_hold(self):
		doc = product(name="WEB-1", route="products/ridge-runner", seo_title="Mine")
		with (
			patch("frappe.has_permission", return_value=True) as permission,
			patch("frappe.get_doc", return_value=doc),
			patch("webshop.webshop.multi_site.site_url", side_effect=lambda path: "https://shop.test" + path),
			patch(SHOP, return_value="Atelier"),
		):
			preview = page_meta.seo_preview("Website Item", "WEB-1")
		permission.assert_called_once_with("Website Item", "read", "WEB-1", throw=True)
		self.assertEqual(preview["title"], "Ridge Runner - Trailhead", "the default, not the field")
		self.assertEqual(preview["url"], "https://shop.test/products/ridge-runner")
		self.assertEqual((preview["shop"], preview["title_budget"], preview["description_budget"]), ("Atelier", 60, 160))

	def test_only_the_three_pages(self):
		with self.assertRaises(frappe.ValidationError):
			page_meta.seo_preview("User", "Administrator")
