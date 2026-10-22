# //// Neoffice — added file (no upstream equivalent). Covers the two parts of our
# //// payment path where a mistake costs real money: idempotency (charging a buyer
# //// twice) and who may conclude a payment. Upstream has no payment controller and
# //// therefore no such test (0231a6f96d, 2026-08-29, "cover multi-site and payment
# //// — 94 → 135 tests", title translated from French). The module docstring below
# //// records what the previous version asserted — its own mocks — and why it proved
# //// nothing.
# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

"""Tests for payment_handler.py — idempotency and who may conclude a payment.

These are the two parts of the payment path that can be tested without a
gateway, and the two where a mistake costs real money: charging a buyer twice,
or letting the wrong person mark someone else's payment as settled.

What was here before did not test any of it. Two cases built a MagicMock,
applied the "fix" *inside the test*, and asserted on their own line:

    mock_si = MagicMock()
    mock_si.order_type = "Shopping Cart"
    if hasattr(mock_si, 'order_type'):
        mock_si.order_type = ""
    self.assertEqual(mock_si.order_type, "")   # never touches payment_handler

They passed no matter what the module did — and the clearing of `order_type`
they described exists nowhere in the app (grep: nothing writes it on a Sales
Invoice). A third called `self.skipTest()` unconditionally. Three more skipped
on a custom field from the URY app. Six green tests, one real assertion.
"""

import unittest
from unittest.mock import patch

import frappe

from webshop.controllers.payment_handler import PaymentHandler, _may_conclude

PREFIX = "_WSTEST-"


def fresh_token():
	"""A fresh token per test.

	`custom_idempotency_token` carries a unique index, and something down the
	create path commits — so a token reused across tests survives the rollback
	and the next insert dies on a duplicate key.
	"""
	return f"{PREFIX}{frappe.generate_hash(length=12)}"


def purge_requests():
	"""Delete the requests these tests made, and the intents pointing at them.

	`frappe.db.rollback()` is not enough: the idempotency path calls
	`frappe.log_error`, which commits, and the request inserted just before is
	committed along with it. Left alone, every run added a batch of draft
	Payment Requests to the site's accounting — 17 of them before this was
	noticed.
	"""
	# //// Neoffice — the Stripe receipts the guard tests lay (maintenance#1807).
	frappe.db.delete("Integration Request", {"request_description": ("like", f"{PREFIX}%")})
	names = frappe.get_all(
		"Payment Request",
		filters={"custom_idempotency_token": ("like", f"{PREFIX}%")},
		pluck="name",
	)
	if not names:
		return

	if frappe.db.exists("DocType", "Payment Intent"):
		for intent in frappe.get_all(
			"Payment Intent",
			filters={"reference_doctype": "Payment Request", "reference_name": ("in", names)},
			pluck="name",
		):
			frappe.delete_doc("Payment Intent", intent, force=True, ignore_permissions=True)

	for name in names:
		frappe.delete_doc("Payment Request", name, force=True, ignore_permissions=True)
	frappe.db.commit()


def _payment_request(token, status="Requested", reference_doctype="Quotation", reference_name=None):
	"""A Payment Request carrying an idempotency token.

	Inserted with validation relaxed: what is under test is how the handler
	*finds* this row again, not ERPNext's own creation rules.
	"""
	doc = frappe.new_doc("Payment Request")
	doc.update(
		{
			"payment_request_type": "Inward",
			"reference_doctype": reference_doctype,
			"reference_name": reference_name or frappe.db.get_value("Quotation", {}, "name"),
			"grand_total": 10,
			"currency": "CHF",
			"email_to": "wstest@example.com",
			"custom_idempotency_token": token,
			"status": status,
		}
	)
	doc.flags.ignore_validate = True
	# reference_name is a Dynamic Link: without this, naming an order that does
	# not exist is refused before the handler ever gets to look the token up.
	doc.flags.ignore_links = True
	doc.insert(ignore_permissions=True, ignore_mandatory=True)
	return doc


