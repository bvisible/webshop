# //// Neoffice — added file (no upstream equivalent).
"""The product sheet: which product, what it says, in whose name, and the PDF itself.

Real customers, a real published item priced on the shop's list, a model with two variants, a real picture
in the public files, and an in-memory copy of Webshop Settings (a Single survives the rollback). The PDF is
made by the shared Chromium where the bench has one; a bench without it skips those tests, and says so.
The tests that build a sheet need the fork's pricing (`needs_fork`): CI, on stock ERPNext, skips them.
"""

import inspect
import io
import re
import unittest
from unittest import mock

import frappe
from erpnext.utilities.product import get_price
from frappe.tests.utils import FrappeTestCase
from frappe.utils import fmt_money
from PIL import Image

from webshop.webshop.catalogue import access, api, sheet, sheet_api
from webshop.webshop.catalogue.pdf import chromium_available
from webshop.webshop.doctype.website_item.website_item import make_website_item
from webshop.webshop.tests.utils import (
	PREFIX,
	ensure_shop_settings,
	make_test_item,
	portal_customer,
	root_customer_group,
	selling_price_list,
)

GROUP = f"{PREFIX} Sheet Resellers"
OTHER_GROUP = f"{PREFIX} Sheet Consumers"
USER, CUSTOMER = "wstest-sheet-a@example.com", f"{PREFIX} Sheet Shop A"
OUT_USER, OUT_CUSTOMER = "wstest-sheet-out@example.com", f"{PREFIX} Sheet Outsider"
ITEM = f"{PREFIX} Sheet Shirt"
MODEL = f"{PREFIX} Sheet Model"
ATTRIBUTE = f"{PREFIX} Sheet Colour"
NASTY_NAME = "Chemise <script>alert(1)</script> & \"quotes\""
PICTURE = "wstest-sheet-picture.png"


def digits(text):
	return re.sub(r"\D", "", text or "")


# The page prices a product through `get_price(..., warehouse=...)`, which only our ERPNext fork has: on stock
# ERPNext `product_info` raises a TypeError, so the product page and the sheet made of it cannot be built.
# CI runs on stock ERPNext on purpose; the tests that build a sheet say so instead of failing, and run on the
# clone of the real site (a skip is "not run", never "passed": read the count).
ON_FORK = "warehouse" in inspect.signature(get_price).parameters
needs_fork = unittest.skipUnless(ON_FORK, "needs the bvisible/erpnext fork (warehouse pricing)")


