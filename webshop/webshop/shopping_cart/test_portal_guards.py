# //// Neoffice — added file (no upstream equivalent).
"""A portal customer keeps what is theirs, and nothing else.

The checkout, the address book and the payment-request button reach three
endpoints that save under the shop's rights, because a portal customer has no
desk rights on addresses or orders. They used to trust the caller entirely:
one rewrote any document of any doctype, one linked an address to any customer,
one answered for any order number. Both directions are pinned here, through a
real portal session (User -> Portal User -> Customer, the chain get_party
resolves): the customer still updates and adds their own addresses, and is
refused on everybody else's.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.templates.pages.checkout import update_address_info
from webshop.webshop.shopping_cart.cart import add_new_address
from webshop.webshop.shopping_cart.offline_payment import open_payment_request
from webshop.webshop.tests.utils import PREFIX, portal_customer

MINE = f"{PREFIX} Guard Customer Mine"
THEIRS = f"{PREFIX} Guard Customer Theirs"
ME = "wstest-guard-mine@yopmail.com"
THEM = "wstest-guard-theirs@yopmail.com"


def _address(customer, title):
	return (
		frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": title,
				"address_type": "Billing",
				"address_line1": "Rue du Test 1",
				"city": "Lausanne",
				"country": frappe.db.get_value("Country", {}, "name") or "Switzerland",
				"links": [{"link_doctype": "Customer", "link_name": customer}],
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


class TestPortalGuards(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		portal_customer(ME, MINE)
		portal_customer(THEM, THEIRS)
		cls.mine = _address(MINE, f"{PREFIX} guard mine")
		cls.theirs = _address(THEIRS, f"{PREFIX} guard theirs")

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		for name in frappe.get_all("Address", filters={"address_title": ["like", f"{PREFIX} guard%"]}, pluck="name"):
			frappe.delete_doc("Address", name, ignore_permissions=True, force=True)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit
		super().tearDownClass()

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_the_customer_updates_their_own_address(self):
		frappe.set_user(ME)
		out = update_address_info("Address", self.mine, {"city": "Genève"})
		self.assertTrue(out["success"])
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Address", self.mine, "city"), "Genève")

	def test_only_address_fields_are_written(self):
		frappe.set_user(ME)
		update_address_info("Address", self.mine, {"city": "Sion", "links": [], "owner": "Administrator"})
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Address", self.mine, "city"), "Sion")
		self.assertTrue(
			frappe.db.exists("Dynamic Link", {"parent": self.mine, "link_doctype": "Customer", "link_name": MINE})
		)

	def test_another_customer_s_address_is_refused(self):
		frappe.set_user(ME)
		with self.assertRaises(frappe.PermissionError):
			update_address_info("Address", self.theirs, {"city": "Nowhere"})
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Address", self.theirs, "city"), "Lausanne")

	def test_any_other_doctype_is_refused(self):
		frappe.set_user(ME)
		with self.assertRaises(frappe.PermissionError):
			update_address_info("User", ME, {"first_name": "Changed"})
		frappe.set_user("Administrator")
		self.assertNotEqual(frappe.db.get_value("User", ME, "first_name"), "Changed")

	def test_a_new_address_goes_to_the_customer_s_own_record_only(self):
		frappe.set_user(ME)
		address = add_new_address(
			{
				"address_title": f"{PREFIX} guard injected",
				"address_type": "Billing",
				"address_line1": "Rue du Test 2",
				"city": "Fribourg",
				"country": frappe.db.get_value("Country", {}, "name") or "Switzerland",
				"is_primary_address": 1,
				"links": [{"link_doctype": "Customer", "link_name": THEIRS}],
			}
		)
		frappe.set_user("Administrator")
		links = {(row.link_doctype, row.link_name) for row in frappe.get_doc("Address", address.name).links}
		self.assertIn(("Customer", MINE), links)
		self.assertNotIn(("Customer", THEIRS), links)
		self.assertNotEqual(frappe.db.get_value("Customer", THEIRS, "customer_primary_address"), address.name)

	def test_a_payment_request_answers_only_the_order_s_customer(self):
		frappe.set_user(ME)
		with self.assertRaises(frappe.PermissionError):
			open_payment_request("SAL-ORD-DOES-NOT-EXIST")
		other_order = frappe.db.get_value("Sales Order", {"customer": ["!=", MINE]}, "name")
		if other_order:
			with self.assertRaises(frappe.PermissionError):
				open_payment_request(other_order)
