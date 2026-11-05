# //// Neoffice — added file (no upstream equivalent). The second lot of the audit of the shop
# //// (neoffice-maintenance#2296): each refusal, and beside it the journey that must still pass.
"""What a shop customer may do with a payment, a cart, a contact and a sign-in, and what they may not.

Methods are called the way the HTTP handler calls them (`frappe.is_whitelisted`, then `frappe.call`), as the real
account and not as Administrator, on the shop's own cart and order (`ShopFixture`). The sign-in goes through the real
application with a test client: its answer is an HTTP status the shop's dialog reads, and a session cookie.
"""

from unittest.mock import patch

import frappe
from frappe.auth import LoginAttemptTracker
from frappe.exceptions import FrappeTypeError
from frappe.tests.test_api import make_request
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt, get_test_client
from frappe.utils.password import update_password

import webshop.webshop.shopping_cart.cart as cart
from webshop.controllers.payment_handler import PaymentHandler
from webshop.webshop.auth import api, confirmation
from webshop.webshop.doctype.webshopsi_settings import webshopsi_settings
from webshop.webshop.shopping_cart import pending_order, webshopsi_cart
from webshop.webshop.shopping_cart.shop_rights import save_as_shop
from webshop.webshop.shopping_cart.test_loyalty_rights import (
	CUSTOMER,
	GATEWAY,
	ITEM,
	PREFIX,
	STRANGER,
	STRANGER_CUSTOMER,
	USER,
	ShopFixture,
	_account,
	no_gateway,
	upstream_checks,
)
from webshop.webshop.utils import throttle

ORDER_PAY = "webshop.templates.pages.order.make_payment_request"
REMOVE_FEES = "webshop.webshop.shopping_cart.webshopsi_cart.remove_webshopsi_fees"
FAIL_PAYMENT = "webshop.controllers.payment_handler.handle_payment_failure"
CONCLUDE_PAYMENT = "webshop.controllers.payment_handler.handle_payment_success"
RAISE_REQUEST = "webshop.controllers.payment_handler.create_payment_request"
DIRECT_ORDER = "webshop.controllers.payment_handler.handle_direct_order"
PAYPAL = "webshop.templates.payments.paypal.create_paypal_payment_request"
BIRTHDAY = "webshop.webshop.doctype.webshopsi_settings.webshopsi_settings.get_contact_birthday"
AUTHORIZED = "webshop.webshop.doctype.webshopsi_settings.webshopsi_settings.on_payment_authorized"
MIGRATION = "webshop.webshop.doctype.webshopsi_settings.webshopsi_settings.migrate_installment_fees_to_templates"

SIGN_IN = "/api/method/webshop.webshop.auth.api.custom_login"
FAIL_URL = f"/api/method/{FAIL_PAYMENT}"
CONCLUDE_URL = f"/api/method/{CONCLUDE_PAYMENT}"
NOT_CONFIRMED_YET = (
	"Your payment is not confirmed yet. If your card was charged, do not pay again: "
	"the order will appear in your orders as soon as the payment is confirmed."
)
NOT_CONFIRMED_TITLE = "Webshop: a payment was asked to be concluded before the gateway confirmed it"
CHECK_EMAIL = "/api/method/webshop.webshop.auth.api.check_email"

# The limits of the shop's two doors, per connection and per minute.
SIGN_INS_PER_MINUTE = 20
ADDRESS_CHECKS_PER_MINUTE = 20

SUPPLIER = f"{PREFIX} W2 Supplier"
BANK = f"{PREFIX} W2 Bank"
BANK_NUMBER = "W2-THIRD-PARTY-0001"
INVOICE_GATEWAY = f"{PREFIX} W2 Invoice"


def call(path, **kwargs):
	"""A web method, as the HTTP handler calls it."""
	method = frappe.get_attr(path)
	frappe.is_whitelisted(method)
	return frappe.call(method, **kwargs)


def error_rows():
	# A commit, not a rollback: a new snapshot sees what the test client wrote, and a rollback would erase the very
	# row a "no trace" test looks for, written on this connection.
	frappe.db.commit()
	return frappe.db.count("Error Log")


def http(verb, path, cookie=None, **kwargs):
	"""A request through the real application: a status, and what a browser would get."""
	client = get_test_client(use_cookies=False)
	headers = {"X-Forwarded-For": "198.51.100.201", "Accept": "application/json"}
	if cookie:
		headers["Cookie"] = cookie
	return make_request(target=getattr(client, verb), args=(path,), kwargs={"headers": headers, **kwargs})


