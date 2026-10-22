# //// Neoffice — added file (no upstream equivalent). The checkout's payment request, raised on a placeholder order.
"""A cart is paid through a Payment Request raised on a placeholder order, and the order is made when the money is.

Upstream ERPNext (v15.12x) refuses a Payment Request against a Quotation, which is how the cart used to open its
payment (neoffice-maintenance#1802). The request is now raised on a draft Sales Order named outside the order series
(PENDING-<quotation>, shopping_cart/pending_order.py), and the REAL order is made, as it always was, only once the
gateway has confirmed the money. These tests go through the shop's own handler as the buyer, under upstream's
checks (`upstream_checks`, which put on the fork the lines stock ERPNext has), and prove:

- the request is accepted where upstream accepts it, and the cart stays a cart: no order, no number of the order
  series, the quotation untouched and still the buyer's cart;
- asking again finds the same request; a cart that changed gets a new one on a new placeholder;
- the gateway's return makes the order, the invoice and the payment entry, moves the request to the order and drops
  the placeholder, once, however many times the gateway calls;
- a payment that never comes leaves the cart as it was and releases what it raised; money that did arrive keeps its
  documents; emptying the cart releases the placeholder (the 417 of the last line);
- the wait page does not announce an order that does not exist yet.
"""

from unittest import mock

import frappe
from frappe.model.naming import parse_naming_series
from frappe.utils import add_to_date, now_datetime

import webshop.webshop.shopping_cart.cart as cart
from webshop.controllers.payment_handler import PaymentHandler
from webshop.templates.pages import order as order_page
from webshop.templates.pages import thank_you as thank_you_page
from webshop.templates.pages.checkout import cart_intent_state
from webshop.templates.payments import paypal
from webshop.webshop.shopping_cart import pending_order
from webshop.webshop.shopping_cart.test_loyalty_rights import (
	GATEWAY,
	ITEM,
	PREFIX,
	PRICE,
	STRANGER,
	USER,
	CUSTOMER,
	ShopFixture,
	no_gateway,
	upstream_checks,
)


def order_series_counters():
	"""Where the counters of the Sales Order series stand: a number taken by a placeholder would show here."""
	counters = {}
	for option in (frappe.get_meta("Sales Order").get_field("naming_series").options or "").split("\n"):
		if option.strip():
			prefix = parse_naming_series(option.strip())
			rows = frappe.db.sql("select `current` from `tabSeries` where name = %s", prefix)
			counters[prefix] = rows[0][0] if rows else None
	return counters


