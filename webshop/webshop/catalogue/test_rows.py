# //// Neoffice — added file (no upstream equivalent).
"""The lines of a spreadsheet or a feed: one per thing that can be bought, priced for one reseller.

Built on the small shop of `fixtures.py` for a reseller whose own price list is below the shop's (FIRST costs
them 80, the shop's visitors 100) and whose markup is 30 %. What is proved is what would hurt: the line of a
model is its variants (a model cannot be bought), what the shop does not show is not in the file, and
**which price is in it depends on the mode asked** — the selling price alone for their customers, their own
price alone for themselves, both, or none — and never the shop's.
"""

import io
import json
import unittest
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase
from PIL import Image

from webshop.webshop.catalogue import access, book, rows, selection
from webshop.webshop.catalogue import api as brand_api
from webshop.webshop.catalogue import fixtures as shop
from webshop.webshop.seo import availability as stock

EAN = "4006381333931"  # a GTIN-13 whose check digit is right
MPN = "MPN-FIRST-01"
SECOND_PICTURE = "wstest-cat-picture-2.png"
SLIDESHOW = f"{shop.PREFIX} Cat Show"
# every figure a reseller must not find in a file made for their customers: what they pay, and the shop's own
COSTS = {80.0, 40.0, 30.0, 48.0, 72.0}
SHOP_PRICES = {100.0, 50.0, 60.0, 90.0}


def png(colour):
	out = io.BytesIO()
	Image.new("RGB", (800, 600), colour).save(out, "PNG")
	return out.getvalue()


class TestOptions(unittest.TestCase):
	def test_the_options_default_to_the_resellers_markup_and_their_customers_price(self):
		self.assertEqual(rows.clean_options({}, 25), {"markup_percent": 25.0, "prices": "customers"})
		self.assertEqual(rows.clean_options(None, 12.5)["markup_percent"], 12.5)
		self.assertEqual(rows.clean_options({"markup_percent": ""}, 7)["markup_percent"], 7.0)

	def test_each_price_mode_is_kept_and_a_layout_is_not_an_option_of_a_file(self):
		for mode in ("customers", "tariff", "both", "none"):
			with self.subTest(mode=mode):
				self.assertEqual(rows.clean_options({"prices": mode, "layout": "list"}, 0)["prices"], mode)
		self.assertNotIn("layout", rows.clean_options({"layout": "list"}, 0))

	def test_an_option_that_is_not_allowed_is_refused_naming_its_field(self):
		for raw, field in (
			({"markup_percent": -1}, "markup_percent"),
			({"markup_percent": 301}, "markup_percent"),
			({"markup_percent": "nan"}, "markup_percent"),
			({"prices": "cost"}, "prices"),
			({"prices": "tariff; drop"}, "prices"),
		):
			with self.subTest(raw=raw):
				with self.assertRaises(book.OptionsRefused) as caught:
					rows.clean_options(raw, 0)
				self.assertEqual(caught.exception.field, field)

	def test_a_feed_may_carry_their_customers_price_or_none_but_never_what_they_pay(self):
		for mode in ("customers", "none"):
			self.assertEqual(rows.clean_options({"prices": mode}, 0, modes=rows.FEED_PRICE_MODES)["prices"], mode)
		for mode in ("tariff", "both"):
			with self.assertRaises(book.OptionsRefused):
				rows.clean_options({"prices": mode}, 0, modes=rows.FEED_PRICE_MODES)

	def test_the_columns_follow_the_price_mode(self):
		self.assertNotIn("price", rows.columns_for("tariff"))
		self.assertIn("purchase_price", rows.columns_for("tariff"))
		self.assertIn("price", rows.columns_for("customers"))
		self.assertNotIn("purchase_price", rows.columns_for("customers"))
		self.assertTrue({"price", "purchase_price", "currency"} <= set(rows.columns_for("both")))
		self.assertFalse({"price", "purchase_price", "currency", "price_includes_vat"} & set(rows.columns_for("none")))
		for mode in rows.PRICE_MODES:
			self.assertEqual(rows.columns_for(mode)[:2], ["code", "model"], "the identifying columns come first")


