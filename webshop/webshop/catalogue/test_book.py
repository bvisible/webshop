# //// Neoffice — added file (no upstream equivalent).
"""A catalogue's content and its PDF: what is printed, at which price, and whether the contents is right.

The content is built on the small shop of `fixtures.py` for a reseller whose own price list is below the shop's
(FIRST costs them 80, the shop's visitors 100) and whose markup is 30 %. Three things are proved, because
they are the ones that would hurt: the reseller's price is the one printed (cost plus markup), **neither
what they pay nor the shop's price is anywhere in the document**, and the page of each section the contents
announces is the page where that section's title really is. The PDF is made by the shared Chromium where the
bench has one; a bench without it skips those tests and says so.
"""

import unittest
from decimal import Decimal
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.catalogue import access, book, book_pdf, selection
from webshop.webshop.catalogue import api as brand_api
from webshop.webshop.catalogue import fixtures as shop
from webshop.webshop.catalogue.pdf import chromium_available
from webshop.webshop.catalogue.sheet import price_text
from webshop.webshop.utils import customer_pricing

OPTIONS = {"markup_percent": 30, "prices": "customers", "layout": "grid"}


class TestOptions(unittest.TestCase):
	def test_the_options_default_to_the_resellers_markup_and_the_grid(self):
		self.assertEqual(book.clean_options({}, 25), {"markup_percent": 25.0, "prices": "customers", "layout": "grid"})
		self.assertEqual(book.clean_options(None, 12.5)["markup_percent"], 12.5)
		self.assertEqual(book.clean_options({"markup_percent": ""}, 7)["markup_percent"], 7.0)

	def test_what_is_chosen_is_kept_when_it_is_allowed(self):
		clean = book.clean_options({"markup_percent": "40.5", "prices": "none", "layout": "list"}, 0)
		self.assertEqual(clean, {"markup_percent": 40.5, "prices": "none", "layout": "list"})

	def test_an_option_that_is_not_allowed_is_refused_naming_its_field(self):
		for raw, field in (
			({"markup_percent": -1}, "markup_percent"),
			({"markup_percent": 301}, "markup_percent"),
			({"markup_percent": "abc"}, "markup_percent"),
			({"markup_percent": "nan"}, "markup_percent"),
			({"prices": "cost"}, "prices"),
			({"prices": "customers; drop"}, "prices"),
			({"layout": "poster"}, "layout"),
		):
			with self.subTest(raw=raw):
				with self.assertRaises(book.OptionsRefused) as caught:
					book.clean_options(raw, 0)
				self.assertEqual(caught.exception.field, field)

	def test_the_title_is_one_plain_line_of_at_most_eighty_characters(self):
		self.assertEqual(book.clean_title("  Spring \n 2027  "), "Spring 2027")
		for value, reason in ((None, "required"), ("   ", "required"), ("x" * 81, "too_long"), ("a <b> c", "not_plain")):
			with self.subTest(value=str(value)[:10]):
				with self.assertRaises(book.OptionsRefused) as caught:
					book.clean_title(value)
				self.assertEqual((caught.exception.field, caught.exception.reason), ("title", reason))
		self.assertEqual(len(book.clean_title("x" * 80)), 80)


