# //// Neoffice — added file (no upstream equivalent): the brand pages (brand_pages.py, www/brand).
# //// neoffice-maintenance#691, lot 2.
"""A brand's page: its address, which brands have one, what the page asks the catalogue for, and
where the shop's links to a brand lead. Every link to a brand used to open the catalogue filtered
on it, which robots.txt closes: a search for a brand found no page of the shop."""

from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.product_data_engine import brand_pages

APP = Path(__file__).resolve().parents[2]
SCOPE = "webshop.webshop.product_data_engine.catalogue_scope.visible_item_filters"


class TestAddress(FrappeTestCase):
	def test_ascii_words_joined_by_hyphens(self):
		cases = {"Canon": "canon", "Café & Co": "cafe-co", "Hewlett-Packard": "hewlett-packard", "  3M  ": "3m"}
		for name, slug in cases.items():
			with self.subTest(name=name):
				self.assertEqual(brand_pages.brand_slug(name), slug)
				self.assertEqual(brand_pages.brand_route(name), "brands/" + slug)


class TestWhichBrandsHaveAPage(FrappeTestCase):
	def test_the_brands_this_site_shows_and_nothing_without_a_letter(self):
		rows = [frappe._dict(brand="Canon", total=3), frappe._dict(brand="Ω", total=2)]
		with patch(SCOPE, return_value={"published": 1}), patch("frappe.get_all", return_value=rows) as get_all:
			self.assertEqual(brand_pages.offered_brands(), {"Canon": 3})
		self.assertEqual(get_all.call_args.kwargs["filters"], {"published": 1, "brand": ["is", "set"]})

	def test_a_slug_names_one_brand_and_links_follow(self):
		with patch.object(brand_pages, "offered_brands", return_value={"Canon": 3, "Café & Co": 1}):
			self.assertEqual(brand_pages.brand_of_slug("cafe-co"), "Café & Co")
			self.assertIsNone(brand_pages.brand_of_slug("nikon"))
			self.assertIsNone(brand_pages.brand_of_slug(""))
			routes = brand_pages.brand_page_routes()
			self.assertEqual(routes, {"Canon": "/brands/canon", "Café & Co": "/brands/cafe-co"})
			self.assertEqual(brand_pages.brand_link("Canon", routes), "brands/canon")
			# a brand with no page keeps the link it always had
			fallback = brand_pages.brand_link("Nikon", routes)
			self.assertTrue(fallback.startswith("all-products?field_filters="))
			self.assertIn('"Nikon"', unquote(fallback))


class TestPage(FrappeTestCase):
	def setUp(self):
		self.form_dict = frappe.local.form_dict
		self.addCleanup(setattr, frappe.local, "form_dict", self.form_dict)

	def test_a_brand_without_a_page_does_not_exist(self):
		from webshop.www.brand import index as page

		frappe.local.form_dict = frappe._dict(brand_slug="nikon")
		with patch.object(page, "brand_of_slug", return_value=None), self.assertRaises(frappe.PageDoesNotExistError):
			page.get_context(frappe._dict())

	def test_the_catalogue_with_the_brand_locked_under_its_own_address(self):
		from webshop.www.brand import index as page

		def listing(context, title, locked_field_filters=None, listing_route=None):
			context.update(
				title=title, locked=locked_field_filters, route=listing_route, metatags=frappe._dict(description="x")
			)

		frappe.local.form_dict = frappe._dict(brand_slug="cafe-co")
		record = frappe._dict(image="/files/cafe.png", description="Torréfacteur <b>depuis</b> 1920.")
		with (
			patch.object(page, "brand_of_slug", return_value="Café & Co"),
			patch.object(page, "build_listing_context", side_effect=listing),
			patch.object(page, "shop_name", return_value="Atelier"),
			patch("frappe.db.get_value", return_value=record),
		):
			context = page.get_context(frappe._dict())
		self.assertEqual((context.title, context.route), ("Café & Co", "/brands/cafe-co"))
		self.assertEqual(context.locked, {"brand": ["Café & Co"]})
		self.assertEqual(context.html_title, "Café & Co | Atelier")
		self.assertEqual(context.metatags["description"], "Torréfacteur depuis 1920.")
		self.assertEqual(context.metatags["image"], "/files/cafe.png")

	def test_the_description_does_not_name_the_brand_twice(self):
		"""Measured on osiris: "Canon chez <shop> : 2 produits, dont Canon." on Canon's own page."""
		from webshop.webshop.seo import meta

		context = frappe._dict(metatags={})
		with (
			patch.object(meta, "catalogue_summary", return_value=(2, ["Canon"])),
			patch.object(meta, "first_product_image", return_value=None),
			patch.object(meta, "shop_name", return_value="Atelier"),
			patch.object(meta, "listing_canonical", return_value="https://shop.test/brands/canon"),
		):
			meta.listing_metatags(context, "Canon", "/brands/canon", {"brand": ["Canon"]})
		self.assertEqual(context.metatags["description"].count("Canon"), 1, context.metatags["description"])

	def test_the_intro_prints_the_logo_and_the_text_escaped(self):
		fragment = (APP / "templates" / "includes" / "brand_intro.html").read_text()
		brand = frappe._dict(name="Café & Co", image="/files/cafe.png", description="Grains <torréfiés>")
		html = frappe.render_template(fragment, {"brand": brand})
		self.assertIn('src="/files/cafe.png" alt="Café &amp; Co"', html)
		self.assertIn("Grains &lt;torréfiés&gt;", html)
		self.assertEqual(frappe.render_template(fragment, {"brand": frappe._dict(name="X")}).strip(), "")


class TestLinksLeadToThePage(FrappeTestCase):
	"""Where the shop linked a brand to its filtered catalogue: now its page, when it has one."""

	def test_the_product_page_and_the_carousel_ask_for_the_page(self):
		for template in ("generators/item/item_details.html", "includes/brand_carousel.html"):
			with self.subTest(template=template):
				self.assertIn("brand_page_routes()", (APP / "templates" / template).read_text())
		self.assertIn(
			"webshop.webshop.product_data_engine.brand_pages.brand_page_routes", frappe.get_hooks("jinja")["methods"]
		)
		rules = {rule["from_route"]: rule["to_route"] for rule in frappe.get_hooks("website_route_rules")}
		self.assertEqual(rules.get("/brands/<brand_slug>"), "brand")

	def test_the_carousel_helper_links_the_page(self):
		from webshop.webshop.utils import brand_carousel_helper

		brand = frappe._dict(name="Canon", brand="Canon", image="/files/canon.png", description="")
		with (
			patch("frappe.get_all", return_value=[brand]),
			patch("frappe.db.count", return_value=2),
			patch("webshop.webshop.multi_site.excluded_item_names", return_value=[]),
			patch.object(brand_pages, "offered_brands", return_value={"Canon": 2}),
		):
			rows = brand_carousel_helper.get_featured_brands(["Canon"], use_cache=False)
		self.assertEqual([row["route"] for row in rows], ["brands/canon"])
