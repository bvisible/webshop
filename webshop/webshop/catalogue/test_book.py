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
from webshop.webshop.catalogue import languages
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

	def test_a_language_is_kept_when_it_is_a_code_and_the_options_are_unchanged_without_one(self):
		self.assertEqual(
			book.clean_options({"language": "de"}, 25), {"markup_percent": 25.0, "prices": "customers", "layout": "grid", "language": "de"}
		)
		self.assertNotIn("language", book.clean_options({"language": ""}, 25))
		with self.assertRaises(book.OptionsRefused) as caught:
			book.clean_options({"language": "Deutsch"}, 25)
		self.assertEqual((caught.exception.field, caught.exception.reason), ("language", "bad_language"))

	def test_a_picture_quality_is_kept_when_it_is_in_the_list_and_the_options_are_unchanged_without_one(self):
		self.assertNotIn("quality", book.clean_options({}, 25))
		self.assertNotIn("quality", book.clean_options({"quality": "standard"}, 25))
		for quality in ("light", "print"):
			self.assertEqual(book.clean_options({"quality": quality}, 25)["quality"], quality)
		for refused in ("high", 5, "print; drop"):
			with self.subTest(value=refused), self.assertRaises(book.OptionsRefused) as caught:
				book.clean_options({"quality": refused}, 25)
			self.assertEqual((caught.exception.field, caught.exception.reason), ("quality", "not_allowed"))

	def test_a_cover_is_kept_when_it_is_in_the_list_and_the_options_are_unchanged_without_one(self):
		self.assertNotIn("cover", book.clean_options({}, 25))
		self.assertNotIn("cover", book.clean_options({"cover": "solid"}, 25))
		for cover in ("band", "minimal"):
			self.assertEqual(book.clean_options({"cover": cover}, 25)["cover"], cover)
		for refused in ("full", "Band", "band; x", 7):
			with self.subTest(value=refused), self.assertRaises(book.OptionsRefused) as caught:
				book.clean_options({"cover": refused}, 25)
			self.assertEqual((caught.exception.field, caught.exception.reason), ("cover", "not_allowed"))

	def test_the_sheet_layout_is_a_layout_like_the_others(self):
		self.assertEqual(book.clean_options({"layout": "sheet"}, 25)["layout"], "sheet")
		for refused in ("page", "Sheet", "grid; list", 4):
			with self.subTest(value=refused), self.assertRaises(book.OptionsRefused) as caught:
				book.clean_options({"layout": refused}, 25)
			self.assertEqual((caught.exception.field, caught.exception.reason), ("layout", "not_allowed"))

	def test_an_order_form_is_kept_only_when_it_is_asked_for(self):
		for asked in (True, 1, "1", "true"):
			with self.subTest(asked=asked):
				self.assertIs(book.clean_options({"order_form": asked}, 25)["order_form"], True)
		for not_asked in (None, False, 0, "0", "", "no", "false"):
			with self.subTest(not_asked=not_asked):
				self.assertNotIn("order_form", book.clean_options({"order_form": not_asked}, 25))
		self.assertNotIn("order_form", book.clean_options({}, 25))

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
				"markup_rules": [],
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

	def test_a_catalogue_in_a_language_prints_the_translated_names_and_descriptions(self):
		def translations(*entries):
			return [
				{"ref_name": frappe.db.get_value("Website Item", {"item_code": code}, "name"), "fieldname": field, "text": text, "human": True}
				for code, field, text in entries
			]

		found = translations((shop.FIRST, "web_item_name", "Wanderschuh"), (shop.FIRST, "short_description", "Leicht und stark."))
		with mock.patch.object(languages.localized, "translation_rows", return_value=found):
			products = self.products(self.make(options={"language": "de"}))
		self.assertEqual(products[shop.FIRST].name, "Wanderschuh")
		self.assertEqual(products[shop.FIRST].description, "Leicht und stark.")
		source = self.products(self.make())
		self.assertNotEqual(source[shop.FIRST].name, "Wanderschuh")
		self.assertEqual(products[shop.SECOND].name, source[shop.SECOND].name, "a product with no translation keeps its own")
		self.assertEqual(products[shop.FIRST].price, source[shop.FIRST].price, "and the price is the same")

	def test_the_quality_chosen_is_the_size_and_the_compression_the_pictures_are_made_with(self):
		seen = {}
		for quality in ("light", "standard", "print"):
			with mock.patch.object(book.images, "site_picture", return_value=None) as picture:
				self.make({"item_groups": [shop.PARENT_GROUP]}, options={} if quality == "standard" else {"quality": quality})
			if picture.call_args:
				seen[quality] = picture.call_args.kwargs
		self.assertEqual(seen["standard"]["max_side"], book.CARD_PICTURE[0])
		self.assertLess(seen["light"]["max_side"], seen["standard"]["max_side"])
		self.assertLess(seen["light"]["quality"], seen["standard"]["quality"])
		self.assertGreater(seen["print"]["max_side"], seen["standard"]["max_side"])
		self.assertGreater(seen["print"]["quality"], seen["standard"]["quality"])
		self.assertFalse(seen["print"]["small_copy"], "a printer is given the picture, not the shop's small copy")
		self.assertTrue(seen["light"]["small_copy"])

	def test_a_used_unit_says_so_on_its_card_and_a_new_one_says_nothing(self):
		first = frappe.db.get_value("Website Item", {"item_code": shop.FIRST}, "name")
		frappe.db.set_value("Website Item", first, "item_condition", "Second-hand", update_modified=False)
		try:
			data = self.make({"item_groups": [shop.PARENT_GROUP]})
			html = book_pdf.render_html(data)
		finally:
			frappe.db.set_value("Website Item", first, "item_condition", "New", update_modified=False)
		products = self.products(data)
		self.assertEqual(products[shop.FIRST].condition, "Second-hand")
		self.assertEqual(products[shop.SECOND].condition, "")
		self.assertEqual(html.count('class="state"'), 1, "one card, the used one")

	# --- the covers --------------------------------------------------------------------------------

	def test_the_cover_style_is_a_class_of_the_cover_and_the_first_one_stays_the_default(self):
		self.assertIn('<section class="cover cover-solid">', book_pdf.render_html(self.make()))
		for cover in ("band", "minimal"):
			data = self.make({"item_groups": [shop.PARENT_GROUP]}, {"cover": cover})
			self.assertEqual(data.cover, cover)
			self.assertIn(f'<section class="cover cover-{cover}">', book_pdf.render_html(data))

	def test_every_cover_prints_the_title_and_the_name_and_leaves_the_pages_where_they_were(self):
		pages = {}
		for cover in ("solid", "band", "minimal"):
			data = self.make({"item_groups": [shop.PARENT_GROUP]}, {"cover": cover})
			pdf, pages[cover] = self.pdf(data)
			first = self.page_texts(pdf)[0]
			self.assertIn("Catalogue 2027", first, cover)
			self.assertIn("Alpine Distribution SA", first, cover)
			self.assertIn("orders@alpine.example", first, cover)
		self.assertEqual(len(set(pages.values())), 1, f"a cover is one page whatever its style: {pages}")

	# --- one product a page ------------------------------------------------------------------------

	def test_a_sheet_is_a_page_a_product_with_its_long_text_and_no_grid(self):
		first = frappe.db.get_value("Website Item", {"item_code": shop.FIRST}, "name")
		before = frappe.db.get_value("Website Item", first, "web_long_description")
		frappe.db.set_value("Website Item", first, "web_long_description", "<p>The <b>long</b> text of the first product.</p>", update_modified=False)
		try:
			data = self.make({"item_groups": [shop.PARENT_GROUP, shop.OTHER_GROUP]}, {"layout": "sheet"})
			html = book_pdf.render_html(data)
		finally:
			frappe.db.set_value("Website Item", first, "web_long_description", before, update_modified=False)
		self.assertEqual(html.count('<article class="leaf">'), data.product_count, "a sheet for each product")
		self.assertNotIn('class="cards"', html)
		self.assertEqual(self.products(data)[shop.FIRST].leaf.text, "The long text of the first product.")
		self.assertIn("The long text of the first product.", html)
		self.assertIn('<body class="layout-sheet">', html)

	def test_the_sheet_of_a_model_lists_its_variants_with_their_own_selling_price(self):
		model = self.products(self.make({"items": [shop.MODEL]}, {"layout": "sheet"}))[shop.MODEL]
		leaf = model.leaf
		self.assertEqual(leaf.columns, [shop.ATTRIBUTE])
		by_size = {variant.cells[0]: variant for variant in leaf.variants}
		self.assertEqual(set(by_size), {"Small", "Large"})
		self.assertEqual(by_size["Small"].price, self.selling(48))
		self.assertEqual(by_size["Large"].price, self.selling(72))
		self.assertEqual(leaf.more, 0)

	def test_a_plain_product_has_no_variants_on_its_sheet_and_the_other_layouts_carry_no_sheet_data(self):
		products = self.products(self.make({"items": [shop.FIRST]}, {"layout": "sheet"}))
		self.assertEqual(products[shop.FIRST].leaf.variants, [])
		self.assertIsNone(self.products(self.make({"items": [shop.FIRST]}))[shop.FIRST].leaf, "a grid does not pay for it")

	def test_a_sheet_never_prints_what_the_reseller_pays_or_the_shops_price(self):
		data = self.make({"item_groups": [shop.PARENT_GROUP, shop.OTHER_GROUP], "items": [shop.MODEL]}, {"layout": "sheet", "order_form": True})
		html = book_pdf.render_html(data)
		for number in ("80.00", "40.00", "30.00", "48.00", "72.00", "100.00", "50.00", "60.00", "90.00"):
			with self.subTest(number=number):
				self.assertNotIn(number, html)
		self.assertIn(self.selling(72), html, "the selling price of a variant is printed")

	def test_a_sheet_without_prices_has_no_price_column_in_its_variants(self):
		html = book_pdf.render_html(self.make({"items": [shop.MODEL]}, {"layout": "sheet", "prices": "none"}))
		leaf = html.split('class="leaf-variants"')[1].split("</table>")[0]
		self.assertNotIn('class="r"', leaf)

	def test_the_pdf_of_sheets_has_a_page_a_product(self):
		data = self.make({"item_groups": [shop.PARENT_GROUP]}, {"layout": "sheet"})
		pdf, pages = self.pdf(data)
		texts = self.page_texts(pdf)
		names = [product.name for section in data.sections for product in section.products]
		for name in names:
			# a long name wraps in the column beside the picture: read the page as one line of words
			holders = [number for number, text in enumerate(texts, start=1) if number > 2 and name in " ".join(text.split())]
			self.assertEqual(len(holders), 1, f"{name} is on one page of its own")
		self.assertGreaterEqual(pages, 2 + len(names))

	# --- the order form ----------------------------------------------------------------------------

	def test_a_catalogue_without_an_order_form_has_none(self):
		data = self.make()
		self.assertIsNone(data.order_form)
		html = book_pdf.render_html(data)
		self.assertNotIn("order-form", html)
		self.assertNotIn('class="order"', html)

	def test_an_order_form_closes_the_catalogue_with_every_product_a_blank_quantity_and_the_resellers_details(self):
		data = self.make({"item_groups": [shop.PARENT_GROUP, shop.OTHER_GROUP]}, {"order_form": True})
		self.assertEqual(data.order_form.title, "Order form")
		html = book_pdf.render_html(data)
		form = html.split('<section class="order">')[1]
		self.assertEqual(form.count('<td class="q"></td>'), data.product_count, "a blank quantity for each product")
		for reference in self.products(data):
			self.assertIn(f'<td class="ref">{reference}</td>', form)
		self.assertIn("orders@alpine.example", form, "who the form goes back to")
		self.assertIn(self.selling(80), form, "the selling price is on the form")
		self.assertEqual(form.count('<td class="r t"></td>'), data.product_count, "and a blank total")

	def test_the_order_form_never_carries_what_the_reseller_pays_or_the_shops_price(self):
		data = self.make({"item_groups": [shop.PARENT_GROUP, shop.OTHER_GROUP], "items": [shop.MODEL]}, {"order_form": True})
		form = book_pdf.render_html(data).split('<section class="order">')[1]
		for number in ("80.00", "40.00", "30.00", "48.00", "72.00", "100.00", "50.00", "60.00", "90.00"):
			with self.subTest(number=number):
				self.assertNotIn(number, form)

	def test_the_order_form_of_a_catalogue_without_prices_has_no_price_or_total_column(self):
		data = self.make({"item_groups": [shop.PARENT_GROUP]}, {"order_form": True, "prices": "none"})
		form = book_pdf.render_html(data).split('<section class="order">')[1]
		self.assertNotIn('class="r"', form)
		self.assertNotIn('class="r t"', form)
		self.assertNotIn("Total", form)
		self.assertEqual(form.count('<td class="q"></td>'), data.product_count)

	def test_the_qr_of_the_order_form_leads_to_the_resellers_own_site_and_only_when_they_have_one(self):
		self.assertIsNone(self.make({"item_groups": [shop.PARENT_GROUP]}, {"order_form": True}).order_form.qr)
		answer = brand_api.save_my_brand({"contact_website": "alpine.example"})
		self.assertTrue(answer["ok"], answer)
		self.payload = brand_api._payload(shop.CUSTOMER)
		data = self.make({"item_groups": [shop.PARENT_GROUP]}, {"order_form": True})
		self.assertTrue(data.order_form.qr.startswith("data:image/"))
		self.assertIn("alpine.example", data.order_form.caption)
		with mock.patch.object(book.qr, "qr_data_uri", return_value="data:image/png;base64,AA") as made:
			book.build_book(shop.CUSTOMER, self.payload, "", "t", selection.clean_selection({"item_groups": [shop.PARENT_GROUP]}), {**OPTIONS, "order_form": True})
		made.assert_called_once_with("https://alpine.example")

	def test_the_contents_lists_the_order_form_with_its_page_after_the_sections(self):
		data = self.make({"item_groups": [shop.PARENT_GROUP, shop.OTHER_GROUP]}, {"order_form": True})
		count = len(data.sections)
		self.assertIn("000", book_pdf.render_html(data).split('<section class="toc">')[1].split("</section>")[0])
		pages = list(range(3, 3 + count)) + [9]
		toc = book_pdf.render_html(data, numbers=pages).split('<section class="toc">')[1].split("</section>")[0]
		self.assertIn('<a href="#order-form"><span class="t">Order form</span>', toc)
		self.assertIn('<span class="n">9</span>', toc)
		self.assertEqual(toc.count('class="n"'), count + 1)

	def test_the_order_form_is_the_last_bookmark_and_the_contents_says_on_which_page_it_is(self):
		data = self.make({"item_groups": [shop.PARENT_GROUP]}, {"order_form": True})
		pdf, pages = self.pdf(data)
		texts = self.page_texts(pdf)
		form_page = next(number for number, text in enumerate(texts, start=1) if number > 2 and "Order form" in text.splitlines())
		self.assertGreater(form_page, 2)
		import re

		self.assertRegex(texts[1], re.compile(r"Order form\s+" + str(form_page) + r"(?!\d)"))
		self.assertIn("orders@alpine.example", texts[form_page - 1])

	# --- the new arrivals ----------------------------------------------------------------------------

	def new_for(self, days, **created):
		"""The window of Webshop Settings, and the date each product was published (a number of days ago)."""
		before = frappe.db.get_single_value("Webshop Settings", "catalogue_new_days")
		frappe.db.set_single_value("Webshop Settings", "catalogue_new_days", days)
		frappe.clear_document_cache("Webshop Settings", "Webshop Settings")
		self.addCleanup(lambda: (frappe.db.set_single_value("Webshop Settings", "catalogue_new_days", before or 0), frappe.clear_document_cache("Webshop Settings", "Webshop Settings")))
		for code, ago in created.items():
			name = frappe.db.get_value("Website Item", {"item_code": code}, "name")
			previous = frappe.db.get_value("Website Item", name, "creation")
			frappe.db.set_value("Website Item", name, "creation", frappe.utils.add_days(frappe.utils.now_datetime(), -ago), update_modified=False)
			self.addCleanup(frappe.db.set_value, "Website Item", name, "creation", previous, update_modified=False)

	def test_a_product_published_in_the_shops_window_is_a_new_arrival_and_the_others_are_not(self):
		self.new_for(30, **{shop.FIRST: 2, shop.SECOND: 100})
		data = self.make({"item_groups": [shop.PARENT_GROUP]})
		products = self.products(data)
		self.assertTrue(products[shop.FIRST].is_new)
		self.assertFalse(products[shop.SECOND].is_new)
		fresh = [code for code, product in products.items() if product.is_new]
		self.assertIn(shop.FIRST, fresh)
		self.assertEqual(book_pdf.render_html(data).count('class="state fresh"'), len(fresh), "a tag for each one, and only for them")

	def test_with_no_window_nothing_is_a_new_arrival(self):
		self.new_for(0, **{shop.FIRST: 1})
		data = self.make({"item_groups": [shop.PARENT_GROUP]})
		self.assertFalse(any(product.is_new for product in self.products(data).values()))
		self.assertNotIn('class="state fresh"', book_pdf.render_html(data))

	def test_a_used_unit_is_not_called_a_new_arrival(self):
		self.new_for(30, **{shop.FIRST: 1})
		first = frappe.db.get_value("Website Item", {"item_code": shop.FIRST}, "name")
		frappe.db.set_value("Website Item", first, "item_condition", "Second-hand", update_modified=False)
		try:
			product = self.products(self.make({"item_groups": [shop.PARENT_GROUP]}))[shop.FIRST]
		finally:
			frappe.db.set_value("Website Item", first, "item_condition", "New", update_modified=False)
		self.assertEqual(product.condition, "Second-hand")
		self.assertFalse(product.is_new)

	def mark_up(self, *rules):
		answer = brand_api.save_my_brand(
			{"markup_rules": [{"rule_type": kind, "target": target, "markup_percent": percent} for kind, target, percent in rules]}
		)
		self.assertTrue(answer["ok"], answer)
		self.payload = brand_api._payload(shop.CUSTOMER)

	def test_a_markup_of_their_own_is_the_price_printed_for_what_it_names(self):
		# FIRST is in the child group, SECOND in the parent, THIRD elsewhere (brand B): 80, 40 and 30 on their list
		self.mark_up(("Item Group", shop.PARENT_GROUP, 50), ("Item", shop.THIRD, 100))
		products = self.products(self.make())
		self.assertEqual(products[shop.FIRST].price, self.selling(80, 50), "the parent's rule reaches the child group")
		self.assertEqual(products[shop.SECOND].price, self.selling(40, 50))
		self.assertEqual(products[shop.THIRD].price, self.selling(30, 100), "a rule on the product itself")

	def test_a_models_from_price_is_marked_up_as_the_model_is(self):
		self.mark_up(("Item", shop.MODEL, 100))
		model = self.products(self.make({"items": [shop.MODEL]}))[shop.MODEL]
		self.assertEqual(model.price, self.selling(48, 100))

	def test_what_the_reseller_pays_is_still_nowhere_when_rules_are_set(self):
		self.mark_up(("Brand", shop.BRAND_A, 10), ("Item Group", shop.OTHER_GROUP, 75))
		data = self.make({"item_groups": [shop.PARENT_GROUP, shop.OTHER_GROUP]})
		haystack = frappe.as_json(data) + book_pdf.render_html(data)
		for number in ("80.00", "40.00", "30.00", "100.00", "50.00", "60.00"):
			with self.subTest(number=number):
				self.assertNotIn(number, haystack)
		self.assertIn(self.selling(80, 10), haystack)
		self.assertIn(self.selling(30, 75), haystack)

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
