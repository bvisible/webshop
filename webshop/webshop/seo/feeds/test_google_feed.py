# //// Neoffice — added file (no upstream equivalent): the Google Merchant Center feed
# //// (seo/feeds/google.py). neoffice-maintenance#691 (lot 3), 2026-09-24.
"""What the feed sends, what it leaves out and why, and that it says what the page says: Google
refuses an item whose feed and page disagree, and suspends an account that keeps doing it."""

import os
import tempfile
import unittest
import xml.etree.ElementTree as ElementTree
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.seo.availability import IN_STOCK
from webshop.webshop.seo.feeds import google

G = "{" + google.GOOGLE_NAMESPACE + "}"
SETTINGS = frappe._dict(google_feed_include_second_hand=1, google_feed_attribute_map="")


def _doc(**fields):
	return frappe._dict(
		{
			"item_code": "TRAIL-01",
			"web_item_name": "Trail shoe",
			"route": "shop/trail-shoe",
			"item_group": "Shoes",
			"brand": "Trailhead",
			"description": "<p>Light.</p>",
			"website_image": "/files/trail.jpg",
			"slideshow": None,
			"item_condition": "New",
			"has_variants": 0,
			"is_gift_card": 0,
			**fields,
		}
	)


def _entry(doc, price=None, settings=SETTINGS, excluded=frozenset(), identifiers=None, attributes=None):
	price = price if price is not None else {"price_list_rate": 90, "currency": "CHF"}
	shopping_cart = frappe._dict(
		cart_settings=frappe._dict(show_price=1, enable_reviews=0), product_info={"price": price}
	)
	with (
		patch("webshop.webshop.shopping_cart.product_info.get_product_info_for_website", return_value=shopping_cart),
		patch("webshop.webshop.seo.availability.schema_availability", return_value=IN_STOCK),
		patch("webshop.webshop.seo.facts.product_identifiers", return_value=identifiers or {}),
		patch("webshop.webshop.seo.facts.category_path", return_value="Shoes > Trail"),
		patch.object(google, "is_service", return_value=False),
		patch.object(google, "variant_attributes", return_value=attributes or {}),
		patch.object(google, "google_category", return_value=""),
		patch.object(google, "shipping_weight", return_value=None),
		patch("webshop.webshop.multi_site.site_url", side_effect=lambda path: "https://shop.test/" + path.lstrip("/")),
	):
		return google.item_entry(doc, settings, set(excluded), google.attribute_map(settings))


class TestAttributes(FrappeTestCase):
	def test_common_names_and_the_shop_s_own(self):
		mapping = google.attribute_map(frappe._dict(google_feed_attribute_map="Teinte = color\nCoupe = size\nX = price"))
		self.assertEqual(mapping["couleur"], "color")
		self.assertEqual(mapping["taille"], "size")
		self.assertEqual(mapping["teinte"], "color")
		self.assertEqual(mapping["coupe"], "size")
		self.assertNotIn("x", mapping)  # "price" is not an attribute Google takes from here


class TestItemEntry(FrappeTestCase):
	def test_what_is_left_out_and_why(self):
		cases = {
			"model": _doc(has_variants=1),
			"gift_card": _doc(is_gift_card=1),
			"excluded": _doc(exclude_from_google_shopping=1),
			"id_too_long": _doc(item_code="X" * 51),
			"no_image": _doc(website_image=None),
		}
		for reason, doc in cases.items():
			with self.subTest(reason=reason):
				self.assertEqual(_entry(doc), (None, reason))
		self.assertEqual(_entry(_doc(), excluded={"Shoes"}), (None, "excluded"))
		self.assertEqual(_entry(_doc(), price={}), (None, "no_price"))
		off = frappe._dict(SETTINGS, google_feed_include_second_hand=0)
		self.assertEqual(_entry(_doc(item_condition="Second-hand"), settings=off), (None, "second_hand_off"))

	def test_the_item_as_its_page_shows_it(self):
		entry, reason = _entry(
			_doc(variant_of="TRAIL", item_condition="Refurbished"),
			identifiers={"gtin13": "4006381333931", "mpn": "TH-01"},
			attributes={"color": "Grey", "size": "42"},
		)
		self.assertIsNone(reason)
		self.assertEqual(entry["id"], "TRAIL-01")
		self.assertEqual(entry["link"], "https://shop.test/shop/trail-shoe")
		self.assertEqual(entry["image_link"], "https://shop.test/files/trail.jpg")
		self.assertEqual((entry["price"], entry["availability"]), ("90.00 CHF", "in_stock"))
		self.assertEqual((entry["condition"], entry["item_group_id"]), ("refurbished", "TRAIL"))
		self.assertEqual((entry["gtin"], entry["mpn"], entry["color"], entry["size"]), ("4006381333931", "TH-01", "Grey", "42"))
		self.assertEqual(entry["product_type"], "Shoes > Trail")
		self.assertNotIn("identifier_exists", entry)
		self.assertNotIn("sale_price", entry)

	def test_a_struck_price_is_the_price_and_the_paid_one_the_sale_price(self):
		sale = {"price_list_rate": 90, "currency": "CHF", "mrp": 100, "formatted_mrp": "CHF 100.00"}
		entry, _reason = _entry(_doc(), price=sale)
		self.assertEqual((entry["price"], entry["sale_price"]), ("100.00 CHF", "90.00 CHF"))

	def test_no_identifier_says_so(self):
		entry, _reason = _entry(_doc())
		self.assertEqual(entry["identifier_exists"], "no")


