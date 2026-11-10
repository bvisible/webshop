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


# //// Neoffice — #2222: the Pay button is a POST form with its CSRF token, as erpnext's order page since v15.124.4.
class TestThePayButtonPostsAForm(FrappeTestCase):
	def test_the_request_is_made_by_a_post_only(self):
		self.assertEqual(tuple(frappe.allowed_http_methods_for_whitelisted_func.get(order.make_payment_request)), ("POST",))

	def test_the_template_posts_a_form_with_its_csrf_token(self):
		import os

		html = open(os.path.join(os.path.dirname(order.__file__), "order.html"), encoding="utf-8").read()
		self.assertIn('id="pay-for-order-form"', html)
		self.assertIn('method="post"', html)
		self.assertIn('name="csrf_token"', html)
		self.assertNotIn("make_payment_request?", html, "a GET link creates a Payment Request for any page")

	def test_the_order_page_hands_its_form_a_token(self):
		name = frappe.db.get_value("Sales Order", {"docstatus": 1}, "name")
		if not name:
			self.skipTest("no submitted Sales Order on this site")
		frappe.set_user("Administrator")
		frappe.form_dict.update({"doctype": "Sales Order", "name": name})
		context = frappe._dict()
		try:
			order.get_context(context)
		finally:
			frappe.form_dict.pop("doctype", None)
			frappe.form_dict.pop("name", None)
		self.assertTrue(context.csrf_token)
