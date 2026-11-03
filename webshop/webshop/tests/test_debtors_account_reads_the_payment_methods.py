# //// Neoffice — added file (no upstream equivalent).
"""A shop configured by its payment methods table can have customers sign in (maintenance#1571)."""

import unittest
from unittest import mock

import frappe

from webshop.webshop.shopping_cart import cart


def settings(field=None, rows=()):
	return frappe._dict(
		payment_gateway_account=field,
		company="_Test Company",
		payment_methods=[frappe._dict(payment_gateway_account=row) for row in rows],
	)


class TestTheDebtorsAccountReadsThePaymentMethods(unittest.TestCase):
	def test_the_single_field_still_comes_first(self):
		self.assertEqual(cart.gateway_account_of(settings("GA-field", ["GA-row"])), "GA-field")

	def test_the_first_row_that_names_a_gateway_account_answers_when_the_field_is_empty(self):
		self.assertEqual(cart.gateway_account_of(settings(None, [None, "GA-1", "GA-2"])), "GA-1")

	def test_a_shop_with_neither_is_still_refused(self):
		self.assertIsNone(cart.gateway_account_of(settings(None, [None, None])))
		with self.assertRaises(frappe.ValidationError):
			cart.get_debtors_account(settings(None, [None]))

	def test_the_sign_in_hook_no_longer_refuses_a_shop_configured_by_the_table(self):
		"""This is what every customer of a new shop met: « Payment Gateway Account not set » on the login page."""
		with (
			mock.patch.object(frappe, "get_doc", return_value=frappe._dict(currency="CHF")),
			mock.patch.object(cart, "get_account_name", return_value="Debtors (CHF) - T"),
		):
			self.assertEqual(cart.get_debtors_account(settings(None, [None, "GA-1"])), "Debtors (CHF) - T")
