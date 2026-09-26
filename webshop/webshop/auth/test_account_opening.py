# //// Neoffice — added file (no upstream equivalent): an account opened at once in the shop, its
# //// address confirmed afterwards (auth/confirmation.py). neoffice-maintenance#691, decision D-9,
# //// 2026-09-25.
"""An account opened at once, and the three things that keep that safe:
- only an address the shop does not know is opened;
- the first way back into the account, which can only go through its mailbox, confirms the
  address and closes the sessions whoever opened it kept;
- an order paid on account waits On Hold for that confirmation, which releases it.
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from webshop.webshop.auth import api, confirmation
from webshop.webshop.shopping_cart import offline_payment
from webshop.webshop.tests.utils import PREFIX, make_test_item, portal_customer, selling_price_list
from webshop.webshop.utils import payment_methods

EMAIL = "e2e.d9-opening@yopmail.com"


def _drop_user(email=EMAIL):
	if frappe.db.exists("User", email):
		frappe.delete_doc("User", email, force=True, ignore_permissions=True)


class TestWhoIsOpenedAtOnce(FrappeTestCase):
	def opens(self, settings=None, known=False, business_only=False, field=True):
		settings = frappe._dict(open_account_at_once=1) if settings is None else settings
		with (
			patch.object(confirmation, "_has_field", return_value=field),
			patch("webshop.webshop.multi_site.site_is_business_only", return_value=business_only),
			patch.object(confirmation.frappe.db, "exists", return_value="CONTACT-1" if known else None) as exists,
		):
			answer = confirmation.opens_at_once(EMAIL, settings)
		return answer, exists

	def test_an_address_the_shop_does_not_know(self):
		answer, exists = self.opens()
		self.assertTrue(answer)
		exists.assert_called_once_with("Contact Email", {"email_id": EMAIL})

	def test_an_address_a_contact_carries_keeps_the_link_first(self):
		# get_party() would attach the new account to that contact's customer, orders and addresses
		self.assertFalse(self.opens(known=True)[0])

	def test_the_switch_a_business_site_and_a_site_not_migrated(self):
		self.assertFalse(self.opens(settings=frappe._dict(open_account_at_once=0))[0])
		self.assertFalse(self.opens(business_only=True)[0])
		self.assertFalse(self.opens(field=False)[0])


class TestCreateAccount(FrappeTestCase):
	def setUp(self):
		_drop_user()
		frappe.set_user("Guest")
		self.form = patch.object(
			frappe.local, "form_dict", frappe._dict(email=EMAIL, first_name="Opening", last_name="Test")
		)
		self.form.start()
		self.mail = patch("frappe.core.doctype.user.user.User.send_welcome_mail_to_user")
		self.mail.start()

	def tearDown(self):
		self.mail.stop()
		self.form.stop()
		frappe.set_user("Administrator")
		_drop_user()

	def test_the_account_is_opened_and_signed_in(self):
		with (
			patch.object(confirmation, "opens_at_once", return_value=True),
			patch.object(confirmation, "open_account") as open_account,
		):
			answer = api.create_account()
		self.assertEqual(answer["message"], "success")
		self.assertTrue(answer["signed_in"])
		self.assertTrue(answer["notice"])
		open_account.assert_called_once_with(EMAIL)
		self.assertEqual(frappe.db.get_value("User", EMAIL, "user_type"), "Website User")

	def test_an_address_kept_for_the_link_is_not_signed_in(self):
		with (
			patch.object(confirmation, "opens_at_once", return_value=False),
			patch.object(confirmation, "open_account") as open_account,
		):
			answer = api.create_account()
		self.assertEqual(answer["message"], "success")
		self.assertNotIn("signed_in", answer)
		open_account.assert_not_called()

	def test_only_accounts_created_count_against_the_limit(self):
		key = api._sign_ups_key()
		frappe.cache().delete_value(key)
		try:
			# a refusal (a missing name) costs nothing
			with patch.object(frappe.local, "form_dict", frappe._dict(email=EMAIL, first_name="", last_name="")):
				self.assertEqual(api.create_account()["reason_code"], "missing_fields")
			self.assertEqual(api._sign_ups_so_far(), 0)
			# an account created counts one
			with patch.object(confirmation, "opens_at_once", return_value=False):
				self.assertEqual(api.create_account()["message"], "success")
			self.assertEqual(api._sign_ups_so_far(), 1)
			# at the limit, nothing more is created from this address
			_drop_user()
			frappe.cache().set_value(key, api.SIGN_UPS_PER_HOUR, expires_in_sec=60)
			self.assertEqual(api.create_account()["reason_code"], "too_many_signups")
			self.assertFalse(frappe.db.exists("User", EMAIL))
		finally:
			frappe.cache().delete_value(key)

	def test_a_site_that_disabled_sign_ups_opens_no_account(self):
		"""Website Settings' "Disable Signup", which frappe's own sign_up() honours."""
		single = frappe.db.get_single_value

		def settings(doctype, field, *args, **kwargs):
			if (doctype, field) == ("Website Settings", "disable_signup"):
				return 1
			return single(doctype, field, *args, **kwargs)

		with patch.object(frappe.db, "get_single_value", side_effect=settings):
			answer = api.create_account()
		self.assertEqual(answer["reason_code"], "signup_disabled")
		self.assertTrue(answer["reason"])
		self.assertFalse(frappe.db.exists("User", EMAIL))

	def test_an_error_says_nothing_of_its_cause(self):
		with (
			patch.object(api.frappe, "get_doc", side_effect=RuntimeError("SMTP host secret.example")),
			patch.object(api.frappe, "log_error"),
		):
			answer = api.create_account()
		self.assertEqual(answer["reason_code"], "unknown_error")
		self.assertNotIn("detail", answer, "the exception's text went to the visitor")
		self.assertNotIn("secret.example", frappe.as_json(answer))


class TestConfirmation(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# the field comes with a patch, which a fresh site ran at install; replaying it is free
		from webshop.patches.add_email_confirmation_field import execute

		execute()

	def setUp(self):
		_drop_user()
		frappe.get_doc(
			{
				"doctype": "User",
				"email": EMAIL,
				"first_name": "Opening",
				"user_type": "Website User",
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		_drop_user()

	def login_manager(self):
		return frappe._dict(user=EMAIL)

	def over_http(self, request=True):
		"""A sign-in that came through an HTTP request (frappe's app sets `http_request`), or not."""
		return patch.object(frappe.local, "http_request", object() if request else None, create=True)

	def test_opening_marks_the_account_and_signs_it_in(self):
		manager = MagicMock()
		with patch.object(frappe.local, "login_manager", manager, create=True):
			confirmation.open_account(EMAIL)
		manager.login_as.assert_called_once_with(EMAIL)
		self.assertTrue(confirmation.pending(EMAIL))
		self.assertFalse(frappe.flags.get("webshop_opening_account"))

	def test_the_first_way_back_in_confirms_and_closes_the_other_sessions(self):
		frappe.db.set_value("User", EMAIL, confirmation.FIELD, 1)
		frappe.set_user("Guest")
		with self.over_http(), patch("frappe.sessions.clear_sessions") as clear:
			confirmation.on_login(self.login_manager())
		self.assertFalse(confirmation.pending(EMAIL))
		clear.assert_called_once_with(EMAIL, keep_current=False, force=True)

	def test_the_opening_itself_and_staff_prove_nothing(self):
		frappe.db.set_value("User", EMAIL, confirmation.FIELD, 1)
		with patch("frappe.sessions.clear_sessions") as clear:
			# the account's own opening signs it in: no confirmation there
			frappe.set_user("Guest")
			frappe.flags.webshop_opening_account = True
			try:
				with self.over_http():
					confirmation.on_login(self.login_manager())
			finally:
				frappe.flags.webshop_opening_account = False
			# staff impersonating the customer on the desk: the staff's own session
			frappe.set_user("Administrator")
			with self.over_http():
				confirmation.on_login(self.login_manager())
			# `bench browse --user`: a Guest session of its own, outside any HTTP request
			frappe.set_user("Guest")
			with self.over_http(request=False):
				confirmation.on_login(self.login_manager())
		self.assertTrue(confirmation.pending(EMAIL))
		clear.assert_not_called()

	def test_an_account_nothing_waits_on_is_left_alone(self):
		frappe.set_user("Guest")
		with self.over_http(), patch("frappe.sessions.clear_sessions") as clear:
			confirmation.on_login(self.login_manager())
		clear.assert_not_called()

	def test_the_confirmation_releases_the_orders_it_held_in_the_background(self):
		frappe.db.set_value("User", EMAIL, confirmation.FIELD, 1)
		frappe.set_user("Guest")
		with (
			self.over_http(),
			patch("frappe.sessions.clear_sessions"),
			patch.object(confirmation, "held_orders", return_value=["SO-HELD"]),
			patch("frappe.enqueue") as enqueue,
		):
			confirmation.on_login(self.login_manager())
		enqueue.assert_called_once_with(
			"webshop.webshop.auth.confirmation.release_held_orders", user=EMAIL, enqueue_after_commit=True
		)
		# nothing held: no job
		frappe.db.set_value("User", EMAIL, confirmation.FIELD, 1)
		with (
			self.over_http(),
			patch("frappe.sessions.clear_sessions"),
			patch.object(confirmation, "held_orders", return_value=[]),
			patch("frappe.enqueue") as enqueue,
		):
			confirmation.on_login(self.login_manager())
		enqueue.assert_not_called()


class TestPaymentOnAccountWaits(FrappeTestCase):
	def rows(self, pending):
		settings = frappe._dict(
			payment_methods=[
				frappe._dict(payment_gateway_account="Card", settlement="Online", only_customer_group=""),
				frappe._dict(payment_gateway_account="Invoice", settlement="On account", only_customer_group=""),
				frappe._dict(payment_gateway_account="Transfer", settlement="Transfer before shipping", only_customer_group=""),
			]
		)
		with (
			patch.object(payment_methods, "group_lineage", return_value=[]),
			patch("webshop.webshop.auth.confirmation.pending", return_value=pending),
		):
			return [row.payment_gateway_account for row in payment_methods.rows_for_group(settings, None)]

	def test_an_unconfirmed_account_pays_on_account_where_the_order_can_wait(self):
		self.assertEqual(self.rows(pending=False), ["Card", "Invoice", "Transfer"])
		with patch.object(confirmation, "can_hold_orders", return_value=True):
			self.assertEqual(self.rows(pending=True), ["Card", "Invoice", "Transfer"])
		# a site that has not migrated cannot mark the order: the method waits for the confirmation
		with patch.object(confirmation, "can_hold_orders", return_value=False):
			self.assertEqual(self.rows(pending=True), ["Card", "Transfer"])


class TestPlacingAnOrderOnAccount(FrappeTestCase):
	"""place_offline_order holds an order paid on account by an unconfirmed account, and only that."""

	def place(self, settlement, pending):
		cart = frappe._dict(items=[frappe._dict(item_code="MUG", qty=1)])
		row = frappe._dict(settlement=settlement, payment_terms_template=None)
		with (
			patch("webshop.webshop.shopping_cart.cart._get_cart_quotation", return_value=cart),
			patch("webshop.webshop.shopping_cart.cart.place_order", return_value="SO-PLACED"),
			patch.object(offline_payment, "row_for_gateway", return_value=row),
			patch.object(offline_payment, "customer_group_of", return_value=None),
			patch.object(offline_payment, "raise_payment_request", return_value="PR-PLACED"),
			patch.object(offline_payment.frappe.db, "set_value"),
			patch.object(confirmation, "pending", return_value=pending),
			patch.object(confirmation, "hold_until_confirmed") as hold,
		):
			answer = offline_payment.place_offline_order("Invoice")
		self.assertEqual(answer["sales_order"], "SO-PLACED")
		return hold

	def test_only_an_unconfirmed_account_paying_on_account_waits(self):
		self.place("On account", pending=True).assert_called_once_with("SO-PLACED")
		self.place("On account", pending=False).assert_not_called()
		# a transfer is held until the money is in, whoever pays: not this module's hold
		self.place("Transfer before shipping", pending=True).assert_not_called()


USER = "_wstest_d9_held@example.com"
CUSTOMER = f"{PREFIX} D9 Held Customer"


class TestOrdersWaitForTheConfirmation(FrappeTestCase):
	"""Real orders: held, released by the confirmation, and a hold that is not ours left alone."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		from webshop.patches.add_email_confirmation_hold_field import execute

		execute()
		cls.item = make_test_item(f"{PREFIX} D9 Held Item", is_stock_item=0).name
		portal_customer(USER, CUSTOMER)
		# class fixtures survive FrappeTestCase's rollback only committed (CLAUDE.md, Testing Strategy)
		frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		cls.purge()
		# class fixtures survive FrappeTestCase's rollback only committed (CLAUDE.md, Testing Strategy)
		frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit
		super().tearDownClass()

	@classmethod
	def purge(cls):
		"""What an interrupted run committed: each test rolls its own orders back."""
		# what an order's submit enrolled links it, and would refuse its cancellation
		for doctype in ("Purchase Follow-up Entry", "Abandoned Cart Reminder"):
			frappe.db.delete(doctype, {"customer": CUSTOMER})
		for name in frappe.get_all("Sales Order", filters={"customer": CUSTOMER}, pluck="name"):
			order = frappe.get_doc("Sales Order", name)
			if order.docstatus == 1:
				order.flags.ignore_links = True
				order.cancel()
			frappe.delete_doc("Sales Order", name, force=True, ignore_permissions=True)

	def setUp(self):
		frappe.set_user("Administrator")
		# FrappeTestCase rolls back at the end of the class only: an order held by one test would
		# still be held in the next
		self.addCleanup(frappe.db.rollback)
		# release_held_orders refuses to switch the user inside a web request; a test is not one
		session = patch.object(frappe.local, "session_obj", None, create=True)
		session.start()
		self.addCleanup(session.stop)

	def order(self):
		order = frappe.get_doc(
			{
				"doctype": "Sales Order",
				"customer": CUSTOMER,
				"order_type": "Sales",
				"transaction_date": nowdate(),
				"delivery_date": add_days(nowdate(), 7),
				"selling_price_list": selling_price_list(),
				"items": [{"item_code": self.item, "qty": 1, "rate": 25, "delivery_date": add_days(nowdate(), 7)}],
			}
		)
		order.flags.ignore_permissions = True
		order.insert()
		order.submit()
		# placed by the customer's own account, as the shop's checkout places it
		frappe.db.set_value("Sales Order", order.name, "owner", USER, update_modified=False)
		return order.name, order.status

	def state(self, name):
		return frappe.db.get_value("Sales Order", name, ["status", confirmation.HELD_FIELD])

	def info_comments(self, name):
		return frappe.get_all(
			"Comment",
			filters={"reference_doctype": "Sales Order", "reference_name": name, "comment_type": "Info"},
			pluck="content",
		)

	def test_held_until_the_confirmation_then_released(self):
		name, placed = self.order()
		confirmation.hold_until_confirmed(name)
		self.assertEqual(self.state(name), ("On Hold", 1))
		self.assertEqual(confirmation.held_orders(USER), [name])
		confirmation.release_held_orders(USER)
		self.assertEqual(self.state(name), (placed, 0), "the status the order had, computed again")
		self.assertTrue(any(USER in text for text in self.info_comments(name)), "the timeline says why")
		self.assertEqual(frappe.session.user, "Administrator")

	def test_a_hold_the_merchant_takes_back_is_never_lifted_by_the_confirmation(self):
		name, _placed = self.order()
		confirmation.hold_until_confirmed(name)
		# the merchant resumes it by hand, then holds it again for a reason of their own
		frappe.get_doc("Sales Order", name).update_status("Draft")
		self.assertEqual(self.state(name)[1], 0, "resumed: no longer ours to release")
		frappe.get_doc("Sales Order", name).update_status("On Hold")
		self.assertEqual(confirmation.held_orders(USER), [])
		confirmation.release_held_orders(USER)
		self.assertEqual(self.state(name), ("On Hold", 0))

	def test_an_order_the_credit_limit_refuses_stays_held_and_says_why(self):
		name, _placed = self.order()
		confirmation.hold_until_confirmed(name)
		with (
			patch(
				"erpnext.selling.doctype.sales_order.sales_order.SalesOrder.check_credit_limit",
				side_effect=frappe.ValidationError("Credit limit crossed"),
			),
			patch.object(confirmation.frappe, "log_error") as log_error,
		):
			confirmation.release_held_orders(USER)
		self.assertEqual(self.state(name), ("On Hold", 1), "nothing half done: still held, still ours")
		log_error.assert_called_once()
		self.assertTrue(any("Credit limit crossed" in text for text in self.info_comments(name)))
