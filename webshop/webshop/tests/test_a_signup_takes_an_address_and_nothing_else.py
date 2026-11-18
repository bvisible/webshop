# //// Neoffice — added file (no upstream equivalent)
# Copyright (c) 2026, Neoffice and contributors
# For license information, please see license.txt

"""The shop's signup takes an address and nothing else (maintenance#2860).

On 18.11 a vulnerability scanner posted to create_account addresses followed by SQL and script payloads. Frappe's
validate_email_address finds an address inside a string, so the signup let them through and 17 enabled Website Users
were created, each name a payload. The signup now answers invalid_email for anything that is not exactly an address,
creates no user and writes no Error Log row; a plain address still makes its account.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.auth import api

PROBES = (
	"zz-probe@email.tst%c0%a7%c0%a2%2527%2522\\'\"",
	"zz-probe@email.tst' and 2*3*8=6*8 and 'a9is'='a9is",
	"zz-probe@email.tstfa6oi2lf') or 701=(select 701 from pg_sleep(15))--",
	"zz-probe@email.tst&n948154=v924635",
)


class TestASignupTakesAnAddressAndNothingElse(FrappeTestCase):
	def sign_up(self, email):
		frappe.set_user("Guest")
		try:
			frappe.local.form_dict = frappe._dict(
				email=email, first_name="Zz", last_name="Probe", password="Zz-Probe-2860-x9!long"
			)
			return api.create_account()
		finally:
			frappe.set_user("Administrator")

	def test_a_payload_after_an_address_is_an_invalid_address(self):
		errors_before = frappe.db.count("Error Log")
		for probe in PROBES:
			with self.subTest(probe=probe):
				answer = self.sign_up(probe)
				self.assertEqual(answer.get("reason_code"), "invalid_email", answer)
				self.assertFalse(frappe.db.exists("User", probe.lower()))
		self.assertEqual(frappe.db.count("Error Log"), errors_before, "a bad address is not an error of the shop")
