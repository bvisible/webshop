# //// Neoffice — added file (no upstream equivalent).
"""The customer's address book in the shop (maintenance#1032).

« Addresses » of the customer's account opened Frappe's web form list, « nothing to show » for a customer
whose addresses the shop or the office made: it now leads to the shop's address book. There the customer
edits the name printed on documents, « to the attention of » and the delivery instructions as well, only
on their own addresses, and a page that does not send those fields does not empty them.
"""

import unittest
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop import api

PREFIX = "PAB1032"
OWN = f"_{PREFIX} Customer"
OTHER = f"_{PREFIX} Other"
PORTAL = "pab1032-portal@yopmail.com"
EXTRA = ("company", "to_the_attention_of", "neo_delivery_instructions")


def _bare_customer(name):
	frappe.db.delete("Customer", {"name": name})
	row = frappe.new_doc("Customer")
	row.update({"customer_name": name, "customer_type": "Company"})
	row.name = name
	row.db_insert()


def _address(customer, street):
	return (
		frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": f"{PREFIX} {street}",
				"address_type": "Billing",
				"address_line1": street,
				"pincode": "1950",
				"city": "Sion",
				"country": "Switzerland",
				"links": [{"link_doctype": "Customer", "link_name": customer}],
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


class TestPortalAddressBook(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# The print and delivery fields are fleet custom fields (neoffice_custom_fields, neoffice_theme):
		# the app's CI site may lack them.
		for field in EXTRA:
			if not frappe.db.has_column("Address", field):
				raise unittest.SkipTest(f"Address.{field} is a fleet custom field this site lacks")
		frappe.set_user("Administrator")
		_bare_customer(OWN)
		_bare_customer(OTHER)
		cls.own = _address(OWN, "Rue Propre")
		cls.other = _address(OTHER, "Rue Voisine")
		# A portal customer: the Customer role, nothing of the desk.
		if not frappe.db.exists("User", PORTAL):
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": PORTAL,
					"first_name": "pab1032-portal",
					"user_type": "Website User",
					"send_welcome_email": 0,
					"roles": [{"role": "Customer"}],
				}
			)
			user.flags.skip_drive_setup = True
			user.insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		frappe.delete_doc("User", PORTAL, force=1, ignore_permissions=True)
		for name in (cls.own, cls.other):
			frappe.delete_doc("Address", name, force=1, ignore_permissions=True)
		frappe.db.delete("Customer", {"name": ("in", (OWN, OTHER))})
		frappe.db.commit()  # nosemgrep: frappe-manual-commit
		super().tearDownClass()

	def _as_customer(self):
		return patch("webshop.webshop.shopping_cart.cart.get_party", return_value=frappe._dict(doctype="Customer", name=OWN))

	def _data(self, **extra):
		data = {
			"address_title": f"{PREFIX} Rue Propre",
			"address_line1": "Rue Propre",
			"pincode": "1950",
			"city": "Sion",
			"country": "Switzerland",
		}
		data.update(extra)
		return data

	def test_the_accounts_addresses_lead_to_the_shops_address_book(self):
		redirects = frappe.get_hooks("website_redirects")
		self.assertIn({"source": "/addresses", "target": "/my_addresses"}, redirects)

	def test_the_print_and_delivery_fields_are_read_and_written(self):
		values = {
			"company": f"{PREFIX} Nom sur les documents",
			"to_the_attention_of": f"{PREFIX} Claire",
			"neo_delivery_instructions": "2e étage, code 1234",
		}
		with self._as_customer():
			api.update_address(self.own, self._data(**values))
			got = api.get_address(self.own)
		for field, value in values.items():
			self.assertEqual(got[field], value)

	def test_a_page_that_does_not_send_them_does_not_empty_them(self):
		with self._as_customer():
			api.update_address(self.own, self._data(company=f"{PREFIX} Kept"))
			api.update_address(self.own, self._data())
		self.assertEqual(frappe.db.get_value("Address", self.own, "company"), f"{PREFIX} Kept")

	def test_another_customers_address_is_refused(self):
		with self._as_customer():
			self.assertRaises(frappe.ValidationError, api.get_address, self.other)
			self.assertRaises(frappe.ValidationError, api.update_address, self.other, self._data(company="x"))
		self.assertFalse(frappe.db.get_value("Address", self.other, "company"))

	def test_an_address_the_office_made_can_be_changed_by_the_customer(self):
		# The Customer role may only write an address it created; the office made this one. Before, the
		# shop answered PermissionError and nothing was saved.
		frappe.set_user(PORTAL)
		with self._as_customer():
			api.update_address(self.own, self._data(to_the_attention_of=f"{PREFIX} Marc"))
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Address", self.own, "to_the_attention_of"), f"{PREFIX} Marc")

	def test_an_address_shared_with_another_account_is_not_changed_from_the_shop(self):
		shared = frappe.get_doc("Address", self.own)
		shared.append("links", {"link_doctype": "Customer", "link_name": OTHER})
		shared.save(ignore_permissions=True)
		try:
			frappe.set_user(PORTAL)
			with self._as_customer():
				self.assertRaises(frappe.ValidationError, api.update_address, self.own, self._data(company="x"))
				self.assertRaises(frappe.ValidationError, api.delete_address, self.own)
		finally:
			frappe.set_user("Administrator")
			shared.reload()
			shared.set("links", [row for row in shared.links if row.link_name != OTHER])
			shared.save(ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Address", self.own))
