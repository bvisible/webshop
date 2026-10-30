# //// Neoffice — added file (no upstream equivalent).
"""The reseller's brand page: who may call it, what it keeps, what it refuses, the prices it shows.

Real customers in a tree of customer groups of their own, a real published item priced on two price
lists, and an in-memory copy of Webshop Settings (a Single survives the rollback: a test never writes
to it). The two resellers differ only by the price list of their account, which is the whole point of
the preview: a catalogue must print the figure the customer is charged.
"""

import base64
import io
import re
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase
from PIL import Image

from webshop.webshop.catalogue import access, api
from webshop.webshop.doctype.reseller_catalogue_profile import reseller_catalogue_profile as profile_module
from webshop.webshop.doctype.website_item.website_item import make_website_item
from webshop.webshop.tests.utils import (
	PREFIX,
	ensure_shop_settings,
	make_test_item,
	portal_customer,
	root_customer_group,
	selling_price_list,
)

DOCTYPE = "Reseller Catalogue Profile"
GROUP = f"{PREFIX} Brand Resellers"
OTHER_GROUP = f"{PREFIX} Brand Consumers"
LIST_B = f"{PREFIX} Brand Reseller B"
ITEM = f"{PREFIX} Brand Shirt"
A_USER, A_CUSTOMER = "wstest-brand-a@example.com", f"{PREFIX} Brand Shop A"
B_USER, B_CUSTOMER = "wstest-brand-b@example.com", f"{PREFIX} Brand Shop B"
OUT_USER, OUT_CUSTOMER = "wstest-brand-out@example.com", f"{PREFIX} Brand Outsider"


def digits(text):
	"""'CHF 1'300.00' and '1 300,00 CHF' are the same figure on two sites: compare the digits."""
	return re.sub(r"\D", "", text)


def png_data_url(size=(60, 20)):
	out = io.BytesIO()
	Image.new("RGB", size, (10, 110, 79)).save(out, "PNG")
	return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()