class TestXml(FrappeTestCase):
	def test_a_well_formed_feed_in_google_s_namespace(self):
		xml = google.render_xml(
			[{"id": "A&B", "title": "Tee <XL>", "additional_image_link": ["https://s/1.jpg", "https://s/2.jpg"]}],
			"Atelier & Co",
			"https://shop.test/",
		)
		root = ElementTree.fromstring(xml.encode())
		item = root.find("channel/item")
		self.assertEqual(item.find(G + "id").text, "A&B")
		self.assertEqual(item.find(G + "title").text, "Tee <XL>")
		self.assertEqual(len(item.findall(G + "additional_image_link")), 2)
		self.assertEqual(root.find("channel/title").text, "Atelier & Co")


class TestSites(FrappeTestCase):
	def test_a_site_that_hides_its_prices_or_serves_businesses_has_no_feed(self):
		open_site = frappe._dict(enabled=1, show_price=1, hide_price_for_guest=0)
		with patch("webshop.webshop.multi_site.site_is_business_only", return_value=False):
			self.assertIsNone(google.site_refusal(open_site))
			self.assertTrue(google.site_refusal(frappe._dict(open_site, hide_price_for_guest=1)))
			self.assertTrue(google.site_refusal(frappe._dict(open_site, show_price=0)))
		with patch("webshop.webshop.multi_site.site_is_business_only", return_value=True):
			self.assertTrue(google.site_refusal(open_site))


class TestRoute(FrappeTestCase):
	def setUp(self):
		self.form_dict = frappe.local.form_dict
		self.addCleanup(setattr, frappe.local, "form_dict", self.form_dict)
		self.folder = tempfile.mkdtemp()
		self.path = os.path.join(self.folder, "google-default.xml")
		with open(self.path, "w") as handle:
			handle.write("<rss/>")

	def render(self, token, enabled=1):
		frappe.local.form_dict = frappe._dict(token=token)
		settings = frappe._dict(enable_google_feed=enabled, google_feed_token="s3cret")
		with (
			patch("frappe.get_cached_doc", return_value=settings),
			patch.object(google, "feed_sites", return_value=[frappe._dict(key="default", profile=None)]),
			patch.object(google, "feed_path", return_value=self.path),
		):
			return google.FeedRenderer(path=google.FEED_ROUTE).render()

	def test_the_file_behind_the_token_and_nothing_without_it(self):
		self.assertTrue(google.FeedRenderer(path="/feeds/google.xml").can_render())
		response = self.render("s3cret")
		self.assertEqual((response.status_code, response.mimetype), (200, "application/xml"))
		self.assertEqual(response.get_data(), b"<rss/>")
		self.assertEqual(self.render("guess").status_code, 404)
		self.assertEqual(self.render("s3cret", enabled=0).status_code, 404)


def _on_the_erpnext_fork() -> bool:
	"""get_product_info_for_website passes `warehouse=` to get_price, a keyword only the
	bvisible/erpnext fork knows: on a stock ERPNext (ci.yml) the page itself cannot price."""
	import inspect

	from erpnext.utilities.product import get_price

	return "warehouse" in inspect.signature(get_price).parameters


@unittest.skipUnless(
	_on_the_erpnext_fork(),
	"prices through get_price(warehouse=), the fork's: runs in the fleet's Tests workflow, on the forks",
)
class TestParityWithThePage(FrappeTestCase):
	"""On a real item of the test site: the feed's price is the one the page shows a visitor."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		from webshop.webshop.tests.utils import ensure_shop_settings

		cls.written = ensure_shop_settings()

	@classmethod
	def tearDownClass(cls):
		from webshop.webshop.tests.utils import restore_webshop_settings

		if cls.written:
			restore_webshop_settings(cls.written)
		super().tearDownClass()

	def test_the_feed_prices_as_the_page_does(self):
		from webshop.webshop.doctype.website_item.website_item import make_website_item
		from webshop.webshop.shopping_cart.product_info import get_product_info_for_website
		from webshop.webshop.tests.utils import make_test_item, selling_price_list

		item = make_test_item("TEST-FEED-PARITY", is_stock_item=0)
		price_list = selling_price_list()
		if not frappe.db.exists("Item Price", {"item_code": item.name, "price_list": price_list}):
			frappe.get_doc(
				{"doctype": "Item Price", "item_code": item.name, "price_list": price_list, "price_list_rate": 42}
			).insert()
		name = frappe.db.get_value("Website Item", {"item_code": item.name}, "name") or make_website_item(item, save=True)[0]
		frappe.db.set_value("Website Item", name, {"published": 1, "website_image": "/files/test-feed.png"})
		doc = frappe.get_doc("Website Item", name)
		site = frappe._dict(key="default", profile=None)
		with google.serving(site):
			from webshop.webshop.doctype.webshop_settings.webshop_settings import get_shopping_cart_settings

			settings = get_shopping_cart_settings()
			entry, reason = google.item_entry(doc, settings, set(), google.attribute_map(settings))
			page = get_product_info_for_website(doc.item_code, skip_quotation_creation=True)
		self.assertIsNone(reason)
		shown = page["product_info"]["price"]
		self.assertEqual(entry["price"], google.money(shown["price_list_rate"], shown["currency"]))
