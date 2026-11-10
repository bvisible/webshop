# //// Neoffice — added file (no upstream equivalent).
"""The pay-on-invoice method finds its template when its row names no path (maintenance#2173).

A gateway's template and JSON were looked up by the first word of its name, `facture.html`. The invoice gateway's files are
webshopsi.html and webshopsi.json, and only the rows the webshopsi migration rewrote carried their path: a method added by hand
in the desk had a tile with no pay button.
"""

from pathlib import Path
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.templates.pages import checkout
from webshop.webshop.utils import utils

PAYMENTS = Path(utils.__file__).resolve().parents[2] / "templates" / "payments"


class TestTheInvoiceMethodFindsItsTemplate(FrappeTestCase):
	def test_the_invoice_gateway_is_known_by_its_settings_whatever_its_name(self):
		for name in ("facture", "rechnung", "invoice"):
			with self.subTest(name=name):
				gateway = frappe._dict(gateway_settings="WebshopSI Settings")
				self.assertEqual(utils.default_payment_template(gateway, name), "webshopsi")

	def test_another_gateway_keeps_the_first_word_of_its_name(self):
		for settings, name in (("Stripe Settings", "stripe"), (None, "on"), ("Twint Bridge Settings", "twint")):
			with self.subTest(name=name):
				self.assertEqual(utils.default_payment_template(frappe._dict(gateway_settings=settings), name), name)

	def test_its_files_exist(self):
		self.assertTrue((PAYMENTS / "webshopsi.html").is_file())
		self.assertTrue((PAYMENTS / "webshopsi.json").is_file())

	def test_a_method_added_by_hand_without_a_path_gets_the_invoice_template_and_its_configuration(self):
		account = frappe._dict(name="Facture - CHF", payment_gateway="Facture", currency="CHF")
		gateway = frappe._dict(name="Facture", gateway="Facture", gateway_settings="WebshopSI Settings")
		method = frappe._dict(template_path=None)  # added by hand in the desk

		made = {"Payment Gateway Account": account, "Payment Gateway": gateway, "Webshop Payment Method": method}
		real_get_doc = frappe.get_doc

		def get_doc(doctype, *args, **kwargs):
			return made[doctype] if doctype in made else real_get_doc(doctype, *args, **kwargs)

		with (
			mock.patch.object(checkout.frappe, "get_doc", side_effect=get_doc),
			mock.patch.object(checkout.frappe.db, "exists", return_value=False),
			mock.patch.object(utils.frappe, "log_error") as log,
		):
			info = checkout.get_gateway_info("Facture - CHF")

		self.assertEqual(info["template"], "webshopsi")
		self.assertEqual(info["type"], "facture")  # the tile's ids and the page script keep reading the type
		# webshopsi.json is read (an empty configuration on purpose); facture.json, which does not exist, was looked for
		log.assert_not_called()