class TestProductSheet(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.settings_written = ensure_shop_settings()
		cls.purge_fixtures()
		for name in (GROUP, OTHER_GROUP):
			if not frappe.db.exists("Customer Group", name):
				frappe.get_doc(
					{"doctype": "Customer Group", "customer_group_name": name, "parent_customer_group": root_customer_group(), "is_group": 0}
				).insert(ignore_permissions=True)
		for user, customer, group in ((USER, CUSTOMER, GROUP), (OUT_USER, OUT_CUSTOMER, OTHER_GROUP)):
			portal_customer(user, customer)
			frappe.db.set_value("Customer", customer, {"customer_group": group, "disabled": 0, "default_price_list": ""})

		out = io.BytesIO()
		Image.new("RGB", (800, 600), (200, 80, 40)).save(out, "PNG")
		picture = frappe.get_doc(
			{"doctype": "File", "file_name": PICTURE, "content": out.getvalue(), "is_private": 0}
		).insert(ignore_permissions=True)
		cls.picture_url = picture.file_url

		shop_list = selling_price_list()
		item = make_test_item(ITEM, item_name=NASTY_NAME, is_stock_item=0)
		cls._price(item.name, shop_list, 100)
		site = cls._publish(
			item,
			website_image=cls.picture_url,
			web_long_description="<p>First paragraph.</p><script>alert('x')</script><ul><li>One</li><li>Two</li></ul>",
		)
		site.append("website_specifications", {"label": "Weight", "description": "180 g"})
		site.append("website_specifications", {"label": "Material", "description": "<b>Cotton</b>"})
		site.save(ignore_permissions=True)
		cls.item_name = site.name

		if not frappe.db.exists("Item Attribute", ATTRIBUTE):
			frappe.get_doc(
				{
					"doctype": "Item Attribute",
					"attribute_name": ATTRIBUTE,
					"item_attribute_values": [{"attribute_value": v, "abbr": v[:3].upper()} for v in ("Noir", "Blanc")],
				}
			).insert(ignore_permissions=True)
		template = make_test_item(MODEL, item_name="Polo de test", has_variants=1, is_stock_item=0, attributes=[{"attribute": ATTRIBUTE}])
		from erpnext.controllers.item_variant import create_variant

		for colour in ("Noir", "Blanc"):
			variant = create_variant(template.name, {ATTRIBUTE: colour})
			variant.is_stock_item = 0
			variant.insert(ignore_permissions=True)
			cls._price(variant.name, shop_list, 60)
			cls._publish(variant)
		cls.model_name = cls._publish(template).name
		# a rollback at the end of the class would take uncommitted fixtures with it
		frappe.db.commit()

	@staticmethod
	def _publish(item, **fields):
		"""The item's Website Item, made if it is not there yet (saving a variant makes its model's), published."""
		name = frappe.db.get_value("Website Item", {"item_code": item.name}, "name")
		site = frappe.get_doc("Website Item", name) if name else (make_website_item(item) and frappe.get_doc("Website Item", {"item_code": item.name}))
		site.published = 1
		for field, value in fields.items():
			site.set(field, value)
		site.save(ignore_permissions=True)
		return site

	@staticmethod
	def _price(code, price_list, rate):
		if not frappe.db.exists("Item Price", {"item_code": code, "price_list": price_list}):
			frappe.get_doc(
				{"doctype": "Item Price", "item_code": code, "price_list": price_list, "price_list_rate": rate}
			).insert(ignore_permissions=True)

	@classmethod
	def purge_fixtures(cls):
		"""The items, their prices, their Website Items and the picture: made once per run, gone after it."""
		for code in [ITEM, MODEL, *frappe.get_all("Item", filters={"variant_of": MODEL}, pluck="name")]:
			for name in frappe.get_all("Website Item", filters={"item_code": code}, pluck="name"):
				frappe.delete_doc("Website Item", name, force=True, ignore_permissions=True)
			frappe.db.delete("Item Price", {"item_code": code})
		for code in [*frappe.get_all("Item", filters={"variant_of": MODEL}, pluck="name"), MODEL, ITEM]:
			if frappe.db.exists("Item", code):
				frappe.delete_doc("Item", code, force=True, ignore_permissions=True)
		for name in frappe.get_all("File", filters={"file_name": PICTURE}, pluck="name"):
			frappe.delete_doc("File", name, force=True, ignore_permissions=True)
		for customer in (CUSTOMER, OUT_CUSTOMER):
			if frappe.db.exists(api.DOCTYPE, customer):
				for name in frappe.get_all("File", filters={"attached_to_doctype": api.DOCTYPE, "attached_to_name": customer}, pluck="name"):
					frappe.delete_doc("File", name, force=True, ignore_permissions=True)
				frappe.delete_doc(api.DOCTYPE, customer, force=True, ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cls.purge_fixtures()
		super().tearDownClass()

	def setUp(self):
		self.settings = frappe.get_doc("Webshop Settings")
		self.settings.enable_reseller_catalogue = 1
		self.settings.reseller_catalogue_groups = [frappe._dict(allowed_customer_group=GROUP)]
		self.settings.catalogue_credit_text = ""
		patcher = mock.patch.object(access, "shop_settings", return_value=self.settings)
		patcher.start()
		self.addCleanup(patcher.stop)
		self.addCleanup(frappe.set_user, "Administrator")

	def doc(self, name=None):
		return frappe.get_doc("Website Item", name or self.item_name)

	def save_brand(self, **values):
		frappe.set_user(USER)
		defaults = {"brand_name": "Alpine Distribution SA", "primary_colour": "#0b6e4f", "default_markup_percent": 30, "price_rounding": "none", "markup_rules": []}
		answer = api.save_my_brand({**defaults, **values})
		self.assertTrue(answer["ok"], answer)
		return answer

	# --- which product ---------------------------------------------------------------------

	def test_a_published_product_has_a_sheet_by_name_or_by_item_code(self):
		self.assertEqual(sheet.find_item(self.item_name).item_code, ITEM)
		self.assertEqual(sheet.find_item(ITEM).name, self.item_name)

	def test_what_the_shop_does_not_offer_has_no_sheet(self):
		for reference in (None, "", 0, ["x"], "no such product"):
			self.assertIsNone(sheet.find_item(reference), reference)
		frappe.db.set_value("Website Item", self.item_name, "published", 0)
		try:
			self.assertIsNone(sheet.find_item(ITEM))
		finally:
			frappe.db.set_value("Website Item", self.item_name, "published", 1)
		frappe.db.set_value("Website Item", self.item_name, "sold", 1)
		try:
			self.assertIsNone(sheet.find_item(ITEM), "a sold used unit has no sheet")
		finally:
			frappe.db.set_value("Website Item", self.item_name, "sold", 0)

	# --- what the shop's sheet says --------------------------------------------------------

	@needs_fork
	def test_the_shop_s_sheet_says_what_the_page_says(self):
		data = sheet.build_sheet(self.doc())
		self.assertEqual(data.name, NASTY_NAME)
		self.assertEqual(data.reference, ITEM)
		self.assertEqual(digits(data.price.amount), "10000", "the price the page prints, to the cent")
		self.assertEqual(data.availability.tone in ("in", "order", "out"), True)
		self.assertEqual(len(data.pictures), 1)
		self.assertTrue(data.pictures[0].startswith("data:image/jpeg;base64,"))
		self.assertTrue(data.qr.startswith("data:image/png;base64,"))
		# Frappe stores a description with its HTML escaped, so a <script> a merchant typed is text here, and
		# the template escapes it again (test below): the markup of the editor is gone, the list items are lines
		self.assertEqual(data.description[0], "First paragraph.")
		self.assertEqual(data.description[-2:], ["One", "Two"])
		self.assertEqual(data.specs, [("Weight", "180 g"), ("Material", "Cotton")])

	def test_a_price_names_its_currency_even_when_the_site_hides_the_currency_symbol(self):
		# measured on osiris: Global Defaults' "hide currency symbol" is on, `fmt_money` drops the currency
		# and the sheet printed "160.65" for a price in CHF
		from unittest.mock import patch

		with patch("frappe.defaults.get_global_default", return_value="Yes"):
			self.assertEqual(fmt_money(160.65, currency="CHF"), "160.65", "the premise: the site hides it")
			text = sheet.price_text(160.65, "CHF")
		self.assertEqual(text, "CHF 160.65")
		with patch("frappe.defaults.get_global_default", return_value="No"):
			self.assertEqual(sheet.price_text(160.65, "CHF"), fmt_money(160.65, currency="CHF"), "a site that shows it keeps its own format")

	@needs_fork
	def test_a_visitor_s_text_cannot_become_markup(self):
		html = sheet.render_html(sheet.build_sheet(self.doc()))
		self.assertNotIn("<script", html.lower())
		self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
		self.assertNotIn("<script", html.lower(), "not even the description's, which reaches the page as text")
		self.assertTrue(html.lstrip().lower().startswith("<!doctype html>"))

	@needs_fork
	def test_a_model_prints_its_choices_and_no_price_of_its_own_like_its_page(self):
		# the variant selector (Webshop Settings) is what makes a model's page offer its variants
		with mock.patch("webshop.webshop.seo.variants.sells_on_model_page", return_value=True):
			data = sheet.build_sheet(self.doc(self.model_name))
		self.assertEqual(data.reference, MODEL)
		self.assertIsNone(data.price)
		self.assertEqual(len(data.variants), 2)
		self.assertTrue(all(digits(row.price) == "6000" for row in data.variants))

	@needs_fork
	def test_the_stylesheet_carries_the_colour_and_a_footer_that_cannot_break_out(self):
		data = sheet.build_sheet(self.doc())
		data.issuer.name = 'Evil"; } </style><script>alert(1)</script> \\ x'
		data.issuer.colour = "#0b6e4f"
		css = sheet.page_css(data)
		self.assertIn("--brand: #0b6e4f", css)
		self.assertNotIn("</style>", css.lower())
		self.assertNotIn("<script", css.lower())
		footer = re.search(r'@bottom-left \{ content: "([^"]*)"', css)
		self.assertIsNotNone(footer, "the footer is one string literal that nothing could close early")
		self.assertEqual(footer.group(1), sheet.css_string(data.issuer.name))
		data.issuer.colour = "red; background: url(//x)"
		self.assertIn("--brand: #1f2933", sheet.page_css(data), "a colour that is not #rrggbb is never written")

	def test_a_footer_text_is_a_plain_css_string(self):
		self.assertEqual(sheet.css_string('a"b\\c<d>e\nf\x00g'), "a'b/c(d)e f g")

	# --- the reseller's sheet --------------------------------------------------------------

	def reseller_sheet(self, prices="customers"):
		self.save_brand()
		payload = api._payload(access.customer_of(USER))
		return sheet.build_sheet(
			self.doc(), sheet.RESELLER, {"payload": payload, "credit_line": "Supplied by the shop", "prices": prices != "none"}
		)

	@needs_fork
	def test_the_reseller_s_sheet_carries_their_price_and_never_what_they_pay(self):
		frappe.set_user(USER)
		data = self.reseller_sheet()
		self.assertEqual(digits(data.price.amount), "13000", "100 they pay, plus 30 %")
		html = sheet.render_html(data)
		self.assertNotIn(fmt_money(100, currency=frappe.db.get_value("Price List", selling_price_list(), "currency")), html)
		self.assertIn("Alpine Distribution SA", html)
		self.assertIn("--brand: #0b6e4f", html)
		self.assertIn("Supplied by the shop", html, "the supplier's credit line, when it set one")

	@needs_fork
	def test_a_markup_of_their_own_is_the_price_of_the_sheet_of_the_product_it_names(self):
		frappe.set_user(USER)
		self.save_brand(markup_rules=[{"rule_type": "Item", "target": ITEM, "markup_percent": 50}])
		payload = api._payload(access.customer_of(USER))
		data = sheet.build_sheet(self.doc(), sheet.RESELLER, {"payload": payload, "credit_line": "", "prices": True})
		self.assertEqual(digits(data.price.amount), "15000", "100 they pay, plus the 50 % of the rule, not the 30 % of the default")

	@needs_fork
	def test_the_reseller_promises_nothing_that_is_the_supplier_s(self):
		frappe.set_user(USER)
		data = self.reseller_sheet()
		self.assertIsNone(data.availability)
		self.assertEqual(data.promises, [])
		self.assertEqual(data.price.struck, "")

	@needs_fork
	def test_a_sheet_without_prices_prints_none(self):
		frappe.set_user(USER)
		self.assertIsNone(self.reseller_sheet(prices="none").price)

	@needs_fork
	def test_a_reseller_with_a_website_gets_a_qr_to_their_site_not_the_supplier_s(self):
		frappe.set_user(USER)
		self.save_brand(contact_website="www.alpine-distribution.example")
		payload = api._payload(access.customer_of(USER))
		with mock.patch.object(sheet.qr, "qr_data_uri", return_value="data:image/png;base64,QQ==") as qr:
			sheet.build_sheet(self.doc(), sheet.RESELLER, {"payload": payload, "credit_line": "", "prices": True})
		qr.assert_called_once_with("https://www.alpine-distribution.example")

	# --- the doors -------------------------------------------------------------------------

	def test_the_shop_s_door_is_shut_while_the_switch_is_off(self):
		with mock.patch.object(frappe, "get_cached_doc", return_value=frappe._dict(enable_product_sheet=0)):
			with self.assertRaises(frappe.DoesNotExistError):
				sheet_api.product_sheet(self.item_name)

	def test_a_product_that_is_not_offered_has_no_sheet_at_the_door_either(self):
		with mock.patch.object(frappe, "get_cached_doc", return_value=frappe._dict(enable_product_sheet=1)):
			with self.assertRaises(frappe.DoesNotExistError):
				sheet_api.product_sheet("no such product")

	def test_the_reseller_s_door_refuses_those_who_are_not_offered_it(self):
		for user in (OUT_USER, "Guest", "Administrator"):
			frappe.set_user(user)
			with self.subTest(user=user), self.assertRaises(frappe.PermissionError):
				sheet_api.my_product_sheet(self.item_name)

	def test_a_brand_never_saved_gets_no_sheet_that_would_print_the_price_they_pay(self):
		frappe.set_user(USER)
		with self.assertRaises(frappe.ValidationError):
			sheet_api.my_product_sheet(self.item_name)

	@needs_fork
	def test_a_bench_without_chromium_says_so(self):
		with mock.patch.object(sheet_api, "chromium_available", return_value=False):
			with self.assertRaises(frappe.ValidationError):
				sheet_api.make_pdf(sheet.build_sheet(self.doc()))

	def test_the_file_is_named_for_the_product_in_plain_letters(self):
		self.assertEqual(sheet_api._filename("Chaise pliante été / blanche"), "Chaise-pliante-ete-blanche.pdf")
		self.assertEqual(sheet_api._filename('../../etc/passwd"; x'), "etc-passwd-x.pdf")
		self.assertEqual(sheet_api._filename("日本語"), "product-sheet.pdf")

	# --- the PDF itself --------------------------------------------------------------------

	def pdf_text(self, pdf):
		from pypdf import PdfReader

		reader = PdfReader(io.BytesIO(pdf))
		return reader, "\n".join(page.extract_text() for page in reader.pages)

	@needs_fork
	def test_the_shop_s_sheet_is_one_a4_page_with_the_text_in_it(self):
		if not chromium_available():
			self.skipTest("no Chromium on this bench")
		pdf = sheet_api.make_pdf(sheet.build_sheet(self.doc()))
		self.assertTrue(pdf.startswith(b"%PDF"))
		reader, text = self.pdf_text(pdf)
		self.assertEqual(len(reader.pages), 1)
		width, height = (float(reader.pages[0].mediabox.width), float(reader.pages[0].mediabox.height))
		self.assertAlmostEqual(width, 595, delta=2)
		self.assertAlmostEqual(height, 842, delta=2)
		self.assertIn("First paragraph.", text)
		self.assertIn("Weight", text)
		self.assertIn("100", text)

	@needs_fork
	def test_the_reseller_s_pdf_prints_their_price_and_not_the_one_they_pay(self):
		if not chromium_available():
			self.skipTest("no Chromium on this bench")
		frappe.set_user(USER)
		self.save_brand()
		response = sheet_api.my_product_sheet(self.item_name)
		self.assertEqual(response.mimetype, "application/pdf")
		self.assertEqual(response.headers["X-Robots-Tag"], "noindex")
		self.assertIn("no-store", response.headers["Cache-Control"])
		_, text = self.pdf_text(response.data)
		self.assertIn("130", text)
		self.assertNotIn("100.00", text)
		self.assertIn("Alpine Distribution SA", text)