class TestTheShopOnItsOwnDocuments(ShopFixture):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.purge_third_party()
		frappe.get_doc(
			{"doctype": "Supplier", "supplier_name": SUPPLIER, "supplier_type": "Company"}
		).insert(ignore_permissions=True)
		frappe.get_doc({"doctype": "Bank", "bank_name": BANK}).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Bank Account",
				"account_name": f"{PREFIX} W2 Account",
				"bank": BANK,
				"party_type": "Supplier",
				"party": SUPPLIER,
				"is_default": 1,
				"bank_account_no": BANK_NUMBER,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		cls.purge_third_party()
		super().tearDownClass()

	@classmethod
	def purge_third_party(cls):
		for name in frappe.get_all("Payment Request", filters={"party": SUPPLIER}, pluck="name"):
			frappe.db.delete("Payment Request", {"name": name})
		for name in frappe.get_all("Bank Account", filters={"party": SUPPLIER}, pluck="name"):
			frappe.delete_doc("Bank Account", name, force=True, ignore_permissions=True)
		if frappe.db.exists("Bank", BANK):
			frappe.delete_doc("Bank", BANK, force=True, ignore_permissions=True)
		if frappe.db.exists("Supplier", SUPPLIER):
			frappe.delete_doc("Supplier", SUPPLIER, force=True, ignore_permissions=True)
		for name in frappe.get_all("Payment Gateway Account", filters={"payment_gateway": INVOICE_GATEWAY}, pluck="name"):
			frappe.delete_doc("Payment Gateway Account", name, force=True, ignore_permissions=True)
		if frappe.db.exists("Payment Gateway", INVOICE_GATEWAY):
			frappe.delete_doc("Payment Gateway", INVOICE_GATEWAY, force=True, ignore_permissions=True)
		frappe.db.commit()

	def tearDown(self):
		for key in ("type", "location"):
			frappe.local.response.pop(key, None)
		super().tearDown()

	# --- helpers ------------------------------------------------------------------

	def token(self):
		return f"{PREFIX}-{frappe.generate_hash(length=10)}"

	def fill_the_cart(self, qty=1, user=USER):
		frappe.set_user(user)
		with upstream_checks():
			cart.update_cart(ITEM, qty)
			cart.get_cart_quotation()  # sets the customer's address on the cart, as the cart page does
			quotation = cart._get_cart_quotation()
		frappe.set_user("Administrator")
		return quotation

	def raise_the_request(self, quotation, token=None, user=USER):
		frappe.set_user(user)
		with upstream_checks():
			result = PaymentHandler().create_payment_request(
				quotation_id=quotation.name, payment_gateway=GATEWAY, idempotency_token=token
			)
		frappe.set_user("Administrator")
		frappe.db.commit()
		return result

	def a_request(self):
		quotation = self.fill_the_cart()
		result = self.raise_the_request(quotation, self.token())
		self.assertEqual(result.get("status"), "success", (result, self.last_error()))
		return result["payment_request_id"]

	def state_of(self, request):
		frappe.db.commit()  # see error_rows
		return frappe.db.get_value("Payment Request", request, ["status", "docstatus", "message"], as_dict=True)

	def real_orders(self, customer=CUSTOMER):
		return frappe.get_all("Sales Order", filters={"customer": customer, "docstatus": 1}, pluck="name")

	def contact_of(self, user):
		return frappe.db.get_value("Contact", {"email_id": user}, "name")

	def charge_shipping(self, quotation_name, amount):
		"""A change of the total that leaves the lines and the discount as they are, as a shipping rule does."""
		doc = frappe.get_doc("Quotation", quotation_name)
		account = _account(self.company, account_type="Tax") or _account(self.company, root_type="Expense")
		doc.append(
			"taxes",
			{
				"charge_type": "Actual",
				"account_head": account,
				"description": f"{PREFIX} shipping",
				"tax_amount": amount,
				"cost_center": frappe.get_cached_value("Company", self.company, "cost_center"),
			},
		)
		save_as_shop(doc, ignore_permissions=True)
		frappe.db.commit()
		return flt(frappe.db.get_value("Quotation", quotation_name, "rounded_total")) or flt(
			frappe.db.get_value("Quotation", quotation_name, "grand_total")
		)

	def invoice_tile(self):
		"""The gateway of the invoice tile, and the account a shop offers it through."""
		gateway = frappe.get_value("Payment Gateway", {"gateway_settings": "WebshopSI Settings"}, "name")
		if not gateway:
			gateway = INVOICE_GATEWAY
			frappe.get_doc(
				{"doctype": "Payment Gateway", "gateway": gateway, "gateway_settings": "WebshopSI Settings"}
			).insert(ignore_permissions=True)
			frappe.get_doc(
				{
					"doctype": "Payment Gateway Account",
					"payment_gateway": gateway,
					"payment_account": self.bank_account,
					"company": self.company,
					"currency": frappe.get_cached_value("Account", self.bank_account, "account_currency"),
				}
			).insert(ignore_permissions=True)
			frappe.db.commit()
		return frappe.db.get_value("Payment Gateway Account", {"payment_gateway": gateway}, "name")

	def a_guest_request(self):
		"""A request of a visitor with no account: their cart is known by its cookie."""
		request = self.a_request()
		cart_name = pending_order.quotation_of(
			frappe.db.get_value("Payment Request", request, "reference_name")
		)
		cookie = frappe.generate_hash(length=16)
		frappe.db.set_value("Quotation", cart_name, "guest_session_id", cookie)
		frappe.db.commit()
		return request, f"guest_session_id={cookie}"

	def page_of(self, order):
		"""The order page as its customer gets it, signed in through the shop's door."""
		password = frappe.generate_hash(length=20)
		update_password(USER, password)
		frappe.db.commit()
		self.addCleanup(frappe.db.delete, "Sessions", {"user": USER})
		client = get_test_client()
		headers = {"X-Forwarded-For": "198.51.100.202", "Accept": "application/json"}
		signed_in = make_request(
			target=client.post, args=(SIGN_IN,), kwargs={"data": {"usr": USER, "pwd": password}, "headers": headers}
		)
		self.assertEqual(signed_in.status_code, 200, signed_in.get_data(as_text=True)[:300])
		page = make_request(target=client.get, args=(f"/orders/{order}",), kwargs={"headers": {"Accept": "text/html"}})
		self.assertEqual(page.status_code, 200, page.get_data(as_text=True)[:300])
		return page.get_data(as_text=True)

	def the_shop_offers(self, *accounts):
		rows = [frappe._dict(payment_gateway_account=account) for account in accounts]
		return patch("webshop.webshop.utils.payment_methods.rows_for_group", return_value=rows)

	# --- 1. the order page's Pay button ---------------------------------------------

	def test_the_pay_button_reads_no_bank_details_of_another_party(self):
		order = self.place_an_order()
		frappe.set_user(USER)
		with (
			patch(
				"erpnext.accounts.doctype.payment_request.payment_request.PaymentRequest.get_payment_url",
				return_value="https://pay.example.test/order",
			),
			patch(
				"erpnext.accounts.doctype.payment_request.payment_request.PaymentRequest.payment_gateway_validation",
				return_value=False,
			),
		):
			answer = call(
				ORDER_PAY,
				dt="Sales Order",
				dn=order,
				party_type="Supplier",
				party=SUPPLIER,
				submit_doc=1,
				mute_email=1,
				recipient_id="somebody-else@example.test",
			)
		frappe.set_user("Administrator")
		self.assertNotIn(BANK_NUMBER, frappe.as_json(answer), "a third party's account in the answer")
		rows = frappe.get_all(
			"Payment Request",
			filters={"reference_name": order},
			fields=["party_type", "party", "bank_account", "bank_account_no", "email_to"],
		)
		self.assertTrue(rows, "the buyer's request is raised")
		for row in rows:
			self.assertEqual((row.party_type, row.party), ("Customer", CUSTOMER))
			self.assertFalse(row.bank_account)
			self.assertFalse(row.bank_account_no)
			self.assertNotEqual(row.email_to, "somebody-else@example.test")

	def test_the_pay_button_forwards_only_what_the_page_sends(self):
		order = self.place_an_order()
		frappe.set_user(USER)
		with patch(
			"erpnext.accounts.doctype.payment_request.payment_request.make_payment_request", return_value={}
		) as erpnext_call:
			call(
				ORDER_PAY,
				dt="Sales Order",
				dn=order,
				submit_doc=1,
				order_type="Shopping Cart",
				loyalty_points=10,
				payment_gateway_account="not the shop's account",
				payment_request_type="Outward",
				party_name="somebody",
				mode_of_payment="Cash",
				ref_doc={"doctype": "Sales Order"},
			)
		self.assertEqual(frappe.session.user, USER, "the session is the buyer's again")
		self.assertEqual(
			erpnext_call.call_args.kwargs,
			{
				"dt": "Sales Order",
				"dn": order,
				"submit_doc": 1,
				"order_type": "Shopping Cart",
				"loyalty_points": 10,
			},
		)

	def test_the_buyer_pays_their_own_order_on_the_shop_s_account(self):
		order = self.place_an_order()
		settings_account = self.gateway_account
		before = frappe.db.get_single_value("Webshop Settings", "payment_gateway_account")
		self.addCleanup(frappe.db.set_single_value, "Webshop Settings", "payment_gateway_account", before)
		frappe.db.set_single_value("Webshop Settings", "payment_gateway_account", settings_account)
		frappe.set_user(USER)
		with (
			patch(
				"erpnext.accounts.doctype.payment_request.payment_request.PaymentRequest.get_payment_url",
				return_value="https://pay.example.test/order",
			),
			patch(
				"erpnext.accounts.doctype.payment_request.payment_request.PaymentRequest.payment_gateway_validation",
				return_value=False,
			),
		):
			call(
				ORDER_PAY,
				dt="Sales Order",
				dn=order,
				submit_doc=1,
				order_type="Shopping Cart",
				payment_gateway_account=settings_account,
			)
		self.assertEqual(frappe.local.response.get("location"), "https://pay.example.test/order")
		frappe.set_user("Administrator")
		request = frappe.db.get_value(
			"Payment Request",
			{"reference_name": order},
			["docstatus", "party", "payment_gateway_account"],
			as_dict=True,
		)
		self.assertEqual((request.docstatus, request.party), (1, CUSTOMER))
		self.assertEqual(request.payment_gateway_account, settings_account)

	def test_a_stranger_does_not_pay_an_order_that_is_not_theirs(self):
		order = self.place_an_order()
		frappe.set_user(STRANGER)
		with self.assertRaises(frappe.PermissionError):
			call(ORDER_PAY, dt="Sales Order", dn=order, submit_doc=1, order_type="Shopping Cart")

	def test_a_cancelled_or_closed_order_cannot_be_paid(self):
		order = self.place_an_order()
		# an order left Closed cannot be cancelled by the fixture's purge
		self.addCleanup(frappe.db.set_value, "Sales Order", order, {"docstatus": 1, "status": "To Bill"})
		for values in ({"docstatus": 2, "status": "Cancelled"}, {"docstatus": 1, "status": "Closed"}):
			with self.subTest(status=values["status"]):
				frappe.db.set_value("Sales Order", order, values)
				frappe.set_user(USER)
				with patch(
					"erpnext.accounts.doctype.payment_request.payment_request.make_payment_request"
				) as erpnext_call:
					with self.assertRaises(frappe.PermissionError):
						call(ORDER_PAY, dt="Sales Order", dn=order, submit_doc=1, order_type="Shopping Cart")
				erpnext_call.assert_not_called()
				frappe.set_user("Administrator")

	def test_the_order_page_offers_to_pay_an_open_order_only(self):
		before = frappe.db.get_single_value("Webshop Settings", "enable_checkout")
		self.addCleanup(frappe.db.set_single_value, "Webshop Settings", "enable_checkout", before)
		frappe.db.set_single_value("Webshop Settings", "enable_checkout", 1)
		order = self.place_an_order()
		frappe.db.commit()
		self.assertIn('id="pay-for-order"', self.page_of(order), "an open order is offered")
		frappe.db.set_value("Sales Order", order, {"docstatus": 2, "status": "Cancelled"})
		frappe.db.commit()
		self.assertNotIn('id="pay-for-order"', self.page_of(order), "a cancelled order is not")

	# --- 2. the fees of the invoice tile --------------------------------------------

	def test_a_stranger_neither_reads_nor_rewrites_a_cart(self):
		quotation = self.fill_the_cart()
		before = frappe.db.get_value("Quotation", quotation.name, "modified")
		frappe.set_user(STRANGER)
		with self.assertRaises(frappe.PermissionError):
			call(REMOVE_FEES, quotation=quotation.name)
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("Quotation", quotation.name, "modified"), before)

	def test_a_quotation_of_the_same_customer_that_is_no_cart_is_refused(self):
		quotation = self.fill_the_cart()
		frappe.db.set_value("Quotation", quotation.name, "order_type", "Sales")
		frappe.set_user(USER)
		with self.assertRaises(frappe.PermissionError):
			call(REMOVE_FEES, quotation=quotation.name)

	def test_a_filter_is_no_quotation(self):
		self.fill_the_cart()
		frappe.set_user(USER)
		with self.assertRaises(frappe.PermissionError):
			call(REMOVE_FEES, quotation={"name": ["like", "%"]})

	def test_the_buyer_clears_the_fees_of_their_own_cart(self):
		quotation = self.fill_the_cart()
		frappe.set_user(USER)
		with upstream_checks():
			answer = call(REMOVE_FEES, quotation=quotation.name)
		self.assertEqual(answer.get("doc", {}).get("name"), quotation.name, (answer, self.last_error()))

	def test_the_internal_calls_still_hand_a_document(self):
		quotation = self.fill_the_cart()
		frappe.set_user(USER)
		with upstream_checks():
			answer = webshopsi_cart.update_payment_terms(quotation.name, "")
			doc = frappe.get_doc("Quotation", quotation.name)
			self.assertEqual(answer.get("doc", {}).get("name"), quotation.name, answer)
			self.assertIn("doc", webshopsi_cart.remove_webshopsi_fees(doc))

	# --- 3. a failed payment ---------------------------------------------------------

	def test_the_buyer_s_decline_is_recorded(self):
		request = self.a_request()
		frappe.set_user(USER)
		answer = call(FAIL_PAYMENT, payment_request_id=request, error_message="Your card was declined.")
		self.assertEqual(answer["status"], "error")
		self.assertEqual(answer["message"], "Your card was declined.")
		frappe.set_user("Administrator")
		state = self.state_of(request)
		self.assertEqual((state.status, state.docstatus), ("Failed", 1), self.last_error())
		self.assertEqual(state.message, "Your card was declined.")

	def test_a_request_past_its_payment_stays_as_it_is(self):
		request = self.a_request()
		for status, docstatus in (
			("Paid", 1),
			("Partially Paid", 1),
			("Payment Ordered", 1),
			("Cancelled", 2),
		):
			with self.subTest(status=status):
				frappe.db.set_value("Payment Request", request, {"status": status, "docstatus": docstatus})
				frappe.db.commit()
				frappe.set_user(USER)
				call(FAIL_PAYMENT, payment_request_id=request, error_message="no")
				frappe.set_user("Administrator")
				state = self.state_of(request)
				self.assertEqual((state.status, state.docstatus), (status, docstatus))
				self.assertNotEqual(state.message, "no")

	def test_a_request_the_gateway_confirmed_stays_as_it_is(self):
		request = self.a_request()
		self.stripe_has_charged(request)
		frappe.set_user(USER)
		call(FAIL_PAYMENT, payment_request_id=request, error_message="no")
		frappe.set_user("Administrator")
		self.assertEqual(self.state_of(request).status, "Draft")

	def test_a_filter_is_no_request(self):
		request = self.a_request()
		frappe.set_user(USER)
		with self.assertRaises(FrappeTypeError):
			# the filter names this request alone: on the code before the guard it is the UPDATE's own filter
			call(FAIL_PAYMENT, payment_request_id={"name": ["like", request]}, error_message="no")
		frappe.set_user("Administrator")
		self.assertEqual(self.state_of(request).status, "Draft")

	def test_the_text_of_a_failure_is_plain_text(self):
		request = self.a_request()
		frappe.set_user(USER)
		call(FAIL_PAYMENT, payment_request_id=request, error_message="{{ doc.name }} <b>{% x %}</b> " + "y" * 900)
		frappe.set_user("Administrator")
		message = self.state_of(request).message
		for mark in ("{{", "{%", "<b>"):
			self.assertNotIn(mark, message)
		self.assertLess(len(message), 300)

	def test_nobody_else_fails_a_request_and_no_trace_is_written(self):
		request = self.a_request()
		before = error_rows()
		frappe.set_user(STRANGER)
		with self.assertRaises(frappe.PermissionError):
			call(FAIL_PAYMENT, payment_request_id=request, error_message="no")
		frappe.set_user("Administrator")
		self.assertEqual(self.state_of(request).status, "Draft")
		self.assertEqual(error_rows(), before, "a refusal is no fault")

	def test_an_anonymous_call_gets_a_real_refusal(self):
		request = self.a_request()
		before = error_rows()
		for url in (FAIL_URL, CONCLUDE_URL):
			with self.subTest(url=url):
				response = http("post", url, data={"payment_request_id": request, "error_message": "no"})
				self.assertEqual(response.status_code, 403, response.get_data(as_text=True)[:300])
		self.assertEqual(self.state_of(request).status, "Draft")
		self.assertEqual(error_rows(), before, "a refusal is no fault")

	def test_a_name_that_does_not_exist_gets_the_same_refusal(self):
		for url in (FAIL_URL, CONCLUDE_URL):
			with self.subTest(url=url):
				response = http("post", url, data={"payment_request_id": "ACC-PRQ-NOT-THERE"})
				self.assertEqual(response.status_code, 403, response.get_data(as_text=True)[:300])

	def test_a_guest_s_decline_is_recorded_and_the_card_tile_gets_its_answer(self):
		request, cookie = self.a_guest_request()
		response = http(
			"post",
			FAIL_URL,
			cookie=cookie,
			data={"payment_request_id": request, "error_message": "Your card was declined."},
		)
		self.assertEqual(response.status_code, 200, "the tile unfreezes in its callback, on a 200 only")
		self.assertEqual(response.json["message"]["message"], "Your card was declined.")
		self.assertEqual(self.state_of(request).status, "Failed")

	def test_a_guest_buyer_hears_that_the_payment_is_not_confirmed_yet(self):
		request, cookie = self.a_guest_request()
		response = http("post", CONCLUDE_URL, cookie=cookie, data={"payment_request_id": request})
		self.assertEqual(response.status_code, 200, "the tile unfreezes in its callback, on a 200 only")
		language = frappe.get_system_settings("language") or "en"
		self.assertEqual(response.json["message"]["message"], frappe._(NOT_CONFIRMED_YET, lang=language))
		self.assertEqual(self.real_orders(), [])

	def test_the_gateway_s_word_still_concludes_for_a_visitor_with_no_session(self):
		request = self.a_request()
		self.stripe_has_charged(request)
		with no_gateway():
			response = http("post", CONCLUDE_URL, data={"payment_request_id": request})
		self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:300])
		frappe.db.rollback()
		self.assertEqual(response.json["message"]["status"], "success", (response.json, self.last_error()))
		self.assertEqual(len(self.real_orders()), 1)

	def test_a_buyer_who_asks_again_writes_one_row_an_hour(self):
		request = self.a_request()
		frappe.db.rollback()
		before = frappe.db.count("Error Log", {"method": NOT_CONFIRMED_TITLE})
		frappe.set_user(USER)
		for _ in range(3):
			answer = call(CONCLUDE_PAYMENT, payment_request_id=request)
		self.assertEqual(answer["message"], NOT_CONFIRMED_YET, "the buyer is told each time")
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.count("Error Log", {"method": NOT_CONFIRMED_TITLE}), before + 1)

	def test_the_web_checkout_still_finds_the_buyer(self):
		from payments.integrations.web_checkout import require_own_request

		request = self.a_request()
		frappe.set_user(USER)
		self.assertEqual(require_own_request(request).name, request)
		frappe.set_user(STRANGER)
		self.assertRaises(frappe.PermissionError, require_own_request, request)

	# --- 52. a refusal leaves no Error Log row ----------------------------------------

	def test_a_refused_conclusion_leaves_no_trace(self):
		request = self.a_request()
		before = error_rows()
		frappe.set_user(STRANGER)
		with self.assertRaises(frappe.PermissionError):
			call(CONCLUDE_PAYMENT, payment_request_id=request)
		frappe.set_user("Administrator")
		self.assertEqual(error_rows(), before, "a refusal is no fault")

	def test_a_refused_request_leaves_no_trace(self):
		quotation = self.fill_the_cart()
		before = error_rows()
		frappe.set_user("Guest")
		answer = call(RAISE_REQUEST, quotation_id=quotation.name)
		self.assertEqual(answer["status"], "error")
		frappe.set_user("Administrator")
		self.assertEqual(error_rows(), before, "a refusal is no fault")

	def test_a_real_fault_is_still_written(self):
		quotation = self.fill_the_cart()
		before = error_rows()
		frappe.set_user(USER)
		with patch("webshop.controllers.payment_handler.PaymentHandler", side_effect=ValueError("broken")):
			answer = call(RAISE_REQUEST, quotation_id=quotation.name)
		self.assertEqual(answer["status"], "error")
		frappe.set_user("Administrator")
		self.assertEqual(error_rows(), before + 1)

	# --- 8, 24. the date of birth of the invoice tile ---------------------------------

	def test_the_buyer_reads_their_own_date_of_birth(self):
		contact = self.contact_of(USER)
		frappe.db.set_value("Contact", contact, "birthday", "1990-02-03")
		frappe.set_user(USER)
		self.assertEqual(str(call(BIRTHDAY, contact_name=contact)), "1990-02-03")

	def test_nobody_reads_the_date_of_birth_of_someone_else(self):
		contact = self.contact_of(USER)
		frappe.db.set_value("Contact", contact, "birthday", "1990-02-03")
		frappe.set_user(STRANGER)
		self.assertIsNone(call(BIRTHDAY, contact_name=contact))

	def test_a_filter_is_no_contact(self):
		frappe.set_user(STRANGER)
		with self.assertRaises(FrappeTypeError):
			call(BIRTHDAY, contact_name={"email_id": USER})
		with self.assertRaises(FrappeTypeError):
			call(
				AUTHORIZED,
				gateway_settings="WebshopSI Settings",
				birthday="2001-01-01",
				contactName={"email_id": USER},
			)

	def test_the_invoice_tile_orders_and_keeps_the_buyer_s_date_of_birth(self):
		account = self.invoice_tile()
		self.fill_the_cart()
		contact = self.contact_of(USER)
		frappe.set_user(USER)
		with upstream_checks(), self.the_shop_offers(account):
			answer = call(
				AUTHORIZED, gateway_settings="WebshopSI Settings", birthday="1990-02-03", contactName=contact
			)
		frappe.set_user("Administrator")
		self.assertEqual(answer.get("status"), "success", (answer, self.last_error()))
		self.assertEqual(len(self.real_orders()), 1)
		self.assertEqual(str(frappe.db.get_value("Contact", contact, "birthday")), "1990-02-03")

	def test_the_tile_writes_nothing_on_the_contact_of_someone_else(self):
		account = self.invoice_tile()
		self.fill_the_cart(user=STRANGER)
		contact = self.contact_of(USER)
		frappe.db.set_value("Contact", contact, "birthday", "1980-05-06")
		frappe.db.commit()
		frappe.set_user(STRANGER)
		with upstream_checks(), self.the_shop_offers(account):
			answer = call(
				AUTHORIZED, gateway_settings="WebshopSI Settings", birthday="2001-01-01", contactName=contact
			)
		frappe.set_user("Administrator")
		self.assertEqual(str(frappe.db.get_value("Contact", contact, "birthday")), "1980-05-06")
		self.assertEqual(answer.get("status"), "success", "a colleague's contact does not stop the order")

	def test_the_tile_is_the_invoice_tile_and_no_other_gateway(self):
		self.fill_the_cart()
		frappe.db.set_value("Payment Gateway", GATEWAY, "gateway_settings", "Stripe Settings")
		frappe.db.commit()
		self.addCleanup(frappe.db.set_value, "Payment Gateway", GATEWAY, "gateway_settings", None)
		frappe.set_user(USER)
		with upstream_checks(), self.the_shop_offers(self.gateway_account):
			answer = call(AUTHORIZED, gateway_settings="Stripe Settings")
		frappe.set_user("Administrator")
		self.assertEqual(answer.get("status"), "error", answer)
		self.assertEqual(self.real_orders(), [], "no unpaid order on a card gateway")

	def test_the_tile_needs_the_shop_to_offer_it(self):
		self.invoice_tile()
		self.fill_the_cart()
		frappe.set_user(USER)
		with upstream_checks(), self.the_shop_offers(self.gateway_account):
			answer = call(AUTHORIZED, gateway_settings="WebshopSI Settings")
		frappe.set_user("Administrator")
		self.assertEqual(answer.get("status"), "error", answer)
		self.assertEqual(self.real_orders(), [], "no unpaid order on a method this customer is not offered")

	# --- 26. the migration ------------------------------------------------------------

	def test_the_migration_is_no_web_method(self):
		frappe.set_user(USER)
		self.assertRaises(frappe.PermissionError, frappe.is_whitelisted, frappe.get_attr(MIGRATION))
		frappe.set_user("Administrator")
		self.assertTrue(callable(webshopsi_settings.migrate_installment_fees_to_templates))

	# --- 33. the PayPal tile ----------------------------------------------------------

	def paypal_call(self, quotation, token, user=USER):
		settings = frappe.get_cached_doc("Webshop Settings")
		fake_settings = frappe._dict(
			payment_methods=[frappe._dict(payment_gateway_account=self.gateway_account, payment_terms_template=None)],
			enabled=settings.enabled,
		)
		real = frappe.get_cached_doc

		def get_cached_doc(doctype, *args, **kwargs):
			return fake_settings if doctype == "Webshop Settings" else real(doctype, *args, **kwargs)

		controller = patch("payments.utils.get_payment_gateway_controller").start()
		self.addCleanup(patch.stopall)
		controller.return_value.get_payment_url.return_value = "https://pay.example.test/paypal"
		frappe.set_user(user)
		with upstream_checks(), patch.object(frappe, "get_cached_doc", side_effect=get_cached_doc):
			result = call(PAYPAL, quotation_id=quotation.name, idempotency_token=token)
		frappe.set_user("Administrator")
		frappe.db.commit()
		return result

	def test_a_filter_is_no_token(self):
		quotation = self.fill_the_cart()
		frappe.set_user(USER)
		with self.assertRaises(FrappeTypeError):
			call(PAYPAL, quotation_id=quotation.name, idempotency_token=["!=", ""])

	def test_the_token_of_another_buyer_names_no_order(self):
		order = self.place_an_order(USER)
		token = self.token()
		request = frappe.new_doc("Payment Request")
		request.update(
			{
				"payment_request_type": "Inward",
				"reference_doctype": "Sales Order",
				"reference_name": order,
				"party_type": "Customer",
				"party": CUSTOMER,
				"grand_total": 10,
				"currency": "CHF",
				"status": "Paid",
				"custom_idempotency_token": token,
			}
		)
		request.flags.ignore_validate = True
		request.flags.ignore_links = True
		request.insert(ignore_permissions=True, ignore_mandatory=True)
		frappe.db.commit()

		quotation = self.fill_the_cart(user=STRANGER)
		result = self.paypal_call(quotation, token, user=STRANGER)

		self.assertNotIn("existing_order", result)
		self.assertNotIn(order, frappe.as_json(result))

	def test_a_double_click_finds_the_request_again(self):
		quotation = self.fill_the_cart()
		token = self.token()
		first = self.paypal_call(quotation, token)
		self.assertEqual(first.get("status"), "success", (first, self.last_error()))
		second = self.paypal_call(quotation, token)
		self.assertEqual(second, first)
		self.assertEqual(frappe.db.count("Payment Request", {"party": CUSTOMER}), 1)

	def test_a_paypal_request_of_another_total_is_not_reused(self):
		quotation = self.fill_the_cart()
		token = self.token()
		self.paypal_call(quotation, token)
		due = self.charge_shipping(quotation.name, 7)
		self.paypal_call(quotation, token)
		totals = frappe.get_all("Payment Request", filters={"party": CUSTOMER, "docstatus": 0}, pluck="grand_total")
		self.assertEqual([flt(total, 2) for total in totals], [flt(due, 2)])

	# --- 37. an order with nothing paid -----------------------------------------------

	def test_a_cart_with_an_amount_to_pay_is_not_ordered_for_free(self):
		quotation = self.fill_the_cart()
		frappe.set_user(USER)
		with upstream_checks():
			answer = call(DIRECT_ORDER, idempotency_token=self.token())
		frappe.set_user("Administrator")
		self.assertEqual(answer.get("status"), "error", answer)
		self.assertEqual(self.real_orders(), [])
		self.assertEqual(frappe.db.get_value("Quotation", quotation.name, "docstatus"), 0)

	def test_a_cart_with_nothing_to_pay_is_ordered(self):
		quotation = self.fill_the_cart()
		doc = frappe.get_doc("Quotation", quotation.name)
		doc.apply_discount_on = "Grand Total"
		doc.additional_discount_percentage = 100
		save_as_shop(doc, ignore_permissions=True)
		self.assertEqual(flt(frappe.db.get_value("Quotation", quotation.name, "rounded_total")), 0)
		frappe.db.commit()
		frappe.set_user(USER)
		with upstream_checks():
			answer = call(DIRECT_ORDER, idempotency_token=self.token())
		frappe.set_user("Administrator")
		self.assertEqual(answer.get("status"), "success", (answer, self.last_error()))
		self.assertEqual(len(self.real_orders()), 1)

	# --- 38. a request kept for a total that moved ------------------------------------

	def test_a_request_of_another_total_is_not_reused(self):
		quotation = self.fill_the_cart()
		token = self.token()
		first = self.raise_the_request(quotation, token)
		self.assertEqual(first.get("status"), "success", (first, self.last_error()))
		due = self.charge_shipping(quotation.name, 7)

		second = self.raise_the_request(quotation, token)

		self.assertEqual(second.get("status"), "success", (second, self.last_error()))
		self.assertNotEqual(second.get("message"), "Using existing payment request", second)
		asked = frappe.db.get_value("Payment Request", second["payment_request_id"], "grand_total")
		self.assertEqual(flt(asked, 2), flt(due, 2), "the request asks what the cart costs now")

	def test_the_same_cart_finds_its_request_again(self):
		quotation = self.fill_the_cart()
		token = self.token()
		first = self.raise_the_request(quotation, token)
		second = self.raise_the_request(quotation, token)
		self.assertEqual(second.get("payment_request_id"), first.get("payment_request_id"))
		self.assertEqual(second.get("message"), "Using existing payment request")
		self.assertTrue(pending_order.is_placeholder(
			frappe.db.get_value("Payment Request", first["payment_request_id"], "reference_name")
		))


