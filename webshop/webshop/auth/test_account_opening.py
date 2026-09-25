# //// Neoffice — added file (no upstream equivalent): an account opened at once in the shop, its
# //// address confirmed afterwards (auth/confirmation.py). neoffice-maintenance#691, decision D-9,
# //// 2026-09-25.
"""An account opened at once, and the three things that keep that safe:
- only an address the shop does not know is opened;
- the first way back into the account, which can only go through its mailbox, confirms the
  address and closes the sessions whoever opened it kept;
- payment on account waits for that confirmation.
"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.auth import api, confirmation
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
		with patch("frappe.sessions.clear_sessions") as clear:
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
				confirmation.on_login(self.login_manager())
			finally:
				frappe.flags.webshop_opening_account = False
			# staff signing in as the customer (impersonation, bench browse)
			frappe.set_user("Administrator")
			confirmation.on_login(self.login_manager())
		self.assertTrue(confirmation.pending(EMAIL))
		clear.assert_not_called()

	def test_an_account_nothing_waits_on_is_left_alone(self):
		frappe.set_user("Guest")
		with patch("frappe.sessions.clear_sessions") as clear:
			confirmation.on_login(self.login_manager())
		clear.assert_not_called()


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

	def test_an_unconfirmed_account_is_not_offered_payment_on_account(self):
		self.assertEqual(self.rows(pending=True), ["Card", "Transfer"])
		self.assertEqual(self.rows(pending=False), ["Card", "Invoice", "Transfer"])
