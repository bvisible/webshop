# //// Neoffice — added file (no upstream equivalent). The checkout starts a payment over
# //// POST only (maintenance#1721): Frappe rolls a GET request's transaction back, so a payment
# //// started by opening an address would reach the PSP while the shop kept nothing of it.

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.templates.pages import checkout


class TestTheCheckoutStartsAPaymentOnPostOnly(FrappeTestCase):
	def test_start_cart_intent_refuses_a_get(self):
		allowed = frappe.allowed_http_methods_for_whitelisted_func[checkout.start_cart_intent]
		self.assertEqual(tuple(allowed), ("POST",))

	def test_it_stays_open_to_a_guest(self):
		self.assertIn(checkout.start_cart_intent, frappe.guest_methods)
