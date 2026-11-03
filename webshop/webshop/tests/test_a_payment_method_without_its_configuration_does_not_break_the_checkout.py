# //// Neoffice — added file (no upstream equivalent).
"""A payment method whose JSON is missing answers an empty configuration (maintenance#2173).

A fresh shop met it with its invoice method: `get_gateway_configuration` logged the exception with its text as the TITLE, a path longer
than the 140 characters of a title made `frappe.log_error` itself raise, and the checkout form broke instead of falling back.
"""

from unittest import mock

from frappe.tests.utils import FrappeTestCase

from webshop.webshop.utils import utils


class TestAPaymentMethodWithoutItsConfigurationDoesNotBreakTheCheckout(FrappeTestCase):
	def read(self, path):
		with mock.patch.object(utils.frappe, "get_app_path", return_value=path):
			return utils.get_gateway_configuration("facture")

	def test_a_missing_file_with_a_long_path_answers_empty(self):
		self.assertEqual(self.read("/home/neoffice/frappe-bench/apps/webshop/" + "a" * 160 + "/facture.json"), {})

	def test_the_exception_goes_in_the_message_and_the_title_stays_short(self):
		with mock.patch.object(utils.frappe, "log_error") as log:
			self.assertEqual(self.read("/nowhere/facture.json"), {})
		title, message = log.call_args.args
		self.assertLessEqual(len(title), 140)
		self.assertIn("facture.json", message)
