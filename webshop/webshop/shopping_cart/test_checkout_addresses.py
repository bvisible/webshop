#//// Neoffice — added file (no upstream equivalent).
#//// Covers the two endpoints the checkout gained during the 2026-08 reliability
#//// pass: the address book behind the address picker, and the batched gift-card
#//// lookup that replaced an N+1 chain of calls.
#////
#//// These tests call the endpoints through a real portal session (User ->
#//// Portal User -> Customer, the chain get_party resolves), never a local copy
#//// of their logic: a test that re-implements what it checks passes even when
#//// the endpoint is broken.

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.shopping_cart.cart import are_gift_card_items, get_customer_addresses

TEST_CUSTOMER = "_Test Checkout Address Customer"
OTHER_CUSTOMER = "_Test Checkout Other Customer"
TEST_USER = "test-checkout-address@example.com"
TITLES = ("_TCA Domicile", "_TCA Chalet", "_TCA Bureau", "_TCA Ancienne", "_TCA Voisin")


class TestCustomerAddresses(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.drop_fixtures()

		if not frappe.db.exists("User", TEST_USER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": TEST_USER,
					"first_name": "Checkout",
					"last_name": "Address",
					"user_type": "Website User",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)

		for name in (TEST_CUSTOMER, OTHER_CUSTOMER):
			customer = frappe.get_doc(
				{
					"doctype": "Customer",
					"customer_name": name,
					"customer_type": "Individual",
					"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
					"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
				}
			)
			if name == TEST_CUSTOMER:
				# The chain get_party() walks to resolve the logged-in shopper.
				customer.append("portal_users", {"user": TEST_USER})
			customer.insert(ignore_permissions=True)

		# address_type "Office" is the whole point of the endpoint: the previous
		# billing-only / shipping-only queries dropped it, hiding the address.
		cls.billing = cls.make_address("_TCA Domicile", "Billing", is_primary=1)
		cls.shipping = cls.make_address("_TCA Chalet", "Shipping", is_shipping=1)
		cls.office = cls.make_address("_TCA Bureau", "Office")
		cls.disabled = cls.make_address("_TCA Ancienne", "Billing", disabled=1)
		cls.foreign = cls.make_address("_TCA Voisin", "Billing", customer=OTHER_CUSTOMER)

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		cls.drop_fixtures()
		super().tearDownClass()

	@classmethod
	def make_address(cls, title, address_type, customer=TEST_CUSTOMER, **flags):
		doc = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": title,
				"address_type": address_type,
				"address_line1": f"Rue {title}",
				"city": "Lausanne",
				"pincode": "1003",
				"country": frappe.db.get_value("Country", "Switzerland") or "Switzerland",
				"is_primary_address": flags.get("is_primary", 0),
				"is_shipping_address": flags.get("is_shipping", 0),
				"disabled": flags.get("disabled", 0),
				"links": [{"link_doctype": "Customer", "link_name": customer}],
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	@classmethod
	def drop_fixtures(cls):
		for title in TITLES:
			for name in frappe.get_all("Address", filters={"address_title": title}, pluck="name"):
				frappe.delete_doc("Address", name, force=True, ignore_permissions=True)
		for name in (TEST_CUSTOMER, OTHER_CUSTOMER):
			if frappe.db.exists("Customer", name):
				frappe.delete_doc("Customer", name, force=True, ignore_permissions=True)

	def book(self):
		"""The endpoint itself, read as the logged-in shopper would."""
		frappe.set_user(TEST_USER)
		try:
			return get_customer_addresses()
		finally:
			frappe.set_user("Administrator")

	def test_office_address_is_returned(self):
		"""An 'Office' address is neither Billing nor Shipping, and used to vanish."""
		self.assertIn(self.office, [a["name"] for a in self.book()])

	def test_all_three_active_addresses_are_returned(self):
		names = [a["name"] for a in self.book()]
		self.assertEqual(sorted(names), sorted([self.billing, self.shipping, self.office]))

	def test_disabled_address_is_hidden(self):
		self.assertNotIn(self.disabled, [a["name"] for a in self.book()])

	def test_other_customers_address_is_not_leaked(self):
		self.assertNotIn(self.foreign, [a["name"] for a in self.book()])

	def test_primary_address_comes_first(self):
		"""Ordering matters: it is the address the quotation defaults to."""
		book = self.book()
		self.assertEqual(book[0]["name"], self.billing)
		self.assertEqual(book[0]["is_primary_address"], 1)

	def test_fields_needed_to_prefill_the_form_are_present(self):
		"""Selecting a card must fill the form without a second round trip."""
		card = next(a for a in self.book() if a["name"] == self.office)
		for field in (
			"title", "address_type", "address_line1", "address_line2",
			"city", "state", "pincode", "country", "phone", "email_id",
			"is_primary_address", "is_shipping_address",
		):
			self.assertIn(field, card, f"{field} missing: the picker would blank that input")
		self.assertEqual(card["title"], "_TCA Bureau")

	def test_flags_are_integers(self):
		"""The client compares them, so a None would silently read as falsy."""
		for card in self.book():
			self.assertIsInstance(card["is_primary_address"], int)
			self.assertIsInstance(card["is_shipping_address"], int)

	def test_guest_gets_no_address_book(self):
		frappe.set_user("Guest")
		try:
			self.assertEqual(get_customer_addresses(), [])
		finally:
			frappe.set_user("Administrator")


class TestAreGiftCardItems(FrappeTestCase):
	UNKNOWN = "_Test Nonexistent Gift Card Item"

	def test_empty_input_returns_empty_map(self):
		self.assertEqual(are_gift_card_items([]), {})
		self.assertEqual(are_gift_card_items(None), {})

	def test_accepts_a_json_string(self):
		"""frappe.call serialises the list, so the endpoint receives a string."""
		self.assertEqual(are_gift_card_items(f'["{self.UNKNOWN}"]'), {self.UNKNOWN: False})

	def test_unknown_item_is_not_a_gift_card(self):
		"""An item with no Website Item must answer False, never raise."""
		self.assertEqual(are_gift_card_items([self.UNKNOWN]), {self.UNKNOWN: False})

	def test_every_requested_code_gets_an_answer(self):
		"""The caller indexes the map by item_code; a missing key would read undefined."""
		codes = [f"{self.UNKNOWN} {i}" for i in range(3)]
		self.assertEqual(sorted(are_gift_card_items(codes)), sorted(codes))

	def test_duplicates_are_collapsed(self):
		self.assertEqual(len(are_gift_card_items([self.UNKNOWN, self.UNKNOWN])), 1)

	def test_blank_codes_are_dropped(self):
		self.assertEqual(are_gift_card_items(["", None, self.UNKNOWN]), {self.UNKNOWN: False})

	def test_oversized_list_is_capped(self):
		"""Never trust the browser on the size of the list."""
		codes = [f"{self.UNKNOWN} {i}" for i in range(250)]
		self.assertLessEqual(len(are_gift_card_items(codes)), 200)

	def test_real_website_item_is_reported(self):
		"""A published Website Item answers with its actual is_gift_card flag."""
		row = frappe.get_all("Website Item", fields=["item_code", "is_gift_card"], limit=1)
		if not row:
			self.skipTest("no Website Item on this site")
		result = are_gift_card_items([row[0].item_code])
		self.assertEqual(result[row[0].item_code], bool(row[0].is_gift_card))
