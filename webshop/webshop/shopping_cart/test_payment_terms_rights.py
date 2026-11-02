# //// Neoffice — added file (no upstream equivalent). A customer pays on a method whose row carries payment terms (#2114).
"""A portal customer can pay with a payment method whose row names a payment terms template.

Upstream ERPNext (the merge of 4 Oct 2026, 0f64354085) makes the whitelisted `get_payment_terms` refuse any session
that may not read the `Payment Terms Template`, and a portal customer may not (the role `All` lost its read right on
the template). The checkout asked it with the BUYER's session: "Error creating payment request" at the last
click, no payment request, no order (neoffice-maintenance#2114). Every shop whose method rows name a template was
hit, for every customer, the day the update reached it.

The schedule is now computed with the shop's rights (`payment_schedule_for`), as the pricing and the saves beside it
already were (#277). The template is the shop's own, named by the method row, or by an instalment plan; the one
endpoint where the buyer names it (`update_payment_terms`) first checks that the shop offers it.

What is proven here:

- the witness: ERPNext's own `get_payment_terms`, asked as the buyer, is refused. Without it a green run would
  prove nothing (a stock ERPNext before the guard lets everyone read);
- the checkout creates the payment request, and the quotation carries the template's schedule;
- the session is handed back as it was;
- the buyer picks an instalment plan the shop offers; a template the shop does not offer is refused, and its
  schedule is not read;
- a failure of the payment path writes its traceback in the Error Log, not only its message;
- no module of the shop calls ERPNext's `get_payment_terms` itself again (a source-reading test, no site).
"""

import ast
import pathlib
import unittest
from unittest.mock import patch

import frappe

import webshop.webshop.shopping_cart.cart as cart
from webshop.controllers.payment_handler import PaymentHandler
from webshop.webshop.shopping_cart import shop_rights, webshopsi_cart
from webshop.webshop.shopping_cart.test_loyalty_rights import (
	GATEWAY,
	ITEM,
	PREFIX,
	USER,
	ShopFixture,
	upstream_checks,
)

TEMPLATE = f"{PREFIX} Terms 40-60"
OTHER_TEMPLATE = f"{PREFIX} Terms Not Offered"
HANDLER = "webshop.controllers.payment_handler"


def make_template(name):
	"""Two terms, 40 % at once and 60 % thirty days after. No Payment Term record: the rows carry the dates."""
	if frappe.db.exists("Payment Terms Template", name):
		return
	frappe.get_doc(
		{
			"doctype": "Payment Terms Template",
			"template_name": name,
			"terms": [
				{"invoice_portion": 40, "due_date_based_on": "Day(s) after invoice date", "credit_days": 0},
				{"invoice_portion": 60, "due_date_based_on": "Day(s) after invoice date", "credit_days": 30},
			],
		}
	).insert(ignore_permissions=True)