class TestTheShopSignIn(FrappeTestCase):
	"""Through the real application: the dialog reads the status of the answer, the browser its cookie."""

	CUSTOMER_ACCOUNT = "wstest-w2-customer@yopmail.com"
	STAFF_ACCOUNT = "wstest-w2-staff@yopmail.com"
	TWO_FACTOR_ROLE = "WSTEST W2 Two Factor"
	NEW_ACCOUNT = "wstest-w2-new@yopmail.com"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.password = frappe.generate_hash(length=20)
		cls.purge()
		for email, role in ((cls.CUSTOMER_ACCOUNT, "Customer"), (cls.STAFF_ACCOUNT, "Sales User")):
			user = frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Wstest", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
			user.add_roles(role)
			update_password(email, cls.password)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		cls.purge()
		super().tearDownClass()

	@classmethod
	def purge(cls):
		for email in (cls.CUSTOMER_ACCOUNT, cls.STAFF_ACCOUNT, cls.NEW_ACCOUNT):
			frappe.db.delete("Sessions", {"user": email})
			frappe.db.delete("Activity Log", {"user": email})
			frappe.db.delete("DefaultValue", {"defkey": ["like", f"{email}%"]})
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, force=True, ignore_permissions=True)
		if frappe.db.exists("Role", cls.TWO_FACTOR_ROLE):
			frappe.delete_doc("Role", cls.TWO_FACTOR_ROLE, force=True, ignore_permissions=True)
		frappe.db.commit()

	def setUp(self):
		frappe.set_user("Administrator")
		self.peer = self.a_peer()
		self.throttled = []

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		for email in (self.CUSTOMER_ACCOUNT, self.STAFF_ACCOUNT):
			frappe.db.delete("Sessions", {"user": email})
			LoginAttemptTracker(email).add_success_attempt()
		LoginAttemptTracker(self.peer).add_success_attempt()
		for name, identity in self.throttled:
			throttle.reset(name, identity)
		frappe.db.commit()

	def a_peer(self):
		TestTheShopSignIn.next_peer = getattr(TestTheShopSignIn, "next_peer", 0) + 1
		return f"198.51.100.{TestTheShopSignIn.next_peer}"

	def http(self, verb, path, forwarded=None, **kwargs):
		client = get_test_client(use_cookies=False)
		headers = {"X-Forwarded-For": forwarded or self.peer, "Accept": "application/json"}
		return make_request(target=getattr(client, verb), args=(path,), kwargs={"headers": headers, **kwargs})

	def sign_in(self, email=None, password=None, **kwargs):
		data = {"usr": email or self.CUSTOMER_ACCOUNT, "pwd": password or self.password}
		return self.http("post", SIGN_IN, data=data, **kwargs)

	def full_budget(self, name, limit):
		"""This connection has used up window `name` of a throttle."""
		for _ in range(limit):
			throttle.hit(name, self.peer, 60)
		self.throttled.append((name, self.peer))

	def sessions_of(self, email):
		frappe.db.rollback()
		return frappe.db.count("Sessions", {"user": email})

	def assertNoSession(self, response, email=None):
		cookies = response.headers.getlist("Set-Cookie")
		opened = [c for c in cookies if c.startswith("sid=") and not c.startswith("sid=Guest")]
		self.assertEqual(opened, [], response.get_data(as_text=True)[:400])
		self.assertEqual(self.sessions_of(email or self.CUSTOMER_ACCOUNT), 0)

	def set_system_setting(self, field, value):
		before = frappe.db.get_single_value("System Settings", field)
		self.addCleanup(self._write_system_setting, field, before)
		self._write_system_setting(field, value)

	def _write_system_setting(self, field, value):
		frappe.db.set_single_value("System Settings", field, value)
		frappe.clear_document_cache("System Settings", "System Settings")
		frappe.db.commit()

	def two_factor_for(self, *emails):
		if not frappe.db.exists("Role", self.TWO_FACTOR_ROLE):
			frappe.get_doc(
				{"doctype": "Role", "role_name": self.TWO_FACTOR_ROLE, "two_factor_auth": 1, "desk_access": 0}
			).insert(ignore_permissions=True)
		for email in emails:
			frappe.get_doc("User", email).add_roles(self.TWO_FACTOR_ROLE)
			self.addCleanup(self._drop_two_factor, email)
		self.set_system_setting("enable_two_factor_auth", 1)

	def _drop_two_factor(self, email):
		frappe.get_doc("User", email).remove_roles(self.TWO_FACTOR_ROLE)
		frappe.db.delete("DefaultValue", {"defkey": ["like", f"{email}%"]})
		frappe.db.commit()

	# --- what still passes ------------------------------------------------------------

	def test_a_customer_signs_in_with_the_right_password(self):
		response = self.sign_in()
		self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:400])
		self.assertEqual(response.json["message"]["message"], "success")
		self.assertEqual(self.sessions_of(self.CUSTOMER_ACCOUNT), 1)

	def test_a_desk_account_with_nothing_more_to_prove_signs_in_as_on_the_sign_in_page(self):
		response = self.sign_in(self.STAFF_ACCOUNT)
		self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:400])
		self.assertEqual(self.sessions_of(self.STAFF_ACCOUNT), 1)
		self.assertIn("app", response.json["message"]["home_page"], "the desk is where it belongs")

	# --- the door of the normal login -------------------------------------------------

	def test_a_wrong_password_opens_no_session(self):
		response = self.sign_in(password="deliberately-wrong")
		self.assertEqual(response.status_code, 401)
		self.assertEqual(response.json["message"]["message"], "error")
		self.assertNoSession(response)

	def test_a_disabled_account_opens_no_session(self):
		frappe.db.set_value("User", self.CUSTOMER_ACCOUNT, "enabled", 0)
		frappe.db.commit()
		self.addCleanup(self._enable)
		response = self.sign_in()
		self.assertEqual(response.status_code, 401)
		self.assertNoSession(response)

	def _enable(self):
		frappe.db.set_value("User", self.CUSTOMER_ACCOUNT, "enabled", 1)
		frappe.db.commit()

	def test_repeated_failures_lock_the_account_and_the_dialog_gets_its_button_back(self):
		self.set_system_setting("allow_consecutive_login_attempts", 3)
		self.set_system_setting("allow_login_after_fail", 60)
		# frappe locks above the setting, not at it (LoginAttemptTracker.is_user_allowed)
		for _ in range(4):
			self.assertEqual(self.sign_in(password="deliberately-wrong").status_code, 401)
		response = self.sign_in()
		self.assertEqual(response.status_code, 403, "403 is the status the dialog answers to")
		self.assertIn("locked", response.get_data(as_text=True))
		self.assertNoSession(response)

	def test_two_factor_is_not_skipped_by_the_shop_s_door(self):
		self.two_factor_for(self.CUSTOMER_ACCOUNT, self.STAFF_ACCOUNT)
		for email in (self.CUSTOMER_ACCOUNT, self.STAFF_ACCOUNT):
			with self.subTest(email=email):
				response = self.sign_in(email)
				self.assertEqual(response.status_code, 403, response.get_data(as_text=True)[:400])
				self.assertEqual(response.json["message"]["reason_code"], "use_the_sign_in_page")
				self.assertIn("/login", response.get_data(as_text=True))
				self.assertNoSession(response, email)

	def test_an_expired_password_is_not_skipped_by_the_shop_s_door(self):
		self.set_system_setting("force_user_to_reset_password", 1)
		frappe.db.set_value("User", self.CUSTOMER_ACCOUNT, "last_password_reset_date", "2020-01-01")
		frappe.db.commit()
		response = self.sign_in()
		self.assertEqual(response.status_code, 403, response.get_data(as_text=True)[:400])
		self.assertIn("update-password", response.json["message"]["redirect_to"])
		self.assertNoSession(response)

	def test_a_site_without_password_sign_in_refuses_it_here_too(self):
		self.set_system_setting("disable_user_pass_login", 1)
		response = self.sign_in()
		self.assertEqual(response.status_code, 401, response.get_data(as_text=True)[:400])
		self.assertNoSession(response)

	def test_a_password_does_not_travel_in_an_address(self):
		response = self.http(
			"get", SIGN_IN, query_string={"usr": self.CUSTOMER_ACCOUNT, "pwd": self.password}
		)
		self.assertEqual(response.status_code, 403, response.get_data(as_text=True)[:400])
		self.assertNoSession(response)

	def test_a_list_is_neither_a_user_nor_a_password(self):
		for body in (
			{"usr": ["like", "%"], "pwd": self.password},
			{"usr": self.CUSTOMER_ACCOUNT, "pwd": [self.password]},
		):
			with self.subTest(body=list(body)):
				response = self.http("post", SIGN_IN, json=body)
				self.assertEqual(response.status_code, 401, response.get_data(as_text=True)[:400])
				self.assertNoSession(response)

	def test_the_second_factor_of_another_door_is_no_key_here(self):
		response = self.http(
			"post",
			SIGN_IN,
			data={"usr": self.CUSTOMER_ACCOUNT, "pwd": "deliberately-wrong", "tmp_id": "x", "otp": "000000"},
		)
		self.assertEqual(response.status_code, 401, response.get_data(as_text=True)[:400])
		self.assertNoSession(response)

	# --- the limit, per connection ----------------------------------------------------

	def test_the_limit_of_a_connection_is_held(self):
		self.full_budget("custom_login_minute", SIGN_INS_PER_MINUTE)
		self.throttled.append(("custom_login_hour", self.peer))
		response = self.sign_in()
		self.assertEqual(response.status_code, 429, response.get_data(as_text=True)[:400])
		self.assertNoSession(response)

	def test_the_limit_counts_the_address_nginx_saw(self):
		self.full_budget("custom_login_minute", SIGN_INS_PER_MINUTE)
		self.throttled.append(("custom_login_hour", self.peer))
		response = self.sign_in(forwarded=f"203.0.113.77, {self.peer}")
		self.assertEqual(response.status_code, 429)

	def test_another_connection_has_its_own_budget(self):
		self.full_budget("custom_login_minute", SIGN_INS_PER_MINUTE)
		self.throttled.append(("custom_login_hour", self.peer))
		other = self.a_peer()
		self.throttled.extend((("custom_login_minute", other), ("custom_login_hour", other)))
		response = self.sign_in(forwarded=other)
		self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:400])

	# --- 21. check_email --------------------------------------------------------------

	def test_an_operator_is_no_address(self):
		response = self.http("post", CHECK_EMAIL, json={"email": ["like", "a%"]})
		self.assertEqual(response.status_code, 417, response.get_data(as_text=True)[:400])

	def test_the_dialog_still_tells_a_known_address_where_a_code_is_not_mailed(self):
		frappe.set_user("Guest")
		with patch("webshop.webshop.auth.code_sign_in.available", return_value=False):
			known = api.check_email(self.CUSTOMER_ACCOUNT)
			unknown = api.check_email("wstest-w2-nobody@yopmail.com")
		self.assertTrue(known["exists"])
		self.assertFalse(unknown["exists"])

	def test_an_address_gives_no_first_name_away(self):
		frappe.set_user("Guest")
		with patch("webshop.webshop.auth.code_sign_in.available", return_value=False):
			self.assertIsNone(api.check_email(self.CUSTOMER_ACCOUNT)["first_name"])

	def test_the_address_check_has_a_limit(self):
		self.full_budget("check_email_minute", ADDRESS_CHECKS_PER_MINUTE)
		self.throttled.append(("check_email_hour", self.peer))
		response = self.http("post", CHECK_EMAIL, data={"email": self.CUSTOMER_ACCOUNT})
		self.assertEqual(response.status_code, 429, response.get_data(as_text=True)[:400])

	# --- 28, 48. create_account -------------------------------------------------------

	def form(self, **fields):
		return patch.object(frappe.local, "form_dict", frappe._dict(fields))

	def test_the_sign_up_limit_counts_the_address_nginx_saw(self):
		frappe.local.request_ip = "203.0.113.9"
		self.addCleanup(setattr, frappe.local, "request_ip", None)
		with patch(
			"frappe.get_request_header",
			side_effect=lambda key, default=None: "203.0.113.9, 198.51.100.50" if key == "X-Forwarded-For" else default,
		):
			key = api._sign_ups_key()
		self.assertIn("198.51.100.50", key)
		self.assertNotIn("203.0.113.9", key)

	def test_a_desk_account_is_told_from_a_customer_by_nothing(self):
		frappe.set_user("Guest")
		answers = []
		for email in (self.STAFF_ACCOUNT, self.CUSTOMER_ACCOUNT):
			with self.form(email=email, first_name="A", last_name="B"):
				answers.append(api.create_account())
		self.assertEqual(answers[0], answers[1])
		self.assertEqual(answers[0]["reason_code"], "account_exists_website", "the dialog goes to the password")

	def test_an_oversized_name_is_cut_and_the_account_counts(self):
		frappe.cache().delete_value(api._sign_ups_key())
		self.addCleanup(frappe.cache().delete_value, api._sign_ups_key())
		frappe.set_user("Guest")
		with (
			self.form(email=self.NEW_ACCOUNT, first_name="x" * 200, last_name="y" * 200),
			patch.object(confirmation, "opens_at_once", return_value=False),
			patch("frappe.core.doctype.user.user.User.send_welcome_mail_to_user"),
		):
			answer = api.create_account()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.delete_doc, "User", self.NEW_ACCOUNT, force=True, ignore_permissions=True)
		self.assertEqual(answer["message"], "success", answer)
		self.assertLessEqual(len(frappe.db.get_value("User", self.NEW_ACCOUNT, "first_name")), 80)
		self.assertLessEqual(len(frappe.db.get_value("User", self.NEW_ACCOUNT, "full_name")), 140)
		self.assertEqual(api._sign_ups_so_far(), 1, "no address probes for free")

	def test_a_value_that_is_no_text_is_a_missing_field(self):
		before = error_rows()
		frappe.set_user("Guest")
		with self.form(email=["a@example.test"], first_name={"a": 1}, last_name="B"):
			self.assertEqual(api.create_account()["reason_code"], "missing_fields")
		frappe.set_user("Administrator")
		self.assertEqual(error_rows(), before)