class TestIdempotence(unittest.TestCase):
	"""One token, one charge — a reloaded payment page must not bill twice."""

	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		purge_requests()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		purge_requests()

	def setUp(self):
		frappe.set_user("Administrator")
		self.handler = PaymentHandler()

	def tearDown(self):
		frappe.db.rollback()
		frappe.set_user("Administrator")

	def test_an_existing_token_returns_the_same_request(self):
		test_token = fresh_token()
		payment_request = _payment_request(test_token)

		result = self.handler.create_payment_request(idempotency_token=test_token)

		self.assertEqual(result.get("status"), "success")
		self.assertEqual(result.get("payment_request_id"), payment_request.name)

	def test_an_order_already_placed_is_reported_as_such(self):
		"""Token already carried through to an order: say so, do not re-charge."""
		test_token = fresh_token()
		_payment_request(test_token, reference_doctype="Sales Order", reference_name="SO-WSTEST-0001")

		result = self.handler.create_payment_request(idempotency_token=test_token)

		self.assertEqual(result.get("status"), "error")
		self.assertEqual(result.get("existing_order"), "SO-WSTEST-0001")

	def test_a_failed_request_is_not_reused(self):
		"""A refused card must leave the buyer able to try again.

		A Failed request is skipped, so the handler carries on to build a new
		one — here with an empty cart, which is why an error comes back. What
		matters is that it is NOT the "using existing payment request" answer.
		"""
		test_token = fresh_token()
		_payment_request(test_token, status="Failed")

		with patch(
			"webshop.controllers.payment_handler._get_cart_quotation", return_value=None
		):
			result = self.handler.create_payment_request(idempotency_token=test_token)

		self.assertEqual(result.get("status"), "error")
		self.assertNotIn("payment_request_id", result)

	def test_an_unknown_token_is_not_matched(self):
		_payment_request(fresh_token())

		with patch(
			"webshop.controllers.payment_handler._get_cart_quotation", return_value=None
		):
			result = self.handler.create_payment_request(idempotency_token="_WSTEST-other")

		self.assertEqual(result.get("status"), "error")
		self.assertNotIn("payment_request_id", result)

	def test_an_empty_cart_is_refused_cleanly(self):
		"""No quotation, no "Devis None not found" traceback in the buyer's face."""
		with patch(
			"webshop.controllers.payment_handler._get_cart_quotation", return_value=None
		):
			result = self.handler.create_payment_request()

		self.assertEqual(result.get("status"), "error")
		self.assertTrue(result.get("message"))