class TestTheLines(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		shop.make()
		# what only these tests look at: the codes of the first product, a second picture, a slideshow
		frappe.get_doc(
			{
				"doctype": "Item Barcode",
				"parent": shop.FIRST,
				"parenttype": "Item",
				"parentfield": "barcodes",
				"barcode": EAN,
				"barcode_type": "EAN",
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Item", shop.FIRST, "default_manufacturer_part_no", MPN)
		picture = frappe.get_doc(
			{"doctype": "File", "file_name": SECOND_PICTURE, "content": png((40, 120, 200)), "is_private": 0}
		).insert(ignore_permissions=True)
		first_picture = frappe.db.get_value("Website Item", {"item_code": shop.FIRST}, "website_image")
		frappe.get_doc(
			{
				"doctype": "Website Slideshow",
				"slideshow_name": SLIDESHOW,
				"slideshow_items": [{"image": first_picture}, {"image": picture.file_url}],
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Website Item", {"item_code": shop.FIRST}, "slideshow", SLIDESHOW)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		shop.purge()
		if frappe.db.exists("Website Slideshow", SLIDESHOW):
			frappe.delete_doc("Website Slideshow", SLIDESHOW, force=True, ignore_permissions=True)
		for name in frappe.get_all("File", filters={"file_name": SECOND_PICTURE}, pluck="name"):
			frappe.delete_doc("File", name, force=True, ignore_permissions=True)
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		self.settings = frappe.get_doc("Webshop Settings")
		self.settings.enable_reseller_catalogue = 1
		self.settings.reseller_catalogue_groups = [frappe._dict(allowed_customer_group=shop.RESELLER_GROUP)]
		patcher = mock.patch.object(access, "shop_settings", return_value=self.settings)
		patcher.start()
		self.addCleanup(patcher.stop)
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(shop.USER)
		answer = brand_api.save_my_brand(
			{"brand_name": "Alpine Distribution SA", "default_markup_percent": 30, "price_rounding": "none", "price_display": "Excluding VAT"}
		)
		self.assertTrue(answer["ok"], answer)
		self.payload = brand_api._payload(shop.CUSTOMER)

	def build(self, picked=None, payload=None, **options):
		clean = selection.clean_selection(picked or {"item_groups": [shop.PARENT_GROUP, shop.OTHER_GROUP]})
		return rows.build_rows(shop.CUSTOMER, payload or self.payload, clean, rows.clean_options(options, 30))

	def by_code(self, data):
		return {row["code"]: row for row in data.rows}

	# --- which lines -----------------------------------------------------------------------------

	def test_a_model_is_its_variants_because_a_model_cannot_be_bought(self):
		data = self.build({"items": [shop.MODEL]})
		self.assertEqual(sorted(row["code"] for row in data.rows), sorted(shop.variants()))
		for row in data.rows:
			self.assertEqual(row["model"], shop.MODEL)
		by_code = self.by_code(data)
		self.assertEqual({tuple(row["attributes"].items()) for row in by_code.values()}, {((shop.ATTRIBUTE, "Small"),), ((shop.ATTRIBUTE, "Large"),)})

	def test_what_the_shop_does_not_show_is_not_in_the_file(self):
		codes = set(self.by_code(self.build({"item_groups": [shop.PARENT_GROUP], "items": [shop.HIDDEN, shop.SOLD]})))
		self.assertFalse({shop.HIDDEN, shop.SOLD} & codes)

	def test_a_variant_asked_for_twice_is_one_line_and_the_order_is_the_products_order(self):
		variant = shop.variants()[0]
		data = self.build({"item_groups": [shop.CHILD_GROUP], "items": [shop.MODEL, variant]})
		codes = [row["code"] for row in data.rows]
		self.assertEqual(len(codes), len(set(codes)))
		self.assertEqual(codes, [row["code"] for row in self.build({"item_groups": [shop.CHILD_GROUP], "items": [shop.MODEL, variant]}).rows])
		self.assertIn(shop.FIRST, codes)

	def test_a_selection_that_holds_nothing_is_refused(self):
		with self.assertRaises(book.CatalogueRefused) as caught:
			self.build({"items": ["no such product"]})
		self.assertEqual(caught.exception.reason, "empty")

	def test_a_file_over_the_cap_is_refused_in_lines_not_in_products(self):
		with mock.patch.object(rows, "MAX_ROWS", 2):
			with self.assertRaises(book.CatalogueRefused) as caught:
				self.build({"items": [shop.MODEL, shop.FIRST]})
		self.assertEqual(caught.exception.reason, "too_many_rows", "a model of two variants and a product are three lines")

	# --- what a line says --------------------------------------------------------------------------

	def test_a_line_carries_what_a_shop_needs_to_list_the_product(self):
		row = self.by_code(self.build())[shop.FIRST]
		self.assertEqual(row["name"], f"{shop.FIRST} name")
		self.assertEqual(row["brand"], shop.BRAND_A)
		self.assertIn(shop.CHILD_GROUP, row["category"])
		self.assertEqual(row["ean"], EAN)
		self.assertEqual(row["mpn"], MPN)
		self.assertEqual(row["unit"], frappe.db.get_value("Item", shop.FIRST, "stock_uom"))
		self.assertEqual(row["description"], "A short text.", "the words stay, the markup goes")
		self.assertEqual(row["model"], "")

	def test_the_pictures_are_whole_public_addresses_the_main_one_is_not_repeated(self):
		row = self.by_code(self.build())[shop.FIRST]
		self.assertRegex(row["image"], r"^https?://[^/]+/files/.*wstest-cat-picture")
		self.assertEqual(len(row["more_images"]), 1, "the slideshow holds the main picture and one more")
		self.assertRegex(row["more_images"][0], rf"^https?://[^/]+/files/.*{SECOND_PICTURE[:-4]}")
		self.assertEqual(self.by_code(self.build())[shop.SECOND]["image"], "", "a product without a picture has an empty cell")

	def test_a_private_file_is_never_given_to_a_reseller_s_shop(self):
		for path in ("/private/files/a.png", "private/files/a.png", "", None):
			self.assertIsNone(rows._public(path))
		self.assertRegex(rows._public("/files/a.png"), r"^https?://[^/]+/files/a\.png$")

	def test_a_variant_is_linked_through_a_page_of_the_shop_and_has_a_whole_address(self):
		for code, row in self.by_code(self.build({"items": [shop.MODEL]})).items():
			with self.subTest(code=code):
				routes = [
					route.lstrip("/")
					for route in (
						frappe.db.get_value("Website Item", {"item_code": code}, "route"),
						frappe.db.get_value("Website Item", {"item_code": shop.MODEL}, "route"),
					)
					if route
				]
				self.assertRegex(row["url"], r"^https?://")
				self.assertTrue(any(route in row["url"] for route in routes), row["url"])

	def test_availability_is_the_shops_own_rule(self):
		data = self.build()
		expected = stock.bulk_availability(list(self.by_code(data)))
		names = {stock.IN_STOCK: "in_stock", stock.OUT_OF_STOCK: "out_of_stock", stock.BACK_ORDER: "backorder"}
		for code, row in self.by_code(data).items():
			with self.subTest(code=code):
				self.assertEqual(row["availability"], names[expected[code].availability])

	# --- the prices ----------------------------------------------------------------------------------

	def test_their_customers_price_is_what_they_pay_plus_the_markup_and_nothing_else(self):
		data = self.build(prices="customers")
		by_code = self.by_code(data)
		self.assertEqual(by_code[shop.FIRST]["price"], 104.0)
		self.assertEqual(by_code[shop.SECOND]["price"], 52.0)
		self.assertEqual(by_code[shop.THIRD]["price"], 39.0)
		self.assertEqual(data.currency, by_code[shop.FIRST]["currency"])
		self.assertEqual(data.columns, rows.columns_for("customers"))
		for row in data.rows:
			self.assertNotIn("purchase_price", row)

	def test_a_variant_is_priced_on_its_own(self):
		by_code = self.by_code(self.build({"items": [shop.MODEL]}, prices="customers"))
		self.assertEqual(sorted(row["price"] for row in by_code.values()), [62.4, 93.6], "48 and 72 on their list, plus 30 %")

	def test_the_mode_for_themselves_carries_what_they_pay_and_no_selling_price(self):
		data = self.build(prices="tariff")
		by_code = self.by_code(data)
		self.assertEqual(by_code[shop.FIRST]["purchase_price"], 80.0)
		self.assertEqual(by_code[shop.SECOND]["purchase_price"], 40.0)
		self.assertEqual(data.columns, rows.columns_for("tariff"))
		for row in data.rows:
			self.assertNotIn("price", row)
			self.assertNotIn("price_includes_vat", row)

	def test_both_prices_side_by_side(self):
		row = self.by_code(self.build(prices="both"))[shop.FIRST]
		self.assertEqual((row["purchase_price"], row["price"]), (80.0, 104.0))

	def test_a_file_without_prices_carries_none_at_all(self):
		data = self.build(prices="none")
		self.assertEqual(data.columns, rows.columns_for("none"))
		for row in data.rows:
			self.assertFalse({"price", "purchase_price", "currency", "price_includes_vat"} & set(row))

	def test_neither_what_they_pay_nor_the_shops_price_is_in_a_file_for_their_customers(self):
		numbers = []

		def walk(value):
			if isinstance(value, dict):
				for item in value.values():
					walk(item)
			elif isinstance(value, (list, tuple)):
				for item in value:
					walk(item)
			elif isinstance(value, (int, float)) and not isinstance(value, bool):
				numbers.append(float(value))

		data = self.build({"item_groups": [shop.PARENT_GROUP, shop.OTHER_GROUP], "items": [shop.MODEL]}, prices="customers")
		walk(data.rows)
		self.assertTrue(numbers, "the test reads real figures")
		self.assertFalse(COSTS & set(numbers), "what the reseller pays is not in it")
		self.assertFalse(SHOP_PRICES & set(numbers), "the shop's own price is not in it")
		text = json.dumps(data.rows, default=str)
		self.assertNotIn("purchase_price", text)

	def test_a_price_with_vat_says_so(self):
		payload = {**self.payload, "values": {**self.payload["values"], "price_display": "Including VAT", "vat_rate": 7.7}}
		row = self.by_code(self.build(payload=payload, prices="customers"))[shop.FIRST]
		self.assertEqual(row["price"], 112.01, "80 plus 30 % plus 7.7 %")
		self.assertIs(row["price_includes_vat"], True)
		self.assertIs(self.by_code(self.build(prices="customers"))[shop.FIRST]["price_includes_vat"], False)

	def test_the_progress_ends_at_the_whole_of_the_prices(self):
		seen = []
		clean = selection.clean_selection({"item_groups": [shop.PARENT_GROUP, shop.OTHER_GROUP]})
		data = rows.build_rows(shop.CUSTOMER, self.payload, clean, rows.clean_options({}, 30), lambda *args: seen.append(args))
		self.assertEqual(seen[-1], ("prices", len(data.rows), len(data.rows)))
