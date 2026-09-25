# //// Neoffice — added file (no upstream equivalent): who may name the document a payment pays.
# //// neoffice-maintenance#747, 2026-09-25.
"""get_payment_template and get_payment_methods are open to visitors and accept a document to pay,
which _document_to_pay loads without checking anything: the booking module calls them from Python
after its own check. Over HTTP the document named must be the caller's; from Python nothing
changes."""

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.templates.pages import checkout

TEMPLATE = "webshop.templates.pages.checkout.get_payment_template"
METHODS = "webshop.templates.pages.checkout.get_payment_methods"


class _Request:
	"""frappe.local.form_dict and frappe.local.request for one call."""

	def __init__(self, cmd=None):
		self.cmd = cmd

	def __enter__(self):
		self.saved = (frappe.local.form_dict, getattr(frappe.local, "request", None))
		frappe.local.form_dict = frappe._dict({"cmd": self.cmd} if self.cmd else {})
		frappe.local.request = SimpleNamespace(path=f"/api/method/{self.cmd}") if self.cmd else None

	def __exit__(self, *args):
		frappe.local.form_dict, frappe.local.request = self.saved


def invoice(readable):
	return SimpleNamespace(has_permission=lambda ptype: readable)


class TestADocumentNamedOverHttp(FrappeTestCase):
	def refused(self, method, readable=False, on_portal=False):
		with (
			_Request(cmd=method),
			patch("frappe.get_doc", return_value=invoice(readable)) as get_doc,
			patch("frappe.has_website_permission", return_value=on_portal),
		):
			try:
				checkout._refuse_foreign_reference(method, "Sales Invoice", "SINV-1")
			except frappe.PermissionError:
				return True
			finally:
				get_doc.assert_called_once_with("Sales Invoice", "SINV-1")
		return False

	def test_someone_elses_document_is_refused(self):
		for method in (TEMPLATE, METHODS):
			with self.subTest(method=method):
				self.assertTrue(self.refused(method))

	def test_the_callers_own_document_is_served(self):
		self.assertFalse(self.refused(METHODS, on_portal=True), "a portal customer's own invoice")
		self.assertFalse(self.refused(METHODS, readable=True), "a desk user who may read it")

	def test_a_python_caller_is_not_second_guessed(self):
		# the booking module checks _may_pay, then calls these from inside its own request
		with _Request(cmd="neoffice_theme.booking.checkout.pay"), patch("frappe.get_doc") as get_doc:
			checkout._refuse_foreign_reference(METHODS, "Sales Invoice", "SINV-1")
		get_doc.assert_not_called()

	def test_no_document_named_checks_nothing(self):
		with _Request(cmd=METHODS), patch("frappe.get_doc") as get_doc:
			checkout._refuse_foreign_reference(METHODS, None, None)
		get_doc.assert_not_called()

	def test_both_endpoints_refuse_before_their_own_error_handling(self):
		"""Their try blocks turn any exception into an answer and an Error Log: the refusal comes first."""
		calls = (
			(TEMPLATE, lambda: checkout.get_payment_template(
				"Stripe - CHF", {"reference_doctype": "Sales Invoice", "reference_docname": "SINV-1"}
			)),
			(METHODS, lambda: checkout.get_payment_methods("Sales Invoice", "SINV-1")),
		)
		for method, call in calls:
			with (
				self.subTest(method=method),
				_Request(cmd=method),
				patch("frappe.get_doc", return_value=invoice(False)),
				patch("frappe.has_website_permission", return_value=False),
				patch("frappe.log_error") as log_error,
				self.assertRaises(frappe.PermissionError),
			):
				call()
			log_error.assert_not_called()