class TestAMethodRowThatNamesPaymentTerms(ShopFixture):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_template(TEMPLATE)
		make_template(OTHER_TEMPLATE)
		frappe.db.commit()

	@classmethod
	def purge(cls):
		super().purge()
		for name in (TEMPLATE, OTHER_TEMPLATE):
			if frappe.db.exists("Payment Terms Template", name):
				frappe.delete_doc("Payment Terms Template", name, force=True, ignore_permissions=True)

	# --- helpers ------------------------------------------------------------------

	def fill_the_cart(self):
		frappe.set_user(USER)
		try:
			with upstream_checks():
				cart.update_cart(ITEM, 1)
				cart.get_cart_quotation()  # sets the customer's address on the cart, as the cart page does
				return cart._get_cart_quotation()
		finally:
			frappe.set_user("Administrator")

	def row_with_terms(self, template=TEMPLATE):
		"""The shop's method row for this gateway, as the shop's own settings would give it."""
		return frappe._dict(payment_terms_template=template, settlement="Online", mode_of_payment=None)

	def pay_as_the_buyer(self, quotation, template=TEMPLATE):
		frappe.set_user(USER)
		try:
			with (
				upstream_checks(),
				patch(f"{HANDLER}.row_for_gateway", return_value=self.row_with_terms(template)),
			):
				result = PaymentHandler().create_payment_request(
					quotation_id=quotation.name,
					payment_gateway=GATEWAY,
					idempotency_token=f"{PREFIX}-{frappe.generate_hash(length=10)}",
				)
				session_user = frappe.session.user
		finally:
			frappe.set_user("Administrator")
		frappe.db.commit()
		return result, session_user

	# --- the witness ----------------------------------------------------------------

	def test_witness_erpnext_refuses_the_buyer_the_template(self):
		"""If this fails, the guard is not on this ERPNext and the tests below prove nothing."""
		frappe.set_user(USER)
		try:
			from erpnext.controllers.accounts_controller import get_payment_terms

			with self.assertRaises(frappe.PermissionError):
				get_payment_terms(TEMPLATE, "2026-11-02", 100, 100)
		finally:
			frappe.set_user("Administrator")

	# --- the checkout ---------------------------------------------------------------

	def test_the_buyer_pays_on_a_method_that_carries_payment_terms(self):
		quotation = self.fill_the_cart()
		result, session_user = self.pay_as_the_buyer(quotation)

		self.assertEqual(result.get("status"), "success", (result, self.last_error()))
		request = frappe.get_doc("Payment Request", result["payment_request_id"])
		self.assertEqual(request.owner, USER, "the request stays the buyer's")
		self.assertEqual(session_user, USER, "the session is handed back as it was")

		quotation.reload()
		self.assertEqual(quotation.payment_terms_template, TEMPLATE)
		schedule = quotation.get("payment_schedule")
		self.assertEqual([row.invoice_portion for row in schedule], [40, 60])
		total = quotation.rounded_total or quotation.grand_total
		self.assertAlmostEqual(sum(row.payment_amount for row in schedule), total, places=2)
		self.assertEqual(str(schedule[0].due_date), str(quotation.transaction_date), "40 % is due at once")

	def test_a_failure_of_the_payment_path_leaves_its_traceback(self):
		quotation = self.fill_the_cart()
		frappe.set_user(USER)
		try:
			with (
				upstream_checks(),
				patch(f"{HANDLER}.row_for_gateway", return_value=self.row_with_terms()),
				patch(f"{HANDLER}.pending_order.carrier_for", side_effect=RuntimeError("the carrier broke")),
				patch("frappe.log_error") as log_error,
			):
				result = PaymentHandler().create_payment_request(
					quotation_id=quotation.name, payment_gateway=GATEWAY
				)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(result.get("status"), "error")
		log_error.assert_called_once()
		title, message = log_error.call_args.args
		message = str(message)
		self.assertEqual(title, "Detailed error while creating payment request", "the title first (RULE #8)")
		self.assertIn("Traceback", message)
		self.assertIn("the carrier broke", message)
		self.assertIn("create_payment_request", message, "it says where")

	# --- the instalment plans: the one place the buyer names the template -------------

	def test_the_buyer_picks_an_instalment_plan_the_shop_offers(self):
		"""The schedule is computed (it is the step that was refused); what the endpoint keeps afterwards depends on
		the method being the "Facture" one, which is not under test here, so the rows are read where they are made."""
		quotation = self.fill_the_cart()
		schedules = []
		computed = webshopsi_cart.payment_schedule_for

		def spy(*args, **kwargs):
			schedules.append(computed(*args, **kwargs))
			return schedules[-1]

		frappe.set_user(USER)
		try:
			with (
				upstream_checks(),
				patch.object(webshopsi_cart, "installment_templates", return_value={TEMPLATE}),
				patch.object(webshopsi_cart, "payment_schedule_for", spy),
			):
				webshopsi_cart.update_payment_terms(quotation.name, TEMPLATE)
				session_user = frappe.session.user
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(session_user, USER, "the session is handed back as it was")
		self.assertEqual(len(schedules), 1, "the schedule was asked for, and not refused")
		self.assertEqual([row.invoice_portion for row in schedules[0]], [40, 60])

	def test_a_template_the_shop_does_not_offer_is_refused_and_not_read(self):
		quotation = self.fill_the_cart()
		frappe.set_user(USER)
		try:
			with upstream_checks(), patch.object(webshopsi_cart, "installment_templates", return_value={TEMPLATE}):
				with self.assertRaises(frappe.PermissionError):
					webshopsi_cart.update_payment_terms(quotation.name, OTHER_TEMPLATE)
		finally:
			frappe.set_user("Administrator")

		quotation.reload()
		self.assertNotEqual(quotation.payment_terms_template, OTHER_TEMPLATE)

	def last_error(self):
		return frappe.db.get_value("Error Log", {}, "error", order_by="creation desc")


# --- the shop reaches ERPNext's guarded function in one place only -------------------


class TestNoModuleAsksForPaymentTermsAsTheBuyer(unittest.TestCase):
	"""`get_payment_terms` refuses a session that may not read the template: the shop asks for a schedule through
	`payment_schedule_for` (the shop's rights), never by itself. A fifth call written the old way would pass every
	test run as Administrator, as the four of #2114 did."""

	def test_only_the_helper_calls_it(self):
		root = pathlib.Path(shop_rights.__file__).resolve().parents[2]  # the `webshop` package
		offenders = []
		for path in sorted(root.rglob("*.py")):
			if "node_modules" in path.parts or path.name.startswith("test_"):
				continue
			tree = ast.parse(path.read_text(), filename=str(path))
			for node in ast.walk(tree):
				imported = isinstance(node, ast.ImportFrom) and any(
					alias.name == "get_payment_terms" for alias in node.names
				)
				called = isinstance(node, ast.Attribute) and node.attr == "get_payment_terms"
				if (imported or called) and path.name != "shop_rights.py":
					offenders.append(f"{path.relative_to(root)}:{node.lineno}")
		self.assertEqual(offenders, [], "ask for the schedule through shop_rights.payment_schedule_for")
