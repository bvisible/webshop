# //// Neoffice — added file (no upstream equivalent): /llms.txt (seo/llms.py). #691 lot 4.
"""The shop's card for language models: its categories and brand pages with their addresses, its
promises and contact, never a price, and nothing on a site serving business accounts only."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.seo import llms

SETTINGS = frappe._dict(
	delivery_delay="2 à 4 jours ouvrés",
	return_days=30,
	store_hours=[frappe._dict(weekday="Monday")],
	store_email="shop@example.com",
	store_phone="+41 00 000 00 00",
	store_address="Rue 1\n1950 Sion",
)


class TestCard(FrappeTestCase):
	def card(self, business_only=False):
		with (
			patch("webshop.webshop.multi_site.site_is_business_only", return_value=business_only),
			patch("webshop.webshop.multi_site.site_url", side_effect=lambda path: "https://shop.test/" + path.lstrip("/")),
			patch("webshop.webshop.seo.site.shop_name", return_value="Atelier"),
			patch.object(llms, "top_categories", return_value=[("Shoes", "shop/shoes", 12), ("Bags", "shop/bags", 3)]),
			patch("webshop.webshop.product_data_engine.brand_pages.offered_brands", return_value={"Café & Co": 2, "Trailhead": 5}),
			patch("frappe.get_cached_doc", return_value=SETTINGS),
		):
			return llms.llms_txt()

	def test_categories_brands_promises_and_contact_with_their_addresses(self):
		text = self.card()
		self.assertTrue(text.startswith("# Atelier\n"), text)
		for address in (
			"https://shop.test/shop/shoes",
			"https://shop.test/brands/trailhead",
			"https://shop.test/brands/cafe-co",
			"https://shop.test/store-hours",
			"https://shop.test/sitemap.xml",
		):
			self.assertIn(address, text)
		self.assertIn("shop@example.com", text)
		self.assertIn("Rue 1 1950 Sion", text)
		# the section a model may skip keeps the format's own name
		self.assertIn("## Optional", text)
		self.assertLess(text.index("brands/trailhead"), text.index("brands/cafe-co"), "fullest brand first")

	def test_never_a_price(self):
		text = self.card()
		self.assertNotRegex(text, r"\d+[.,]\d{2}")
		self.assertNotIn("CHF", text)

	def test_a_site_serving_business_accounts_only_has_none(self):
		self.assertIsNone(self.card(business_only=True))

	def test_the_first_level_of_the_tree_fullest_first(self):
		groups = [
			frappe._dict(name="All", route="", parent_item_group="", lft=1),
			frappe._dict(name="Shoes", route="shop/shoes", parent_item_group="All", lft=2),
			frappe._dict(name="Trail", route="shop/shoes/trail", parent_item_group="Shoes", lft=3),
			frappe._dict(name="Bags", route="shop/bags", parent_item_group="All", lft=6),
		]
		carried = {"All": 15, "Shoes": 12, "Trail": 7, "Bags": 3}
		with (
			patch("webshop.webshop.product_data_engine.catalogue_scope.groups_carrying_items", return_value=carried),
			patch("frappe.get_all", return_value=groups),
		):
			self.assertEqual(llms.top_categories(), [("Shoes", "shop/shoes", 12), ("Bags", "shop/bags", 3)])


class TestRoute(FrappeTestCase):
	def test_markdown_or_nothing(self):
		with patch.object(llms, "llms_txt", return_value="# Atelier\n"):
			response = llms.LlmsTxtRenderer(path="/llms.txt").render()
		self.assertEqual((response.status_code, response.mimetype), (200, "text/markdown"))
		self.assertEqual(response.get_data(as_text=True), "# Atelier\n")
		with patch.object(llms, "llms_txt", return_value=None):
			self.assertEqual(llms.LlmsTxtRenderer(path="/llms.txt").render().status_code, 404)
		self.assertFalse(llms.LlmsTxtRenderer(path="/robots.txt").can_render())
