# //// Neoffice — added file (no upstream equivalent). The transfer path under upstream's checks (#2056).
"""A portal customer who pays by transfer gets their order and their Payment Request.

ERPNext v15.123.0 reads the order again inside `Payment Request.validate`, for the SESSION user
(`ref_doc.check_permission("read")`). A portal customer (Website User, role Customer) holds no read right on Sales Order
itself, and `ignore_permissions` on the request does not answer that question: the transfer path of the checkout ended
in a 403 at the last click, and the order was rolled back (neoffice-maintenance#2056). The request is now raised with
the shop's rights and handed back as the buyer's.

Run under `upstream_checks`, which put on the fork the lines stock ERPNext has (the CI runs on stock ERPNext, where
they are real). Nothing here calls a gateway: the method row is the module's own, scripted.
"""

from unittest.mock import patch

import frappe

import webshop.webshop.shopping_cart.cart as cart
from webshop.webshop.shopping_cart import offline_payment
from webshop.webshop.shopping_cart.test_loyalty_rights import (
	CUSTOMER,
	ITEM,
	PREFIX,
	USER,
	ShopFixture,
	upstream_checks,
)


class TestATransferOrderOfAPortalCustomer(ShopFixture):
	def place(self, settlement="Transfer before shipping"):
		"""The customer fills the cart and presses the last button, under upstream's checks."""
		row = frappe._dict(settlement=settlement, mode_of_payment=None, payment_terms_template=None)
		frappe.set_user(USER)
		try:
			with (
				upstream_checks(),
				patch.object(offline_payment, "row_for_gateway", return_value=row),
				patch.object(offline_payment, "customer_group_of", return_value=None),
			):
				cart.update_cart(ITEM, 1)
				cart.get_cart_quotation()  # sets the customer's address on the cart, as the cart page does
				answer = offline_payment.place_offline_order(
					self.gateway_account, f"{PREFIX}-{frappe.generate_hash(length=10)}"
				)
				session_user = frappe.session.user
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(session_user, USER, "the session is handed back as it was")
		return answer

	def test_the_order_is_placed_and_held_and_its_request_is_the_buyers(self):
		answer = self.place()

		self.assertEqual(answer.get("status"), "success", answer)
		order = frappe.get_doc("Sales Order", answer["sales_order"])
		self.assertEqual((order.customer, order.docstatus), (CUSTOMER, 1))
		self.assertEqual(order.status, "On Hold", "nothing ships before the money is in")

		request = frappe.get_doc("Payment Request", answer["payment_request"])
		self.assertEqual((request.reference_doctype, request.reference_name), ("Sales Order", order.name))
		self.assertEqual(request.docstatus, 1)
		self.assertEqual(request.owner, USER, "the request stays the buyer's")
		self.assertEqual(request.modified_by, USER)

	def test_an_order_paid_on_account_raises_no_request(self):
		answer = self.place("On account")

		self.assertEqual(answer.get("status"), "success", answer)
		self.assertFalse(answer.get("payment_request"))
		self.assertFalse(
			frappe.db.exists(
				"Payment Request",
				{"reference_doctype": "Sales Order", "reference_name": answer["sales_order"]},
			)
		)