class TestACardPaymentIsRaisedOnAPlaceholderOrder(ShopFixture):
	# --- helpers ------------------------------------------------------------------

	def fill_the_cart(self, qty=1):
		frappe.set_user(USER)
		with upstream_checks():
			cart.update_cart(ITEM, qty)
			cart.get_cart_quotation()  # sets the customer's address on the cart, as the cart page does
			quotation = cart._get_cart_quotation()
		frappe.set_user("Administrator")
		return quotation

	def raise_the_request(self, quotation, token=None):
		frappe.set_user(USER)
		with upstream_checks():
			result = PaymentHandler().create_payment_request(
				quotation_id=quotation.name, payment_gateway=GATEWAY, idempotency_token=token
			)
		frappe.set_user("Administrator")
		frappe.db.commit()
		return result

	def the_money_comes(self, request):
		frappe.set_user(USER)
		with upstream_checks(), no_gateway():
			result = PaymentHandler().handle_payment_success(payment_request_id=request)
		frappe.set_user("Administrator")
		return result

	def token(self):
		return f"{PREFIX}-{frappe.generate_hash(length=10)}"

	def placeholders(self):
		return frappe.get_all(
			"Sales Order",
			filters={"customer": CUSTOMER, "name": ["like", f"{pending_order.PLACEHOLDER_PREFIX}%"]},
			pluck="name",
		)

	def real_orders(self):
		return frappe.get_all("Sales Order", filters={"customer": CUSTOMER, "docstatus": 1}, pluck="name")

	# --- the request, and the cart that stays a cart ------------------------------

	def test_the_request_is_raised_on_a_placeholder_order(self):
		quotation = self.fill_the_cart()
		result = self.raise_the_request(quotation, self.token())
		self.assertEqual(result.get("status"), "success", (result, self.last_error()))

		request = frappe.get_doc("Payment Request", result["payment_request_id"])
		placeholder = pending_order.placeholder_name(quotation.name)
		self.assertEqual((request.reference_doctype, request.reference_name), ("Sales Order", placeholder))
		self.assertEqual(request.company, self.company)
		self.assertEqual(request.owner, USER, "the request stays the buyer's: _may_conclude reads it")
		order = frappe.get_doc("Sales Order", placeholder)
		self.assertEqual(order.docstatus, 0)
		self.assertEqual(order.order_type, "Shopping Cart")
		self.assertEqual(order.customer, CUSTOMER)
		self.assertEqual(
			sorted((row.item_code, row.qty) for row in order.items),
			sorted((row.item_code, row.qty) for row in quotation.items),
		)
		self.assertEqual(order.owner, USER)

	def test_the_cart_stays_a_cart_and_nothing_is_ordered(self):
		quotation = self.fill_the_cart()
		self.raise_the_request(quotation, self.token())

		self.assertEqual(self.real_orders(), [], "no order exists until the money is in")
		self.assertEqual(frappe.db.get_value("Quotation", quotation.name, "docstatus"), 0)
		frappe.set_user(USER)
		self.assertEqual(cart._get_cart_quotation().name, quotation.name, "it is still the buyer's cart")

	def test_the_placeholder_takes_no_number_of_the_order_series(self):
		quotation = self.fill_the_cart()
		before = order_series_counters()
		self.raise_the_request(quotation, self.token())
		self.assertEqual(order_series_counters(), before)
		self.assertFalse(
			self.placeholders() == [], "the placeholder is there, and still took no number of the series"
		)

	def test_a_draft_is_not_an_order_to_the_buyer(self):
		"""The placeholder is not one of the buyer's orders: 'my orders' lists submitted ones."""
		quotation = self.fill_the_cart()
		self.raise_the_request(quotation, self.token())
		self.assertEqual(
			frappe.get_all(
				"Sales Order",
				filters={"customer": CUSTOMER, "docstatus": ["not in", [0, 2]]},
			),
			[],
		)

	# --- asking again -------------------------------------------------------------

	def test_asking_again_finds_the_same_request_and_the_same_placeholder(self):
		quotation = self.fill_the_cart()
		token = self.token()
		first = self.raise_the_request(quotation, token)
		second = self.raise_the_request(quotation, token)

		self.assertEqual(second.get("status"), "success", (second, self.last_error()))
		self.assertEqual(second["payment_request_id"], first["payment_request_id"])
		self.assertEqual(len(self.placeholders()), 1)

	def test_a_new_attempt_after_a_refusal_raises_a_new_request_on_the_same_placeholder(self):
		quotation = self.fill_the_cart()
		first = self.raise_the_request(quotation, self.token())
		frappe.set_user(USER)
		PaymentHandler().handle_payment_failure(
			payment_request_id=first["payment_request_id"], error_message="card declined"
		)
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Payment Request", first["payment_request_id"], "status"), "Failed")

		second = self.raise_the_request(quotation, self.token())

		self.assertEqual(second.get("status"), "success", (second, self.last_error()))
		self.assertNotEqual(second["payment_request_id"], first["payment_request_id"])
		self.assertEqual(self.placeholders(), [pending_order.placeholder_name(quotation.name)])
		self.assertEqual(frappe.db.get_value("Quotation", quotation.name, "docstatus"), 0)

	def test_a_cart_that_changed_has_its_request_and_its_placeholder_made_again(self):
		quotation = self.fill_the_cart(1)
		token = self.token()
		first = self.raise_the_request(quotation, token)
		old_total = frappe.db.get_value("Payment Request", first["payment_request_id"], "grand_total")
		frappe.set_user(USER)
		with upstream_checks():
			cart.update_cart(ITEM, 3)
		frappe.set_user("Administrator")

		second = self.raise_the_request(quotation, token)

		self.assertEqual(second.get("status"), "success", (second, self.last_error()))
		self.assertNotEqual(second.get("message"), "Using existing payment request", second)
		# Frappe gives a deleted request's number back when it was the last one, so the NAME may repeat:
		# what must differ is what the request asks for.
		request = frappe.get_doc("Payment Request", second["payment_request_id"])
		self.assertEqual(request.grand_total, 3 * PRICE)
		self.assertNotEqual(request.grand_total, old_total)
		self.assertEqual(request.reference_name, pending_order.placeholder_name(quotation.name))
		order = frappe.get_doc("Sales Order", request.reference_name)
		self.assertEqual([(row.item_code, row.qty) for row in order.items], [(ITEM, 3)])
		self.assertEqual(len(self.placeholders()), 1)
		self.assertEqual(
			frappe.db.count("Payment Request", {"reference_name": request.reference_name}), 1, "one request, not two"
		)

	# --- the money comes ----------------------------------------------------------

	def test_the_gateway_return_makes_the_real_order_and_drops_the_placeholder(self):
		quotation = self.fill_the_cart()
		request = self.raise_the_request(quotation, self.token())["payment_request_id"]
		placeholder = pending_order.placeholder_name(quotation.name)

		result = self.the_money_comes(request)

		self.assertEqual(result.get("status"), "success", (result, self.last_error()))
		order = frappe.db.get_value("Payment Request", request, "reference_name")
		self.assertFalse(pending_order.is_placeholder(order))
		self.assertEqual(frappe.db.get_value("Sales Order", order, "docstatus"), 1)
		self.assertEqual(self.real_orders(), [order])
		self.assertFalse(frappe.db.exists("Sales Order", placeholder), "the placeholder is dropped")
		self.assertEqual(frappe.db.get_value("Payment Request", request, "status"), "Paid")
		self.assertEqual(
			pending_order.confirmed_order(frappe.get_doc("Payment Request", request)),
			order,
			"now a real order says so",
		)
		self.assertEqual(frappe.db.get_value("Quotation", quotation.name, "status"), "Ordered")

	def test_the_gateway_calling_twice_makes_one_order_one_invoice_one_payment(self):
		quotation = self.fill_the_cart()
		request = self.raise_the_request(quotation, self.token())["payment_request_id"]

		first = self.the_money_comes(request)
		second = self.the_money_comes(request)

		self.assertEqual(first.get("status"), "success", (first, self.last_error()))
		self.assertEqual(second.get("status"), "success", (second, self.last_error()))
		self.assertEqual(second.get("message"), "Payment already processed")
		order = frappe.db.get_value("Payment Request", request, "reference_name")
		self.assertEqual(self.real_orders(), [order])
		invoices = frappe.get_all(
			"Sales Invoice Item", filters={"sales_order": order, "docstatus": 1}, pluck="parent", distinct=True
		)
		self.assertEqual(len(invoices), 1)
		self.assertEqual(
			len(
				frappe.get_all(
					"Payment Entry Reference",
					filters={"reference_name": invoices[0], "docstatus": 1},
					pluck="parent",
				)
			),
			1,
		)

	def test_an_attempt_the_gateway_refused_follows_the_request_that_succeeds_to_the_order(self):
		"""A refusal then a success: the refused attempt stays as history on the real order, nothing blocks the
		placeholder's deletion, and nothing is left behind (a submitted refused request used to keep it)."""
		quotation = self.fill_the_cart()
		first = self.raise_the_request(quotation, self.token())["payment_request_id"]
		frappe.set_user(USER)
		PaymentHandler().handle_payment_failure(payment_request_id=first, error_message="card declined")
		frappe.set_user("Administrator")
		second = self.raise_the_request(quotation, self.token())["payment_request_id"]
		self.assertNotEqual(frappe.db.get_value("Payment Request", second, "status"), "Failed")

		result = self.the_money_comes(second)

		self.assertEqual(result.get("status"), "success", (result, self.last_error()))
		order = frappe.db.get_value("Payment Request", second, "reference_name")
		self.assertEqual(self.real_orders(), [order])
		self.assertEqual(self.placeholders(), [], "the placeholder is gone")
		self.assertEqual(frappe.db.get_value("Payment Request", first, "reference_name"), order)
		self.assertEqual(frappe.db.get_value("Payment Request", first, "status"), "Failed")
		self.assertEqual(frappe.db.get_value("Payment Request", second, "status"), "Paid")

	def test_a_second_method_the_buyer_left_open_follows_the_order_and_is_not_deleted(self):
		"""Two methods opened on one cart, one pays: the other request, whose gateway may still answer, is kept."""
		quotation = self.fill_the_cart()
		paid = self.raise_the_request(quotation, self.token())["payment_request_id"]
		other = self.raise_the_request(quotation, self.token())["payment_request_id"]
		self.assertNotEqual(paid, other)
		self.assertEqual(len(self.placeholders()), 1, "one placeholder for the cart, two requests on it")

		result = self.the_money_comes(paid)

		self.assertEqual(result.get("status"), "success", (result, self.last_error()))
		order = frappe.db.get_value("Payment Request", paid, "reference_name")
		self.assertEqual(frappe.db.get_value("Payment Request", other, "reference_name"), order)
		self.assertEqual(frappe.db.get_value("Payment Request", other, "docstatus"), 0, "kept as it was")
		self.assertEqual(self.placeholders(), [])

	def test_the_gateway_controllers_authorisation_makes_the_order_too(self):
		"""Stripe and PayPal conclude through the Payment Request's own on_payment_authorized (the override
		in override_doctype/payment_request.py), in the buyer's session, with `place_order` reading the cart."""
		quotation = self.fill_the_cart()
		request = self.raise_the_request(quotation, self.token())["payment_request_id"]
		placeholder = pending_order.placeholder_name(quotation.name)

		frappe.set_user(USER)
		with upstream_checks(), no_gateway():
			document = frappe.get_doc("Payment Request", request)
			redirect = document.on_payment_authorized("Completed")
		frappe.set_user("Administrator")

		order = frappe.db.get_value("Payment Request", request, "reference_name")
		self.assertFalse(pending_order.is_placeholder(order), (order, self.last_error()))
		self.assertEqual(frappe.db.get_value("Sales Order", order, "docstatus"), 1)
		self.assertEqual(self.real_orders(), [order])
		self.assertFalse(frappe.db.exists("Sales Order", placeholder), "the placeholder is dropped")
		self.assertEqual(frappe.db.get_value("Payment Request", request, "docstatus"), 1)
		self.assertTrue(redirect, "the page to send the buyer to (the shop's setting decides which)")

	def paypal_request(self, quotation, token):
		"""The PayPal tile's server entry point, as the buyer, the gateway's own controller standing in."""
		settings = frappe.get_cached_doc("Webshop Settings")
		fake_settings = frappe._dict(
			payment_methods=[frappe._dict(payment_gateway_account=self.gateway_account, payment_terms_template=None)],
			enabled=settings.enabled,
		)
		real = frappe.get_cached_doc

		def get_cached_doc(doctype, *args, **kwargs):
			return fake_settings if doctype == "Webshop Settings" else real(doctype, *args, **kwargs)

		controller = mock.Mock()
		controller.get_payment_url.return_value = "https://pay.example.test/paypal"
		frappe.set_user(USER)
		with (
			upstream_checks(),
			mock.patch.object(frappe, "get_cached_doc", side_effect=get_cached_doc),
			mock.patch("payments.utils.get_payment_gateway_controller", return_value=controller),
		):
			result = paypal.create_paypal_payment_request(quotation.name, token)
		frappe.set_user("Administrator")
		frappe.db.commit()
		return result

	def test_the_paypal_tile_raises_its_request_on_the_placeholder(self):
		quotation = self.fill_the_cart()

		result = self.paypal_request(quotation, self.token())

		self.assertEqual(result.get("status"), "success", (result, self.last_error()))
		self.assertEqual(result.get("payment_url"), "https://pay.example.test/paypal")
		request = frappe.get_all(
			"Payment Request",
			filters={"party": CUSTOMER},
			fields=["reference_doctype", "reference_name", "status", "owner"],
		)
		self.assertEqual(len(request), 1, request)
		self.assertEqual(
			(request[0].reference_doctype, request[0].reference_name, request[0].status, request[0].owner),
			("Sales Order", pending_order.placeholder_name(quotation.name), "Initiated", USER),
		)
		self.assertEqual(self.real_orders(), [], "no order until the money is in")

	def test_an_order_paid_elsewhere_does_not_make_the_next_cart_read_already_paid(self):
		"""The lookup of an existing request read a filter Frappe cut to its first key: any paid request on any
		order answered "This order has already been paid" to every other cart."""
		first = self.fill_the_cart()
		self.the_money_comes(self.raise_the_request(first, self.token())["payment_request_id"])
		self.assertEqual(len(self.real_orders()), 1)

		quotation = self.fill_the_cart()
		self.assertNotEqual(quotation.name, first.name)
		result = self.paypal_request(quotation, self.token())

		self.assertEqual(result.get("status"), "success", (result, self.last_error()))
		self.assertEqual(result.get("payment_url"), "https://pay.example.test/paypal")

	# --- whose cart, what amount, what a clock may delete --------------------------------

	def test_a_buyer_cannot_raise_a_request_on_another_buyers_cart(self):
		quotation = self.fill_the_cart()
		frappe.set_user(STRANGER)
		with upstream_checks(), self.assertRaises(frappe.PermissionError):
			PaymentHandler().create_payment_request(
				quotation_id=quotation.name, payment_gateway=GATEWAY, idempotency_token=self.token()
			)
		frappe.set_user("Administrator")
		self.assertEqual(self.placeholders(), [], "nothing was made on the other buyer's cart")
		self.assertEqual(frappe.db.count("Payment Request", {"party": CUSTOMER}), 0)

	def test_a_token_is_not_a_key_to_another_buyers_request(self):
		quotation = self.fill_the_cart()
		token = self.token()
		mine = self.raise_the_request(quotation, token)["payment_request_id"]
		# the other buyer's own cart, asked with MY token
		frappe.set_user(STRANGER)
		with upstream_checks():
			cart.update_cart(ITEM, 1)
			cart.get_cart_quotation()
			theirs = cart._get_cart_quotation()
		frappe.set_user("Administrator")
		frappe.db.set_value("Payment Request", mine, "custom_idempotency_token", token + "-mine")
		self.assertNotEqual(theirs.name, quotation.name)

		frappe.set_user(STRANGER)
		with upstream_checks():
			result = PaymentHandler().create_payment_request(
				quotation_id=theirs.name, payment_gateway=GATEWAY, idempotency_token=token + "-mine"
			)
		frappe.set_user("Administrator")
		# it does not answer with my request, and it leaves mine alone
		self.assertNotEqual(result.get("payment_request_id"), mine, result)
		self.assertTrue(frappe.db.exists("Payment Request", mine))
		self.assertEqual(frappe.db.get_value("Payment Request", mine, "reference_name"), "PENDING-" + quotation.name)

	def test_a_cart_changed_after_the_payment_started_is_not_ordered_for_the_wrong_amount(self):
		quotation = self.fill_the_cart(1)
		request = self.raise_the_request(quotation, self.token())["payment_request_id"]
		frappe.set_user(USER)
		with upstream_checks():
			cart.update_cart(ITEM, 3)  # in another tab
		frappe.set_user("Administrator")

		result = self.the_money_comes(request)

		self.assertEqual(result.get("status"), "error", result)
		self.assertEqual(self.real_orders(), [], "no order for an amount nobody paid")
		self.assertEqual(frappe.db.get_value("Quotation", quotation.name, "docstatus"), 0, "the cart is untouched")
		self.assertTrue(frappe.db.exists("Sales Order", pending_order.placeholder_name(quotation.name)))
		self.assertTrue(
			frappe.db.exists(
				"Comment", {"reference_doctype": "Payment Request", "reference_name": request, "comment_type": "Info"}
			),
			"the request says why it was kept",
		)
		self.assertIn("amount paid", (self.last_error() or {}).get("method", ""))

	def test_a_request_marked_paid_on_the_placeholder_still_makes_its_order(self):
		"""A gateway that marked the request Paid without the shop making the order: that is not "processed"."""
		quotation = self.fill_the_cart()
		request = self.raise_the_request(quotation, self.token())["payment_request_id"]
		frappe.db.set_value("Payment Request", request, "status", "Paid")

		result = self.the_money_comes(request)

		self.assertEqual(result.get("status"), "success", (result, self.last_error()))
		order = frappe.db.get_value("Payment Request", request, "reference_name")
		self.assertFalse(pending_order.is_placeholder(order))
		self.assertEqual(self.real_orders(), [order])

	def test_a_second_payment_for_a_cart_that_is_already_an_order_is_reported(self):
		quotation = self.fill_the_cart()
		paid = self.raise_the_request(quotation, self.token())["payment_request_id"]
		other = self.raise_the_request(quotation, self.token())["payment_request_id"]
		self.the_money_comes(paid)

		result = self.the_money_comes(other)

		self.assertEqual(result.get("status"), "success", result)
		self.assertEqual(len(self.real_orders()), 1, "still one order")
		self.assertIn("second payment request", (self.last_error() or {}).get("method", ""))

	def test_nobody_submits_a_placeholder(self):
		placeholder = self.a_placeholder()
		order = frappe.get_doc("Sales Order", placeholder)
		with self.assertRaises(frappe.ValidationError):
			order.submit()
		self.assertEqual(frappe.db.get_value("Sales Order", placeholder, "docstatus"), 0)

	def test_a_placeholder_is_one_whatever_the_case(self):
		self.assertTrue(pending_order.is_placeholder("PENDING-DEVIS-1"))
		self.assertTrue(pending_order.is_placeholder("pending-devis-1"))
		self.assertFalse(pending_order.is_placeholder("SAL-ORD-2026-00001"))
		self.assertFalse(pending_order.is_placeholder(None))

	def test_the_order_page_has_no_page_for_a_placeholder_in_any_case(self):
		placeholder = self.a_placeholder()
		frappe.set_user(USER)
		frappe.local.form_dict = frappe._dict(doctype="Sales Order", name=placeholder.lower())
		with self.assertRaises(frappe.DoesNotExistError):
			order_page.get_context(frappe._dict())

	def test_a_placeholder_older_than_its_cart_belongs_to_another_cart(self):
		"""Frappe gives a deleted cart's number back: a new cart can carry the name of a cart that is gone."""
		quotation = self.fill_the_cart()
		first = self.raise_the_request(quotation, self.token())["payment_request_id"]
		placeholder = pending_order.placeholder_name(quotation.name)
		frappe.db.set_value(
			"Sales Order", placeholder, "creation", add_to_date(quotation.creation, days=-1), update_modified=False
		)
		self.assertFalse(pending_order.is_of_this_cart(placeholder, frappe.get_doc("Quotation", quotation.name)))

		second = self.raise_the_request(quotation, self.token())

		self.assertEqual(second.get("status"), "success", (second, self.last_error()))
		self.assertTrue(
			pending_order.is_of_this_cart(placeholder, frappe.get_doc("Quotation", quotation.name)),
			"made again, for this cart",
		)
		self.assertEqual(self.placeholders(), [placeholder])
		self.assertEqual(frappe.db.count("Payment Request", {"reference_name": placeholder}), 1)

	def stale(self, placeholder):
		frappe.db.set_value(
			"Sales Order",
			placeholder,
			"modified",
			add_to_date(now_datetime(), hours=-(pending_order.HOLD_HOURS + 1)),
			update_modified=False,
		)

	def an_intent(self, request, status):
		intent = frappe.new_doc("Payment Intent")
		intent.update({"reference_doctype": "Payment Request", "reference_name": request, "status": status})
		intent.flags.ignore_validate = True
		intent.insert(ignore_permissions=True, ignore_mandatory=True)
		return intent

	def test_a_gateway_attempt_that_may_still_answer_keeps_the_placeholder_through_the_hold(self):
		if not frappe.db.exists("DocType", "Payment Intent"):
			self.skipTest("Payment Intent doctype not installed")
		quotation = self.fill_the_cart()
		request = self.raise_the_request(quotation, self.token())["payment_request_id"]
		intent = self.an_intent(request, "processing")  # a bank page, still open
		placeholder = pending_order.placeholder_name(quotation.name)
		self.stale(placeholder)

		pending_order.release_stale()

		self.assertTrue(frappe.db.exists("Payment Request", request), "the gateway may still answer for it")
		self.assertEqual(self.placeholders(), [placeholder])

		# a day later nothing has moved: it goes, with its attempt
		frappe.db.set_value(
			"Payment Intent",
			intent.name,
			"modified",
			add_to_date(now_datetime(), hours=-(pending_order.HOLD_HOURS + 1)),
			update_modified=False,
		)
		pending_order.release_stale()
		self.assertFalse(frappe.db.exists("Payment Request", request))
		self.assertEqual(self.placeholders(), [])

	def test_money_on_a_placeholder_is_said_once_not_every_hour(self):
		quotation = self.fill_the_cart()
		request = self.raise_the_request(quotation, self.token())["payment_request_id"]
		frappe.db.set_value("Payment Request", request, "status", "Paid")
		placeholder = pending_order.placeholder_name(quotation.name)
		self.stale(placeholder)

		pending_order.release_stale()
		pending_order.release_stale()
		pending_order.release_stale()

		self.assertEqual(
			frappe.db.count(
				"Comment", {"reference_doctype": "Sales Order", "reference_name": placeholder, "comment_type": "Info"}
			),
			1,
			"one note",
		)
		self.assertEqual(
			frappe.db.count("Error Log", {"method": "Webshop: a pending order is kept", "error": ["like", f"{placeholder}%"]}),
			1,
			"one line in the Error Log",
		)
		self.assertEqual(self.placeholders(), [placeholder])

	# --- the money does not come --------------------------------------------------

	def test_a_payment_that_never_comes_leaves_the_cart_as_it_was(self):
		quotation = self.fill_the_cart()
		first = self.raise_the_request(quotation, self.token())["payment_request_id"]
		second = self.raise_the_request(self.fill_the_cart(), self.token())["payment_request_id"]
		self.assertEqual(len(self.placeholders()), 1)
		# the hold is over: nobody came back
		frappe.db.set_value(
			"Sales Order",
			pending_order.placeholder_name(quotation.name),
			"modified",
			add_to_date(now_datetime(), hours=-(pending_order.HOLD_HOURS + 1)),
			update_modified=False,
		)

		pending_order.release_stale()

		self.assertEqual(self.placeholders(), [])
		self.assertFalse(frappe.db.exists("Payment Request", first))
		self.assertFalse(frappe.db.exists("Payment Request", second))
		self.assertEqual(frappe.db.get_value("Quotation", quotation.name, "docstatus"), 0, "the cart is untouched")
		self.assertEqual(self.real_orders(), [])

	def test_a_refused_attempt_does_not_keep_the_placeholder_alive(self):
		"""A request the gateway refused is submitted; released, it is cancelled, and a cancelled request is no
		link: the placeholder goes, as it does with a request that was never submitted."""
		quotation = self.fill_the_cart()
		request = self.raise_the_request(quotation, self.token())["payment_request_id"]
		frappe.set_user(USER)
		PaymentHandler().handle_payment_failure(payment_request_id=request, error_message="card declined")
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Payment Request", request, "docstatus"), 1)

		self.assertTrue(pending_order.release(quotation.name))

		self.assertEqual(self.placeholders(), [])
		self.assertEqual(frappe.db.get_value("Payment Request", request, "docstatus"), 2, "cancelled, not paid")

	def test_a_payment_still_in_its_hold_is_not_released(self):
		quotation = self.fill_the_cart()
		request = self.raise_the_request(quotation, self.token())["payment_request_id"]

		pending_order.release_stale()

		self.assertTrue(frappe.db.exists("Payment Request", request))
		self.assertEqual(len(self.placeholders()), 1)

	def test_money_that_arrived_keeps_its_documents(self):
		quotation = self.fill_the_cart()
		request = self.raise_the_request(quotation, self.token())["payment_request_id"]
		frappe.db.set_value("Payment Request", request, "status", "Paid")  # the gateway captured it

		self.assertFalse(pending_order.release(quotation.name), "refused: money moved")
		frappe.db.set_value(
			"Sales Order",
			pending_order.placeholder_name(quotation.name),
			"modified",
			add_to_date(now_datetime(), hours=-(pending_order.HOLD_HOURS + 1)),
			update_modified=False,
		)
		pending_order.release_stale()

		self.assertTrue(frappe.db.exists("Payment Request", request))
		self.assertEqual(len(self.placeholders()), 1)

	def test_emptying_the_cart_releases_the_placeholder_and_the_unpaid_request(self):
		"""The 417 of the last line: a document linking the quotation stops it being deleted."""
		quotation = self.fill_the_cart()
		request = self.raise_the_request(quotation, self.token())["payment_request_id"]

		frappe.set_user(USER)
		with upstream_checks():
			cart.update_cart(ITEM, 0)
		frappe.set_user("Administrator")

		self.assertFalse(frappe.db.exists("Quotation", quotation.name), "the cart is gone")
		self.assertEqual(self.placeholders(), [])
		self.assertFalse(frappe.db.exists("Payment Request", request))

	# --- the wait page ------------------------------------------------------------

	def test_the_wait_page_announces_the_order_only_once_it_exists(self):
		"""The request used to point at an order only once the order existed: the poll read that as "done"."""
		if not frappe.db.exists("DocType", "Payment Intent"):
			self.skipTest("Payment Intent doctype not installed")
		quotation = self.fill_the_cart()
		request = self.raise_the_request(quotation, self.token())["payment_request_id"]
		intent = frappe.new_doc("Payment Intent")
		intent.update({"reference_doctype": "Payment Request", "reference_name": request, "status": "requires_action"})
		intent.flags.ignore_validate = True
		intent.insert(ignore_permissions=True, ignore_mandatory=True)

		frappe.set_user(USER)
		waiting = cart_intent_state(intent.name)
		frappe.set_user("Administrator")
		self.assertEqual(waiting.get("done"), False, waiting)

		self.the_money_comes(request)

		frappe.set_user(USER)
		done = cart_intent_state(intent.name)
		frappe.set_user("Administrator")
		self.assertEqual(done.get("done"), True, done)
		self.assertIn("/thank_you?sales_order=", done.get("redirect_to"))
		self.assertNotIn(pending_order.PLACEHOLDER_PREFIX, done.get("redirect_to"))

	def test_a_request_on_a_placeholder_has_no_order_yet(self):
		quotation = self.fill_the_cart()
		request = frappe.get_doc(
			"Payment Request", self.raise_the_request(quotation, self.token())["payment_request_id"]
		)
		self.assertIsNone(pending_order.confirmed_order(request))
		self.assertIsNone(pending_order.confirmed_order(frappe._dict(reference_doctype="Quotation", reference_name="x")))
		self.assertIsNone(
			pending_order.confirmed_order(frappe._dict(reference_doctype="Sales Order", reference_name="SO-NONE-0001"))
		)

	# --- the buyer never meets the placeholder as an order -----------------------------

	def a_placeholder(self):
		quotation = self.fill_the_cart()
		self.raise_the_request(quotation, self.token())
		return pending_order.placeholder_name(quotation.name)

	def test_the_thank_you_page_does_not_confirm_a_placeholder(self):
		placeholder = self.a_placeholder()
		frappe.set_user(USER)
		frappe.local.form_dict = frappe._dict(sales_order=placeholder)
		context = frappe._dict()
		with upstream_checks():
			thank_you_page.get_context(context)
		self.assertTrue(context.get("error_message"), "told that the order does not exist")
		self.assertFalse(context.get("sales_order"))

	def test_the_order_page_has_no_page_for_a_placeholder(self):
		placeholder = self.a_placeholder()
		frappe.set_user(USER)
		frappe.local.form_dict = frappe._dict(doctype="Sales Order", name=placeholder)
		with self.assertRaises(frappe.DoesNotExistError):
			order_page.get_context(frappe._dict())

	def test_the_pay_button_of_the_order_page_does_not_pay_a_placeholder(self):
		placeholder = self.a_placeholder()
		frappe.set_user(USER)
		with self.assertRaises(frappe.PermissionError):
			order_page.make_payment_request(dt="Sales Order", dn=placeholder)
		frappe.set_user("Administrator")
		self.assertEqual(
			frappe.db.count("Payment Request", {"reference_name": placeholder}), 1, "only the checkout's request"
		)

	def test_the_thank_you_page_still_confirms_a_real_order(self):
		quotation = self.fill_the_cart()
		request = self.raise_the_request(quotation, self.token())["payment_request_id"]
		self.the_money_comes(request)
		order = frappe.db.get_value("Payment Request", request, "reference_name")
		frappe.set_user(USER)
		frappe.local.form_dict = frappe._dict(sales_order=order)
		context = frappe._dict()
		with upstream_checks():
			thank_you_page.get_context(context)
		self.assertFalse(context.get("error_message"), context.get("error_message"))
		self.assertEqual(context.sales_order.name, order)
