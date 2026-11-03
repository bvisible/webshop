# //// Neoffice — added file (no upstream equivalent). Tests of the shop's half of signing in with a code
# //// (auth/code_sign_in.py, neoffice-maintenance#2192). The engine is the frappe fork's `frappe.passwordless`:
# //// on stock Frappe (the CI) it is absent, the tests that need it are skipped, and the ones that say the
# //// shop then behaves as it always did still run. A skip is "not run", never "passed".
import os
import re
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.auth import api, code_sign_in

try:
	from frappe import passwordless
except ImportError:
	passwordless = None

EMAIL = "e2e.code-signup@yopmail.com"
KNOWN = "e2e.code-known@yopmail.com"
STAFF = "e2e.code-staff@yopmail.com"


def _drop(*emails):
	for email in emails:
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=True, ignore_permissions=True)


def _website_user(email):
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": "Known",
			"user_type": "Website User",
			"send_welcome_email": 0,
			"roles": [{"role": "Customer", "doctype": "Has Role"}],
		}
	)
	user.insert(ignore_permissions=True)
	return user


class TestTheShopWithoutTheEngine(FrappeTestCase):
	"""What holds on every site, the fork's engine or not."""

	def test_the_dialog_is_told_what_the_site_can_do_and_never_more(self):
		self.assertEqual(api.get_auth_settings()["passwordless"], code_sign_in.available())
		with patch.object(code_sign_in, "available", return_value=False):
			self.assertFalse(api.get_auth_settings()["passwordless"])

	def test_without_the_engine_the_shop_keeps_its_password(self):
		with patch.dict("sys.modules", {"frappe.passwordless": None}):
			self.assertFalse(code_sign_in.available())
			answer = code_sign_in.complete_sign_up("proof", "A", "B")
		self.assertEqual(answer["reason_code"], "unavailable")

	def test_check_email_still_answers_as_before_where_no_code_is_sent(self):
		_drop(KNOWN)
		self.addCleanup(_drop, KNOWN)
		_website_user(KNOWN)
		with patch.object(code_sign_in, "available", return_value=False):
			self.assertTrue(api.check_email(KNOWN)["exists"])
			self.assertFalse(api.check_email("e2e.code-nobody@yopmail.com")["exists"])

	def test_check_email_tells_a_known_address_from_an_unknown_one_to_nobody_where_a_code_is_sent(self):
		_drop(KNOWN)
		self.addCleanup(_drop, KNOWN)
		_website_user(KNOWN)
		with patch.object(code_sign_in, "available", return_value=True):
			known, unknown = api.check_email(KNOWN), api.check_email("e2e.code-nobody@yopmail.com")
		self.assertEqual(known, unknown)
		self.assertFalse(known["exists"])
		self.assertIsNone(known["first_name"])

	def test_the_shop_closes_sign_up_for_the_engine_on_a_business_site(self):
		self.assertIn(
			"webshop.webshop.auth.code_sign_in.signup_closed", frappe.get_hooks("passwordless_signup_closed")
		)
		with patch("webshop.webshop.multi_site.site_is_business_only", return_value=True):
			self.assertTrue(code_sign_in.signup_closed())
		with patch("webshop.webshop.multi_site.site_is_business_only", return_value=False):
			self.assertFalse(code_sign_in.signup_closed())

	def test_the_mail_speaks_for_the_shop_being_served(self):
		self.assertIn("webshop.webshop.auth.code_sign_in.brand", frappe.get_hooks("passwordless_brand"))
		with patch("webshop.webshop.seo.site.shop_name", return_value="La Fromagerie"):
			self.assertEqual(code_sign_in.brand(), "La Fromagerie")

	def test_a_field_losing_the_focus_never_mails_a_code(self):
		"""A code is mailed on Continue or Enter. The dialog used to look the address up on every blur."""
		path = os.path.join(os.path.dirname(__file__), "..", "..", "public", "js", "auth_dialog.js")
		source = open(path).read()
		blur = re.search(r"emailInput\.addEventListener\('blur'.*?\n    \}\);", source, re.S).group(0)
		self.assertIn("if (passwordless) return;", blur)
		# and the dialog asks the engine through its own fetch, never frappe.call (mute on a 429)
		self.assertIn("'frappe.passwordless.request_code'", source)
		self.assertNotRegex(source, r"frappe\.call\(\{\s*method:\s*'frappe\.passwordless")