class TestContentsPages(unittest.TestCase):
	"""Which page the contents announces for each section, from the bookmarks Chromium wrote."""

	def test_each_section_gets_the_page_of_its_bookmark_in_order(self):
		entries = [("Catalogue", 1), ("Shoes", 3), ("Shirts", 5), ("Hats", 9)]
		self.assertEqual(book_pdf.section_pages(entries, "Catalogue", ["Shoes", "Shirts", "Hats"]), [3, 5, 9])

	def test_a_section_with_the_title_of_the_cover_is_not_taken_for_the_cover(self):
		entries = [("Shoes", 1), ("Shoes", 3), ("Hats", 4)]
		self.assertEqual(book_pdf.section_pages(entries, "Shoes", ["Shoes", "Hats"]), [3, 4])

	def test_two_sections_with_one_title_each_get_their_own_page(self):
		entries = [("Catalogue", 1), ("Misc", 3), ("Misc", 7)]
		self.assertEqual(book_pdf.section_pages(entries, "Catalogue", ["Misc", "Misc"]), [3, 7])

	def test_spaces_do_not_matter(self):
		entries = [("Catalogue", 1), ("Shoes   and\n boots", 3)]
		self.assertEqual(book_pdf.section_pages(entries, " Catalogue ", ["Shoes and boots"]), [3])

	def test_bookmarks_that_do_not_say_give_nothing_rather_than_wrong_numbers(self):
		self.assertIsNone(book_pdf.section_pages([("Catalogue", 1), ("Shoes", 3)], "Catalogue", ["Shoes", "Hats"]))
		self.assertIsNone(book_pdf.section_pages([], "Catalogue", ["Shoes"]))
		self.assertEqual(book_pdf.section_pages([], "Catalogue", []), [])


