# //// Neoffice — added file (no upstream equivalent). erpnext 15.124 made has_website_permission answer False to an
# //// account without the Customer or Supplier role and gave its own order page a fallback on the desk's permission;
# //// the shop's copy of the page had none, so a Website Manager met "Not Permitted" on /order (maintenance#1748).
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.templates.pages import order as order_page


class TestTheOrderPageLetsTheStaffIn(FrappeTestCase):
	def order(self, desk_read):
		doc = MagicMock()
		doc.has_permission.return_value = desk_read
		return doc

	def factor(self, doc, website):
		with (
			patch("frappe.get_doc", return_value=doc),
			patch("frappe.has_website_permission", return_value=website),
			patch(
				"webshop.webshop.shopping_cart.loyalty_rights.customer_redemption_factor", return_value=1.0
			),
			patch("webshop.webshop.shopping_cart.loyalty_rights.customer_of", return_value="C"),
		):
			return order_page.get_redemption_factor("Sales Order", "SO-1")

	def test_a_member_of_the_staff_who_reads_the_order_on_the_desk_gets_the_factor(self):
		self.assertEqual(self.factor(self.order(desk_read=True), website=False), 1.0)

	def test_a_customer_of_the_order_gets_the_factor(self):
		self.assertEqual(self.factor(self.order(desk_read=False), website=True), 1.0)

	def test_nobody_else_does(self):
		with self.assertRaises(frappe.PermissionError):
			self.factor(self.order(desk_read=False), website=False)