class TestCompleteSignUp(FrappeTestCase):
	def setUp(self):
		if passwordless is None:
			self.skipTest("needs the frappe fork's passwordless engine")
		_drop(EMAIL, KNOWN, STAFF)
		self.addCleanup(_drop, EMAIL, KNOWN, STAFF)
		frappe.set_user("Guest")
		self.addCleanup(frappe.set_user, "Administrator")
		self.signed_in = []

		def fake_sign_in(user, redirect_to=None):
			self.signed_in.append((user, redirect_to))
			return {"ok": True, "status": "signed_in", "user": user, "redirect_to": redirect_to or "/me"}

		for p in (
			patch.object(api, "signups_disabled", return_value=False),
			patch.object(code_sign_in, "signup_closed", return_value=False),
			patch.object(api, "_sign_ups_so_far", return_value=0),
			patch.object(api, "_count_sign_up"),
			patch("frappe.passwordless.sign_in", side_effect=fake_sign_in),
		):
			p.start()
			self.addCleanup(p.stop)

	def proof(self, email=EMAIL):
		return passwordless._mint_proof(email)

	def test_a_proven_mailbox_and_a_name_open_an_account_that_is_signed_in(self):
		answer = code_sign_in.complete_sign_up(self.proof(), "Ada", "Lovelace", "/checkout")

		self.assertEqual((answer["message"], answer["signed_in"], answer["redirect_to"]), ("success", True, "/checkout"))
		user = frappe.get_doc("User", EMAIL)
		self.assertEqual((user.user_type, user.first_name, user.last_name), ("Website User", "Ada", "Lovelace"))
		roles = [r.role for r in user.roles]
		self.assertIn("Customer", roles)
		# other apps of the instance add their own portal roles (a course student, a suite user); never a desk one
		self.assertNotIn("System Manager", roles)
		self.assertTrue(user.enabled)
		# the code proved the address: nothing is left to confirm by a welcome email
		self.assertFalse(frappe.db.get_value("User", EMAIL, "email_confirmation_pending"))
		self.assertEqual(self.signed_in, [(EMAIL, "/checkout")])

	def test_a_proof_works_once(self):
		proof = self.proof()
		self.assertEqual(code_sign_in.complete_sign_up(proof, "Ada", "Lovelace")["message"], "success")
		again = code_sign_in.complete_sign_up(proof, "Ada", "Lovelace")
		self.assertEqual(again["reason_code"], "invalid_proof")
		self.assertEqual(len(self.signed_in), 1)

	def test_nothing_without_a_proof(self):
		for proof in (None, "", "forged", "x" * 200):
			answer = code_sign_in.complete_sign_up(proof, "Ada", "Lovelace")
			self.assertEqual(answer["reason_code"], "invalid_proof", repr(proof))
		self.assertFalse(frappe.db.exists("User", EMAIL))
		self.assertEqual(self.signed_in, [])

	def test_a_missing_name_is_refused_and_the_proof_is_kept_for_the_next_try(self):
		proof = self.proof()
		for first, last in (("", "Lovelace"), ("Ada", ""), ("<b></b>", "  "), (None, None)):
			self.assertEqual(code_sign_in.complete_sign_up(proof, first, last)["reason_code"], "missing_fields")
		self.assertEqual(code_sign_in.complete_sign_up(proof, "Ada", "Lovelace")["message"], "success")

	def test_a_name_is_text_and_short(self):
		code_sign_in.complete_sign_up(self.proof(), "<script>alert(1)</script>Ada", "L" * 300)
		user = frappe.get_doc("User", EMAIL)
		self.assertNotIn("<", user.first_name)
		self.assertLessEqual(len(user.last_name), code_sign_in.NAME_LENGTH)

	def test_a_closed_site_opens_nothing_and_keeps_the_proof(self):
		proof = self.proof()
		for closed in ("signups_disabled", "signup_closed"):
			module = api if closed == "signups_disabled" else code_sign_in
			with patch.object(module, closed, return_value=True):
				self.assertEqual(
					code_sign_in.complete_sign_up(proof, "Ada", "Lovelace")["reason_code"], "signup_disabled"
				)
		self.assertFalse(frappe.db.exists("User", EMAIL))
		self.assertEqual(code_sign_in.complete_sign_up(proof, "Ada", "Lovelace")["message"], "success")

	def test_the_hourly_ceiling_answers_429_and_keeps_the_proof(self):
		proof = self.proof()
		with patch.object(api, "_sign_ups_so_far", return_value=api.SIGN_UPS_PER_HOUR):
			answer = code_sign_in.complete_sign_up(proof, "Ada", "Lovelace")
		self.assertEqual(answer["reason_code"], "too_many_signups")
		self.assertEqual(frappe.local.response.http_status_code, 429)
		frappe.local.response.http_status_code = 200
		self.assertEqual(code_sign_in.complete_sign_up(proof, "Ada", "Lovelace")["message"], "success")

	def test_an_account_that_exists_is_signed_in_not_created_twice(self):
		_website_user(KNOWN)
		answer = code_sign_in.complete_sign_up(self.proof(KNOWN), "Other", "Name")
		self.assertEqual(answer["message"], "success")
		self.assertEqual(frappe.db.get_value("User", KNOWN, "first_name"), "Known")  # untouched
		self.assertEqual(self.signed_in[0][0], KNOWN)

	def test_a_staff_address_is_never_taken_over_by_the_shop(self):
		frappe.set_user("Administrator")  # only an administrator grants a desk role
		staff = frappe.get_doc({"doctype": "User", "email": STAFF, "first_name": "Staff", "send_welcome_email": 0})
		staff.insert(ignore_permissions=True)
		staff.add_roles("System Manager")
		frappe.set_user("Guest")
		self.assertEqual(frappe.db.get_value("User", STAFF, "user_type"), "System User")

		answer = code_sign_in.complete_sign_up(self.proof(STAFF), "Mallory", "X")
		self.assertEqual(answer["reason_code"], "account_exists_system")
		self.assertEqual(frappe.db.get_value("User", STAFF, "first_name"), "Staff")
		self.assertEqual(self.signed_in, [])

	def test_a_sign_in_the_site_refuses_is_reported_without_the_engines_words(self):
		with patch("frappe.passwordless.sign_in", return_value={"ok": False, "reason": "not_allowed"}):
			answer = code_sign_in.complete_sign_up(self.proof(), "Ada", "Lovelace")
		self.assertEqual((answer["message"], answer["reason_code"]), ("error", "not_allowed"))