class TestTheBook(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		shop.make()

	@classmethod
	def tearDownClass(cls):
		shop.purge()
		super().tearDownClass()

	def setUp(self):
		self.settings = frappe.get_doc("Webshop Settings")
		self.settings.enable_reseller_catalogue = 1
		self.settings.reseller_catalogue_groups = [frappe._dict(allowed_customer_group=shop.RESELLER_GROUP)]
		self.settings.catalogue_credit_text = ""
		patcher = mock.patch.object(access, "shop_settings", return_value=self.settings)
		patcher.start()
		self.addCleanup(patcher.stop)
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(shop.USER)
		answer = brand_api.save_my_brand(
			{
				"brand_name": "Alpine Distribution SA",
				"primary_colour": "#0b6e4f",
				"default_markup_percent": 30,
				"price_rounding": "none",
				"price_display": "Excluding VAT",
				"contact_email": "orders@alpine.example",
			}
		)
		self.assertTrue(answer["ok"], answer)
		self.payload = brand_api._payload(shop.CUSTOMER)
		self.currency = customer_pricing.currency_of(customer_pricing.customer_price_list(
			frappe.get_cached_doc("Webshop Settings"), frappe.get_doc("Customer", shop.CUSTOMER)
		))

	def make(self, picked=None, options=None, title="Catalogue 2027"):
		clean = selection.clean_selection(picked or {"item_groups": [shop.PARENT_GROUP, shop.OTHER_GROUP]})
		return book.build_book(shop.CUSTOMER, self.payload, "", title, clean, {**OPTIONS, **(options or {})})

	def products(self, data):
		return {product.reference: product for section in data.sections for product in section.products}

	# --- what is in it --------------------------------------------------------------------------

	def test_the_products_are_in_sections_by_item_group_in_order(self):
		data = self.make()
		self.assertEqual([section.title for section in data.sections], sorted((s.title for s in data.sections), key=str.lower))
		by_group = {section.title: [p.reference for p in section.products] for section in data.sections}
		self.assertIn(shop.FIRST, by_group[shop.CHILD_GROUP])
		self.assertIn(shop.SECOND, by_group[shop.PARENT_GROUP])
		self.assertEqual(by_group[shop.OTHER_GROUP], [shop.THIRD])
		self.assertEqual(data.product_count, sum(len(items) for items in by_group.values()))

	def test_a_product_carries_its_name_brand_reference_and_short_text_as_a_person_reads_them(self):
		product = self.products(self.make())[shop.FIRST]
		self.assertEqual(product.name, f"{shop.FIRST} name")
		self.assertEqual(product.brand, shop.BRAND_A)
		self.assertEqual(product.reference, shop.FIRST)
		self.assertEqual(product.description, "A short text.", "the markup of the text is gone, the words stay")

	def test_a_product_with_a_picture_carries_it_small_and_one_without_has_its_initials(self):
		products = self.products(self.make())
		self.assertTrue(products[shop.FIRST].picture.startswith("data:image/jpeg;base64,"))
		self.assertIsNone(products[shop.SECOND].picture)
		self.assertTrue(products[shop.SECOND].abbreviation)

	def test_what_the_shop_does_not_show_is_not_in_the_catalogue(self):
		references = set(self.products(self.make({"item_groups": [shop.PARENT_GROUP], "items": [shop.HIDDEN, shop.SOLD]})))
		self.assertFalse({shop.HIDDEN, shop.SOLD} & references)

	def test_a_selection_that_holds_nothing_is_refused(self):
		with self.assertRaises(book.CatalogueRefused) as caught:
			self.make({"items": ["no such product"]})
		self.assertEqual(caught.exception.reason, "empty")

	def test_a_selection_over_the_cap_is_refused(self):
		with mock.patch.object(selection, "MAX_PRODUCTS", 1):
			with self.assertRaises(book.CatalogueRefused) as caught:
				self.make()
		self.assertEqual(caught.exception.reason, "too_many_products")

	# --- the prices ------------------------------------------------------------------------------

	def selling(self, cost, percent=30):
		return price_text(Decimal(str(cost)) * (1 + Decimal(percent) / 100), self.currency)

	def test_the_price_is_the_resellers_own_plus_the_markup_not_the_shops(self):
		products = self.products(self.make())
		self.assertEqual(products[shop.FIRST].price, self.selling(80), "80 on their list, 104 with the markup")
		self.assertEqual(products[shop.SECOND].price, self.selling(40))
		self.assertEqual(products[shop.THIRD].price, self.selling(30))

	def test_the_markup_of_the_catalogue_is_the_one_asked_for(self):
		products = self.products(self.make(options={"markup_percent": 10}))
		self.assertEqual(products[shop.FIRST].price, self.selling(80, 10))

	def test_a_model_is_one_card_from_the_price_of_its_cheapest_variant(self):
		model = self.products(self.make({"items": [shop.MODEL]}))[shop.MODEL]
		self.assertTrue(model.price_from)
		self.assertEqual(model.choices, 2)
		self.assertEqual(model.price, self.selling(48), "the variant at 48 on their list, not the one at 72")

	def test_a_catalogue_without_prices_carries_none_at_all(self):
		data = self.make(options={"prices": "none"})
		self.assertFalse(data.with_prices)
		self.assertEqual(data.price_note, "")
		for product in self.products(data).values():
			self.assertIsNone(product.price)
			self.assertFalse(product.price_missing)

	def test_a_product_the_customer_has_no_price_for_says_so_instead_of_printing_zero(self):
		with mock.patch.object(customer_pricing, "prices_for", return_value={}):
			products = self.products(self.make())
		self.assertTrue(all(product.price_missing and product.price is None for product in products.values()))

	def test_neither_what_the_reseller_pays_nor_the_shops_price_is_anywhere_in_the_content_or_the_html(self):
		data = self.make({"item_groups": [shop.PARENT_GROUP, shop.OTHER_GROUP], "items": [shop.MODEL]})
		haystack = frappe.as_json(data) + book_pdf.render_html(data) + book_pdf.render_html(data, numbers=[3] * len(data.sections))
		for number in ("80.00", "40.00", "30.00", "48.00", "72.00", "100.00", "50.00", "60.00", "90.00"):
			with self.subTest(number=number):
				self.assertNotIn(number, haystack)
		self.assertIn(self.selling(80), haystack, "the selling price is printed")

	def test_the_prices_are_dated_and_say_whether_the_vat_is_in(self):
		data = self.make()
		self.assertIn(frappe.utils.formatdate(frappe.utils.nowdate()), data.price_note)

	# --- the document ----------------------------------------------------------------------------

	def test_what_a_person_typed_is_escaped_in_the_html(self):
		data = self.make()
		data.title = 'Offer <script>alert("x")</script> & "co"'
		data.issuer.name = "<img src=x onerror=alert(1)>"
		data.issuer.contact = ["<b>bold</b>"]
		data.sections[0].title = "<u>Group</u>"
		data.sections[0].products[0].name = "<svg onload=alert(2)>"
		html = book_pdf.render_html(data)
		for raw in ("<script>alert", "<img src=x", "<b>bold", "<u>Group", "<svg onload"):
			with self.subTest(raw=raw):
				self.assertNotIn(raw, html)
		self.assertIn("&lt;script&gt;", html)

	def test_the_colour_is_the_resellers_and_a_value_that_is_not_a_colour_is_never_written(self):
		data = self.make()
		self.assertIn("--brand: #0b6e4f;", book_pdf.page_css(data))
		data.issuer.colour = "red; background: url(//x)"
		self.assertIn("--brand: #1f2933;", book_pdf.page_css(data))
		self.assertNotIn("url(//x)", book_pdf.page_css(data))

	def test_the_footer_text_cannot_break_out_of_its_css_string(self):
		data = self.make()
		data.issuer.name = 'Shop"; } body { display:none } /*'
		css = book_pdf.page_css(data)
		self.assertNotIn('"; }', css.split("@page")[1])

	def test_the_contents_lists_every_section_once_with_a_placeholder_or_a_number(self):
		data = self.make()
		first = book_pdf.render_html(data)
		self.assertEqual(first.count('class="n"'), len(data.sections))
		self.assertIn(">000<", first)
		pages = list(range(3, 3 + len(data.sections)))
		second = book_pdf.render_html(data, numbers=pages)
		for page in pages:
			self.assertIn(f'<span class="n">{page}</span>', second)
		self.assertNotIn('class="n"', book_pdf.render_html(data, show_numbers=False))

	# --- the PDF ---------------------------------------------------------------------------------

	def pdf(self, data):
		if not chromium_available():
			self.skipTest("no Chromium on this bench")
		return book_pdf.make_pdf(data)

	def page_texts(self, pdf):
		import io

		from pypdf import PdfReader

		return [page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages]

	def test_the_contents_announces_for_each_section_the_page_where_its_title_is(self):
		import re

		data = self.make({"item_groups": [shop.PARENT_GROUP, shop.OTHER_GROUP], "items": [shop.MODEL]})
		pdf, pages = self.pdf(data)
		texts = self.page_texts(pdf)
		self.assertEqual(len(texts), pages)
		contents = texts[1]
		for section in data.sections:
			title = section.title
			# the page where the section's heading is printed: after the cover and the contents
			page = next(
				(number for number, text in enumerate(texts, start=1) if number > 2 and title in text.splitlines()), None
			)
			self.assertIsNotNone(page, f"{title} is printed after the contents")
			row = re.compile(re.escape(title) + r"\s+" + str(len(section.products)) + r"\s+" + str(page) + r"(?!\d)")
			self.assertRegex(contents, row, f"the contents says {title} is on page {page}")

	def test_the_pdf_has_a_cover_a_contents_page_the_resellers_name_and_the_selling_prices_only(self):
		data = self.make({"item_groups": [shop.PARENT_GROUP]})
		pdf, pages = self.pdf(data)
		self.assertGreaterEqual(pages, 3)
		texts = self.page_texts(pdf)
		self.assertIn("Catalogue 2027", texts[0])
		self.assertIn("Alpine Distribution SA", texts[0])
		everything = "\n".join(texts)
		self.assertIn(self.selling(80).replace(" ", ""), everything.replace(" ", ""))
		for number in ("80.00", "100.00", "40.00", "50.00"):
			with self.subTest(number=number):
				self.assertNotIn(number, everything)
		self.assertTrue(pdf.startswith(b"%PDF"))

	def test_the_footer_and_the_page_numbers_start_after_the_cover(self):
		data = self.make({"item_groups": [shop.PARENT_GROUP]})
		pdf, pages = self.pdf(data)
		texts = self.page_texts(pdf)
		self.assertNotIn(f"1 / {pages}", texts[0])
		self.assertIn(f"2 / {pages}", texts[1])

	def test_a_catalogue_without_prices_has_no_price_in_it(self):
		data = self.make({"item_groups": [shop.PARENT_GROUP]}, options={"prices": "none"})
		pdf, _pages = self.pdf(data)
		everything = "\n".join(self.page_texts(pdf))
		self.assertNotIn(self.selling(80).replace(" ", ""), everything.replace(" ", ""))
		self.assertNotIn("Prices valid", everything)
