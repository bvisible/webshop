# //// Neoffice — added file (no upstream equivalent). The "Pay" button of the order page asks the shop's own
# //// make_payment_request, which is guarded by the website permission of the order, then made as the system
# //// (erpnext's own asks for a desk right, v15.99.0, GHSA-wpfx-jw7g-7f83).

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.templates.pages import order

PORTAL_USER = "neoffice-order-payment@example.com"


class TestTheOrderPagePaymentButton(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("User", PORTAL_USER):
			frappe.get_doc(
				{"doctype": "User", "email": PORTAL_USER, "first_name": "Order Payment", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		frappe.delete_doc("User", PORTAL_USER, force=True, ignore_permissions=True)
		frappe.db.commit()
		super().tearDownClass()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_it_is_not_open_to_a_guest(self):
		self.assertNotIn(order.make_payment_request, frappe.guest_methods)

	def test_only_an_order_or_an_invoice_can_be_paid(self):
		frappe.set_user(PORTAL_USER)
		for doctype in ("Quotation", "Customer", "User"):
			with self.subTest(doctype=doctype):
				self.assertRaises(frappe.PermissionError, order.make_payment_request, dt=doctype, dn="x")

	def test_a_customer_who_cannot_see_the_order_cannot_pay_it(self):
		name = frappe.db.get_value("Sales Order", {"docstatus": 1}, "name")
		if not name:
			self.skipTest("no submitted Sales Order on this site")
		frappe.set_user(PORTAL_USER)
		self.assertRaises(frappe.PermissionError, order.make_payment_request, dt="Sales Order", dn=name)
		self.assertEqual(frappe.session.user, PORTAL_USER)