class TestMyBrand(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.settings_written = ensure_shop_settings()
		cls.purge_fixtures()
		for name, parent, is_group in ((GROUP, root_customer_group(), 0), (OTHER_GROUP, root_customer_group(), 0)):
			if not frappe.db.exists("Customer Group", name):
				frappe.get_doc(
					{"doctype": "Customer Group", "customer_group_name": name, "parent_customer_group": parent, "is_group": is_group}
				).insert(ignore_permissions=True)
		for user, customer, group in ((A_USER, A_CUSTOMER, GROUP), (B_USER, B_CUSTOMER, GROUP), (OUT_USER, OUT_CUSTOMER, OTHER_GROUP)):
			portal_customer(user, customer)
			frappe.db.set_value("Customer", customer, {"customer_group": group, "disabled": 0, "default_price_list": ""})

		shop_list = selling_price_list()
		if not frappe.db.exists("Price List", LIST_B):
			frappe.get_doc(
				{
					"doctype": "Price List",
					"price_list_name": LIST_B,
					"selling": 1,
					"enabled": 1,
					"currency": frappe.db.get_value("Price List", shop_list, "currency"),
				}
			).insert(ignore_permissions=True)
		item = make_test_item(ITEM, item_name="Chemise de marque", is_stock_item=0)
		for price_list, rate in ((shop_list, 100), (LIST_B, 80)):
			if not frappe.db.exists("Item Price", {"item_code": item.name, "price_list": price_list}):
				frappe.get_doc(
					{"doctype": "Item Price", "item_code": item.name, "price_list": price_list, "price_list_rate": rate}
				).insert(ignore_permissions=True)
		make_website_item(item)
		website_item = frappe.get_doc("Website Item", {"item_code": item.name})
		website_item.published = 1
		website_item.save(ignore_permissions=True)
		# reseller B pays from its own list; A, with none, falls back to the shop's
		frappe.db.set_value("Customer", B_CUSTOMER, "default_price_list", LIST_B)
		# a rollback at the end of the class would take uncommitted fixtures with it
		frappe.db.commit()

	@classmethod
	def purge_fixtures(cls):
		"""The item, its prices, its Website Item and the second price list: made once per run and
		gone after it. The CI runs a module twice on one site, and a published test item left behind
		would fail the second run ("Already Published") and sit in every later module's catalogue."""
		if frappe.db.exists("Customer", B_CUSTOMER):
			frappe.db.set_value("Customer", B_CUSTOMER, "default_price_list", "")
		for name in frappe.get_all("Website Item", filters={"item_code": ITEM}, pluck="name"):
			frappe.delete_doc("Website Item", name, force=True, ignore_permissions=True)
		frappe.db.delete("Item Price", {"item_code": ITEM})
		if frappe.db.exists("Item", ITEM):
			frappe.delete_doc("Item", ITEM, force=True, ignore_permissions=True)
		frappe.db.delete("Item Price", {"price_list": LIST_B})
		if frappe.db.exists("Price List", LIST_B):
			frappe.delete_doc("Price List", LIST_B, force=True, ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cls.purge_fixtures()
		super().tearDownClass()

	def setUp(self):
		self.purge()
		self.settings = frappe.get_doc("Webshop Settings")
		self.settings.enable_reseller_catalogue = 1
		self.settings.reseller_catalogue_groups = [frappe._dict(allowed_customer_group=GROUP)]
		self.settings.catalogue_credit_text = ""
		patcher = mock.patch.object(access, "shop_settings", return_value=self.settings)
		patcher.start()
		self.addCleanup(patcher.stop)
		self.addCleanup(self.purge)
		self.addCleanup(frappe.set_user, "Administrator")

	def purge(self):
		frappe.set_user("Administrator")
		for customer in (A_CUSTOMER, B_CUSTOMER, OUT_CUSTOMER):
			for name in frappe.get_all("File", filters={"attached_to_doctype": DOCTYPE, "attached_to_name": customer}, pluck="name"):
				frappe.delete_doc("File", name, ignore_permissions=True, force=True)
			if frappe.db.exists(DOCTYPE, customer):
				frappe.delete_doc(DOCTYPE, customer, ignore_permissions=True, force=True)

	# --- who may call it -------------------------------------------------------------------

	def test_a_customer_of_an_allowed_group_gets_a_form_that_starts_from_their_name(self):
		frappe.set_user(A_USER)
		answer = api.get_my_brand()
		self.assertTrue(answer["ok"])
		self.assertFalse(answer["saved"])
		self.assertEqual(answer["customer"], A_CUSTOMER)
		self.assertEqual(answer["values"]["brand_name"], A_CUSTOMER)
		self.assertEqual(answer["values"]["price_rounding"], "0.05")

	def test_a_customer_of_another_group_a_visitor_and_the_administrator_are_refused(self):
		for user in (OUT_USER, "Guest", "Administrator"):
			frappe.set_user(user)
			for call in (api.get_my_brand, lambda: api.save_my_brand({"brand_name": "x"}), api.remove_my_logo, api.preview_prices):
				with self.subTest(user=user), self.assertRaises(frappe.PermissionError):
					call()

	def test_nothing_is_offered_while_the_switch_is_off(self):
		self.settings.enable_reseller_catalogue = 0
		frappe.set_user(A_USER)
		with self.assertRaises(frappe.PermissionError):
			api.get_my_brand()

	# --- what it keeps ---------------------------------------------------------------------

	def test_a_save_writes_the_profile_of_the_session_s_customer_whatever_the_values_say(self):
		frappe.set_user(A_USER)
		answer = api.save_my_brand(
			{"brand_name": "Alpine Distribution SA", "default_markup_percent": "30", "customer": B_CUSTOMER, "logo": "/private/files/x.png"}
		)
		self.assertTrue(answer["ok"])
		self.assertTrue(answer["saved"])
		self.assertTrue(frappe.db.exists(DOCTYPE, A_CUSTOMER))
		self.assertFalse(frappe.db.exists(DOCTYPE, B_CUSTOMER), "a key named customer must not reach another customer")
		self.assertEqual(frappe.db.get_value(DOCTYPE, A_CUSTOMER, "default_markup_percent"), 30)
		self.assertFalse(frappe.db.get_value(DOCTYPE, A_CUSTOMER, "logo"), "the logo is set by the upload, never by a value")

	def test_two_resellers_keep_their_own_brand(self):
		frappe.set_user(A_USER)
		api.save_my_brand({"brand_name": "Shop A", "default_markup_percent": 20})
		frappe.set_user(B_USER)
		api.save_my_brand({"brand_name": "Shop B", "default_markup_percent": 40})
		frappe.set_user(A_USER)
		mine = api.get_my_brand()["values"]
		self.assertEqual((mine["brand_name"], mine["default_markup_percent"]), ("Shop A", 20.0))

	def test_a_value_that_is_refused_is_named_and_nothing_is_saved(self):
		frappe.set_user(A_USER)
		answer = api.save_my_brand({"brand_name": "Fine", "default_markup_percent": "301"})
		self.assertFalse(answer["ok"])
		self.assertEqual(answer["field"], "default_markup_percent")
		self.assertTrue(answer["message"])
		self.assertFalse(frappe.db.exists(DOCTYPE, A_CUSTOMER))

	def test_the_desk_refuses_the_same_values_as_the_page(self):
		doc = frappe.get_doc({"doctype": DOCTYPE, "customer": A_CUSTOMER, "primary_colour": "red"})
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_a_profile_made_at_the_desk_without_a_name_takes_the_customer_s(self):
		doc = frappe.get_doc({"doctype": DOCTYPE, "customer": A_CUSTOMER}).insert(ignore_permissions=True)
		self.assertEqual(doc.brand_name, A_CUSTOMER)
		self.assertEqual(doc.primary_colour, "#1f2933")

	def test_the_credit_line_is_told_to_the_page_and_never_set_by_it(self):
		self.settings.catalogue_credit_text = "Catalogue proposed by the supplier"
		frappe.set_user(A_USER)
		self.assertEqual(api.get_my_brand()["credit_line"], "Catalogue proposed by the supplier")
		api.save_my_brand({"catalogue_credit_text": "nothing", "footer_text": "mine"})
		self.assertEqual(api.get_my_brand()["values"]["footer_text"], "mine")
		self.assertNotIn("catalogue_credit_text", api.get_my_brand()["values"])

	# --- the logo --------------------------------------------------------------------------

	def logo_files(self, customer=A_CUSTOMER):
		return frappe.get_all(
			"File",
			filters={"attached_to_doctype": DOCTYPE, "attached_to_name": customer, "attached_to_field": "logo"},
			fields=["name", "is_private", "file_url"],
		)

	def test_a_logo_is_kept_private_and_the_next_one_replaces_it(self):
		frappe.set_user(A_USER)
		answer = api.upload_my_logo(png_data_url())
		self.assertTrue(answer["ok"])
		self.assertTrue(answer["logo"].startswith("data:image/png;base64,"))
		first = self.logo_files()
		self.assertEqual(len(first), 1)
		self.assertEqual(first[0].is_private, 1)
		api.upload_my_logo(png_data_url((80, 30)))
		second = self.logo_files()
		self.assertEqual(len(second), 1)
		self.assertNotEqual(second[0].name, first[0].name, "the new logo replaces the old file")
		self.assertEqual(frappe.db.get_value(DOCTYPE, A_CUSTOMER, "logo"), second[0].file_url)

	def test_a_logo_belongs_to_the_session_s_customer(self):
		frappe.set_user(A_USER)
		api.upload_my_logo(png_data_url())
		self.assertEqual(len(self.logo_files(B_CUSTOMER)), 0)
		frappe.set_user(B_USER)
		self.assertIsNone(api.get_my_brand()["logo"])

	def test_what_is_not_a_png_or_a_jpeg_is_refused_and_nothing_is_kept(self):
		frappe.set_user(A_USER)
		svg = "data:image/svg+xml;base64," + base64.b64encode(b'<svg xmlns="http://www.w3.org/2000/svg"/>').decode()
		for sent in (svg, "data:image/png;base64,@@@not base64@@@", "", None):
			with self.subTest(sent=str(sent)[:30]):
				answer = api.upload_my_logo(sent)
				self.assertFalse(answer["ok"])
				self.assertEqual(answer["field"], "logo")
		self.assertEqual(self.logo_files(), [])

	def test_a_logo_can_be_removed(self):
		frappe.set_user(A_USER)
		api.upload_my_logo(png_data_url())
		answer = api.remove_my_logo()
		self.assertIsNone(answer["logo"])
		self.assertEqual(self.logo_files(), [])

	# --- the prices ------------------------------------------------------------------------

	def row_of(self, answer):
		rows = [row for row in answer["rows"] if row["item_code"] == ITEM]
		self.assertEqual(len(rows), 1, f"the test item must be among the products shown: {answer['rows']}")
		return rows[0]

	def test_each_reseller_sees_the_price_of_their_own_list_and_the_markup_is_added_by_the_server(self):
		frappe.set_user(A_USER)
		answer_a = api.preview_prices(markup_percent="30", price_rounding="none")
		frappe.set_user(B_USER)
		answer_b = api.preview_prices(markup_percent="30", price_rounding="none")
		row_a, row_b = self.row_of(answer_a), self.row_of(answer_b)
		self.assertEqual(answer_a["price_list"], selling_price_list())
		self.assertEqual(answer_b["price_list"], LIST_B)
		# A pays 100 and sells at 130; B pays 80 and sells at 104
		self.assertEqual((digits(row_a["cost"]), digits(row_a["price"])), ("10000", "13000"))
		self.assertEqual((digits(row_b["cost"]), digits(row_b["price"])), ("8000", "10400"))

	def test_the_preview_uses_the_saved_settings_when_none_are_tried(self):
		frappe.set_user(A_USER)
		api.save_my_brand({"default_markup_percent": 10, "price_rounding": "none"})
		self.assertEqual(digits(self.row_of(api.preview_prices())["price"]), "11000")

	def test_a_preview_asked_to_try_a_value_out_of_bounds_is_refused(self):
		frappe.set_user(A_USER)
		answer = api.preview_prices(markup_percent="301")
		self.assertFalse(answer["ok"])
		self.assertEqual(answer["field"], "default_markup_percent")

	def test_a_preview_reads_the_colours_it_is_asked_about(self):
		frappe.set_user(A_USER)
		ink = api.preview_prices(primary_colour="#ffd400", secondary_colour="#0b6e4f")["ink"]
		self.assertEqual(ink, {"primary": "#111111", "secondary": "#ffffff"})


class TestStartingValues(FrappeTestCase):
	"""What an approved account request already says about the company: a form that starts filled."""

	def test_the_request_fills_the_form_and_a_value_that_does_not_pass_is_left_out(self):
		request = frappe._dict(
			company_name="Alpine Distribution SA",
			tax_id="CHE-123.456.789 TVA",
			website="not a web address at all",
			email="orders@alpine-distribution.example",
			phone="+41 27 000 00 00",
			address_line1="Rue du Rhône",
			house_number="12",
			pincode="1950",
			city="Sion",
			country="Switzerland",
		)
		with mock.patch.object(frappe.db, "exists", return_value=True), mock.patch.object(
			frappe.db, "get_value", return_value=request
		):
			found = profile_module.application_defaults("Any Customer")
		self.assertEqual(found["brand_name"], "Alpine Distribution SA")
		self.assertEqual(found["contact_email"], "orders@alpine-distribution.example")
		self.assertEqual(found["contact_address"], "Rue du Rhône 12\n1950 Sion\nSwitzerland")
		self.assertNotIn("contact_website", found, "a website that is not a web address is left out, not refused")

	def test_without_the_account_request_doctype_there_is_nothing_to_start_from(self):
		with mock.patch.object(frappe.db, "exists", return_value=False):
			self.assertEqual(profile_module.application_defaults("Any Customer"), {})
