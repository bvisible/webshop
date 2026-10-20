# //// Neoffice — added file (no upstream equivalent). The PayPal tile's server entry point raises a charge
# //// only against the session's own cart, not any quotation whose name the caller knows (maintenance#1764).

from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.templates.payments import paypal

MODULE = "webshop.templates.payments.paypal"


class TestPaypalOwnsTheCart(FrappeTestCase):
    def test_a_quotation_that_is_not_the_session_cart_is_refused(self):
        mine = frappe._dict(name="QTN-MINE")
        with mock.patch(f"{MODULE}._get_cart_quotation", return_value=mine):
            with mock.patch(f"{MODULE}.frappe.get_doc") as get_doc:
                self.assertRaises(
                    frappe.PermissionError,
                    paypal.create_paypal_payment_request,
                    "QTN-SOMEONE-ELSE",
                )
            # the refusal happens before anything is read or written
            get_doc.assert_not_called()

    def test_no_session_cart_is_refused(self):
        with mock.patch(f"{MODULE}._get_cart_quotation", return_value=None):
            self.assertRaises(
                frappe.PermissionError, paypal.create_paypal_payment_request, "QTN-MINE"
            )

    def test_the_session_cart_gets_past_the_ownership_gate(self):
        mine = frappe._dict(name="QTN-MINE")
        # past the gate the function reads the quotation; make that read fail so the test needs no
        # gateway config. The function's own except turns the failure into an error dict (log_error is
        # silenced so it does not re-enter the mocked get_doc): reaching the dict proves the ownership
        # gate (which sits before the try) let the call through.
        with mock.patch(f"{MODULE}._get_cart_quotation", return_value=mine):
            with mock.patch(f"{MODULE}.frappe.log_error"):
                with mock.patch(
                    f"{MODULE}.frappe.get_doc", side_effect=RuntimeError("past the gate")
                ) as get_doc:
                    result = paypal.create_paypal_payment_request("QTN-MINE")
        get_doc.assert_called_once()
        self.assertEqual(result.get("status"), "error")
        self.assertIn("past the gate", result.get("message", ""))