class TestWhoMayConcludeAPayment(unittest.TestCase):
	"""`_may_conclude` decides who may settle a payment request.

	It is reached from a `allow_guest=True` endpoint, so "anyone with the id"
	must not be enough: the id travels in a redirect URL.
	"""

	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		purge_requests()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		purge_requests()

	def setUp(self):
		self.user_before = frappe.session.user
		frappe.set_user("Administrator")
		self.payment_request = _payment_request(fresh_token())
		self.addCleanup(self._restore)

	def _restore(self):
		frappe.set_user(self.user_before)
		frappe.db.rollback()

	def test_the_server_itself_may_conclude(self):
		"""Background jobs and the server-side return page run as Administrator."""
		self.assertTrue(_may_conclude(self.payment_request.name))

	def test_a_guest_may_not_conclude_on_the_id_alone(self):
		frappe.set_user("Guest")

		self.assertFalse(_may_conclude(self.payment_request.name, money_confirmed=False))

	def test_a_guest_may_conclude_when_the_money_is_confirmed(self):
		"""Back from the gateway, the session is not always restored yet.

		A succeeded Payment Intent on THIS request is the proof that stands in
		for the session.
		"""
		if not frappe.db.exists("DocType", "Payment Intent"):
			self.skipTest("Payment Intent doctype not installed")

		intent = frappe.new_doc("Payment Intent")
		intent.update(
			{
				"reference_doctype": "Payment Request",
				"reference_name": self.payment_request.name,
				"status": "succeeded",
			}
		)
		intent.flags.ignore_validate = True
		intent.insert(ignore_permissions=True, ignore_mandatory=True)

		frappe.set_user("Guest")

		self.assertTrue(_may_conclude(self.payment_request.name))

	def test_a_confirmed_intent_on_another_request_does_not_count(self):
		if not frappe.db.exists("DocType", "Payment Intent"):
			self.skipTest("Payment Intent doctype not installed")

		other = _payment_request(fresh_token())
		intent = frappe.new_doc("Payment Intent")
		intent.update(
			{
				"reference_doctype": "Payment Request",
				"reference_name": other.name,
				"status": "succeeded",
			}
		)
		intent.flags.ignore_validate = True
		intent.insert(ignore_permissions=True, ignore_mandatory=True)

		frappe.set_user("Guest")

		self.assertFalse(_may_conclude(self.payment_request.name))

	def test_a_failed_intent_does_not_count(self):
		if not frappe.db.exists("DocType", "Payment Intent"):
			self.skipTest("Payment Intent doctype not installed")

		intent = frappe.new_doc("Payment Intent")
		intent.update(
			{
				"reference_doctype": "Payment Request",
				"reference_name": self.payment_request.name,
				"status": "failed",
			}
		)
		intent.flags.ignore_validate = True
		intent.insert(ignore_permissions=True, ignore_mandatory=True)

		frappe.set_user("Guest")

		self.assertFalse(_may_conclude(self.payment_request.name))

	def test_staff_may_conclude(self):
		"""A System Manager settles a payment by hand when a webhook is lost."""
		user = _test_user("_wstest_staff@example.com", ["System Manager"])
		frappe.set_user(user)

		self.assertTrue(_may_conclude(self.payment_request.name))

	def test_the_buyer_who_opened_the_request_may_fail_it_but_not_conclude_it(self):
		"""The buyer's identity is no proof of payment (maintenance#1807).

		The 22.09 arbitration had accepted it ("opening the request is the buyer's signature"). To FAIL a request
		nothing is paid out, so the identity still serves for that. The party is deliberately someone else, so only
		ownership can carry the failure.
		"""
		buyer = _test_user("_wstest_buyer@example.com", ["Customer"])
		frappe.db.set_value(
			"Payment Request",
			self.payment_request.name,
			{"owner": buyer, "party": "_WSTEST Someone Else"},
		)
		frappe.set_user(buyer)

		self.assertTrue(_may_conclude(self.payment_request.name, money_confirmed=False))
		self.assertFalse(_may_conclude(self.payment_request.name))

	def test_the_customer_of_the_request_may_not_conclude_it_on_their_identity_either(self):
		"""Case 3 (the buyer through their Contact) was the same identity-only door as case 3a."""
		buyer = _test_user("_wstest_contact@example.com", ["Customer"])
		with patch(
			"erpnext.controllers.website_list_for_contact.get_customers_suppliers",
			return_value=(["_WSTEST Someone Else"], []),
		):
			frappe.db.set_value("Payment Request", self.payment_request.name, "party", "_WSTEST Someone Else")
			frappe.set_user(buyer)

			self.assertTrue(_may_conclude(self.payment_request.name, money_confirmed=False))
			self.assertFalse(_may_conclude(self.payment_request.name))

	def test_the_receipt_of_a_stripe_charge_lets_anyone_conclude(self):
		"""The card tile has no Payment Intent: Stripe's answer to the server's charge is the proof, and a guest back
		from the payment has no session to show."""
		self._stripe_receipt(amount=1000)  # the request asks CHF 10
		buyer = _test_user("_wstest_buyer@example.com", ["Customer"])

		frappe.set_user("Guest")
		self.assertTrue(_may_conclude(self.payment_request.name))

		frappe.set_user(buyer)
		self.assertTrue(_may_conclude(self.payment_request.name))

	def test_a_stripe_charge_for_less_than_the_request_does_not_count(self):
		self._stripe_receipt(amount=100)
		frappe.set_user("Guest")
		self.assertFalse(_may_conclude(self.payment_request.name))

	def test_a_stripe_charge_in_another_currency_does_not_count(self):
		self._stripe_receipt(amount=1000, currency="eur")
		frappe.set_user("Guest")
		self.assertFalse(_may_conclude(self.payment_request.name))

	def test_a_stripe_charge_that_was_not_captured_does_not_count(self):
		self._stripe_receipt(amount=1000, captured=False)
		frappe.set_user("Guest")
		self.assertFalse(_may_conclude(self.payment_request.name))

	def test_a_stripe_charge_of_another_request_does_not_count(self):
		other = _payment_request(fresh_token())
		self._stripe_receipt(amount=1000, request=other.name)
		frappe.set_user("Guest")
		self.assertFalse(_may_conclude(self.payment_request.name))

	def test_a_receipt_nobody_bound_to_a_request_does_not_count(self):
		self._stripe_receipt(amount=1000, request=None)
		frappe.set_user("Guest")
		self.assertFalse(_may_conclude(self.payment_request.name))

	def _stripe_receipt(self, amount, currency="chf", captured=True, request="__this__"):
		"""What `Stripe Settings` writes when Stripe has answered a charge, from a stand-in for Stripe's answer."""
		try:
			from payments.utils import stripe_receipt
		except ImportError:
			self.skipTest("payments app not installed")
		integration_request = frappe.get_doc(
			{
				"doctype": "Integration Request",
				"integration_request_service": stripe_receipt.RECEIPT_SERVICE,
				"request_description": f"{PREFIX}receipt",
				"status": "Completed",
				"data": "{}",
			}
		).insert(ignore_permissions=True)
		charge = frappe._dict(
			id="ch_" + frappe.generate_hash(length=16), amount=amount, currency=currency, captured=captured, paid=captured
		)
		stripe_receipt.write(
			integration_request, charge, self.payment_request.name if request == "__this__" else request
		)
		return integration_request

	def test_a_signed_in_stranger_may_not_conclude(self):
		"""Signed in, but not the buyer and not staff: the request is not theirs."""
		user = _test_user("_wstest_stranger@example.com", ["Customer"])
		frappe.db.set_value(
			"Payment Request", self.payment_request.name, "party", "_WSTEST Someone Else"
		)
		frappe.set_user(user)

		self.assertFalse(_may_conclude(self.payment_request.name, money_confirmed=False))

	def test_a_request_without_a_party_is_refused(self):
		user = _test_user("_wstest_stranger@example.com", ["Customer"])
		frappe.db.set_value("Payment Request", self.payment_request.name, "party", None)
		frappe.set_user(user)

		self.assertFalse(_may_conclude(self.payment_request.name, money_confirmed=False))


def _test_user(email, roles):
	"""A user with these roles, created muted (a welcome mail needs SMTP)."""
	before = frappe.flags.mute_emails
	frappe.flags.mute_emails = True
	try:
		if not frappe.db.exists("User", email):
			doc = frappe.new_doc("User")
			doc.update({"email": email, "first_name": email.split("@")[0], "send_welcome_email": 0})
			doc.insert(ignore_permissions=True)

		# Read the user back before touching roles: insert() writes it again
		# (welcome-mail bookkeeping), so the doc in hand is already stale and
		# add_roles' save raises TimestampMismatchError.
		missing = [r for r in roles if not frappe.db.exists("Has Role", {"parent": email, "role": r})]
		if missing:
			frappe.get_doc("User", email).add_roles(*missing)
		return email
	finally:
		frappe.flags.mute_emails = before
