# //// Neoffice — added file (no upstream equivalent).
"""A reseller's access to the partner API: the request, staff's decision, the key, and what a call must show.

Two resellers of one allowed group, a customer of a group the shop did not allow, and staff. What is proved is
what would hurt: the secret of a key is kept nowhere (a row holds an id and a hash), a refused, revoked,
replaced or suspended key is the same 401 with a reason only in its code, one reseller never sees or decides
another's access, and a decision is staff's alone.
"""

import json
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.catalogue import access as catalogue_access
from webshop.webshop.catalogue import fixtures as shop
from webshop.webshop.partner_api import access, portal_api
from webshop.webshop.partner_api.access import ApiError
from webshop.webshop.utils import throttle

DOCTYPE = access.DOCTYPE
CUSTOMERS = (shop.CUSTOMER, shop.OTHER_CUSTOMER)


def wipe():
	for customer in CUSTOMERS:
		if frappe.db.exists(DOCTYPE, customer):
			frappe.delete_doc(DOCTYPE, customer, force=True, ignore_permissions=True)
		for name in frappe.get_all("ToDo", filters={"reference_type": DOCTYPE, "reference_name": customer}, pluck="name"):
			frappe.delete_doc("ToDo", name, force=True, ignore_permissions=True)
		for counter in ("partner-request", "partner-key", "partner-api"):
			throttle.reset(counter, customer)
	throttle.reset("partner-miss", "unknown")
	frappe.db.commit()


class TestPartnerAccess(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		shop.make()

	@classmethod
	def tearDownClass(cls):
		wipe()
		shop.purge()
		super().tearDownClass()

	def setUp(self):
		self.settings = frappe.get_doc("Webshop Settings")
		self.settings.enable_reseller_catalogue = 1
		self.settings.reseller_catalogue_groups = [frappe._dict(allowed_customer_group=shop.RESELLER_GROUP)]
		patcher = mock.patch.object(catalogue_access, "shop_settings", return_value=self.settings)
		patcher.start()
		self.addCleanup(patcher.stop)
		self.addCleanup(frappe.set_user, "Administrator")
		wipe()
		frappe.set_user("Administrator")

	def ask(self, customer=shop.CUSTOMER, user=shop.USER, **fields):
		args = {"use_case": "Keep my shop's prices up to date", "wants_orders": True, "expected_volume": "a few hundred a day"}
		args.update(fields)
		return access.request(customer, user, args["use_case"], args["wants_orders"], args["expected_volume"])

	def approved(self, customer=shop.CUSTOMER, user=shop.USER, **decision):
		self.assertIsNone(self.ask(customer, user))
		frappe.set_user("Administrator")
		access.approve(customer, **{"scope_orders": 1, "calls_per_minute": 60, **decision})
		return access.get(customer)

	def keyed(self, customer=shop.CUSTOMER, user=shop.USER, **decision):
		self.approved(customer, user, **decision)
		key, refusal = access.new_key(customer)
		self.assertIsNone(refusal)
		return key

	# --- asking --------------------------------------------------------------------------------------

	def test_a_request_is_written_as_asked_and_staff_find_it_in_their_to_dos(self):
		self.assertIsNone(self.ask())
		doc = access.get(shop.CUSTOMER)
		self.assertEqual((doc.status, doc.requested_by, doc.wants_orders), ("Requested", shop.USER, 1))
		self.assertEqual(doc.use_case, "Keep my shop's prices up to date")
		self.assertEqual(
			frappe.db.count("ToDo", {"reference_type": DOCTYPE, "reference_name": shop.CUSTOMER, "status": "Open"}), 1
		)

	def test_a_request_that_is_not_one_is_refused_beside_its_field(self):
		for fields, field in (
			({"use_case": "   "}, "use_case"),
			({"use_case": "x" * 501}, "use_case"),
			({"use_case": "a <b> c"}, "use_case"),
			({"expected_volume": "y" * 101}, "expected_volume"),
			({"expected_volume": "<script>"}, "use_case"),
		):
			with self.subTest(fields=list(fields)):
				answer = self.ask(**fields)
				self.assertEqual((answer["ok"], answer["field"]), (False, field))
		self.assertIsNone(access.get(shop.CUSTOMER))

	def test_one_access_a_customer_and_a_request_waits_for_its_answer(self):
		self.assertIsNone(self.ask())
		again = self.ask()
		self.assertFalse(again["ok"])
		self.assertEqual(frappe.db.count(DOCTYPE, {"customer": shop.CUSTOMER}), 1)

	def test_a_refused_reseller_may_ask_again_and_the_day_has_a_limit(self):
		self.assertIsNone(self.ask())
		access.refuse(shop.CUSTOMER, note="Not now")
		self.assertEqual(access.get(shop.CUSTOMER).decision_note, "Not now")
		self.assertIsNone(self.ask(use_case="More about what I need"))
		doc = access.get(shop.CUSTOMER)
		self.assertEqual((doc.status, doc.decision_note), ("Requested", ""), "a new request starts without the old note")
		with mock.patch.object(access, "REQUESTS_PER_DAY", 1):
			access.refuse(shop.CUSTOMER)
			self.assertFalse(self.ask()["ok"])

	# --- the decision ----------------------------------------------------------------------------------

	def test_staff_approve_with_the_scopes_they_choose_and_the_to_do_closes(self):
		doc = self.approved(scope_orders=1, submit_orders=1, calls_per_minute=120)
		self.assertEqual((doc.status, doc.scope_products, doc.scope_orders, doc.submit_orders, doc.calls_per_minute), ("Active", 1, 1, 1, 120))
		self.assertEqual(doc.decided_by, "Administrator")
		self.assertEqual(frappe.db.count("ToDo", {"reference_type": DOCTYPE, "reference_name": shop.CUSTOMER, "status": "Open"}), 0)

	def test_a_submit_scope_without_the_orders_scope_is_not_kept(self):
		doc = self.approved(scope_orders=0, submit_orders=1)
		self.assertEqual((doc.scope_orders, doc.submit_orders), (0, 0))

	def test_the_allowance_is_bounded(self):
		self.assertIsNone(self.ask())
		for calls in (0, -1, access.MAX_CALLS_PER_MINUTE + 1):
			with self.subTest(calls=calls), self.assertRaises(frappe.ValidationError):
				access.approve(shop.CUSTOMER, calls_per_minute=calls)

	def test_a_decision_is_staffs_alone(self):
		self.assertIsNone(self.ask())
		for user in (shop.USER, shop.OTHER_USER, shop.OUT_USER, "Guest"):
			frappe.set_user(user)
			for call in (
				lambda: access.approve(shop.CUSTOMER),
				lambda: access.refuse(shop.CUSTOMER),
				lambda: access.suspend(shop.CUSTOMER),
				lambda: access.resume(shop.CUSTOMER),
			):
				with self.subTest(user=user), self.assertRaises(frappe.PermissionError):
					call()
		frappe.set_user("Administrator")
		self.assertEqual(access.get(shop.CUSTOMER).status, "Requested")

	def test_the_states_follow_one_another_and_nothing_jumps(self):
		with self.assertRaises(frappe.ValidationError):
			access.approve(shop.CUSTOMER)  # nobody asked
		self.assertIsNone(self.ask())
		with self.assertRaises(frappe.ValidationError):
			access.suspend(shop.CUSTOMER)  # not active
		with self.assertRaises(frappe.ValidationError):
			access.resume(shop.CUSTOMER)
		access.approve(shop.CUSTOMER)
		with self.assertRaises(frappe.ValidationError):
			access.refuse(shop.CUSTOMER)  # active: suspend it
		access.suspend(shop.CUSTOMER, note="Overload")
		self.assertEqual(access.get(shop.CUSTOMER).status, "Suspended")
		access.resume(shop.CUSTOMER)
		self.assertEqual(access.get(shop.CUSTOMER).status, "Active")

	# --- the key ---------------------------------------------------------------------------------------

	def test_a_key_is_made_for_an_active_access_only(self):
		self.assertIsNone(self.ask())
		key, refusal = access.new_key(shop.CUSTOMER)
		self.assertIsNone(key)
		self.assertFalse(refusal["ok"])
		key, refusal = access.new_key(shop.OTHER_CUSTOMER)
		self.assertIsNone(key, "a reseller who never asked has none")

	def test_the_secret_is_kept_nowhere_a_row_holds_an_id_and_a_hash(self):
		key = self.keyed()
		self.assertRegex(key, access.KEY_PATTERN)
		key_id, secret = access.KEY_PATTERN.match(key).groups()
		row = frappe.db.sql("select * from `tabPartner API Access` where name = %s", shop.CUSTOMER, as_dict=True)[0]
		values = [str(value) for value in row.values()]
		self.assertIn(key_id, values)
		self.assertEqual(row.secret_hash, access.digest(secret))
		self.assertFalse(any(secret in value for value in values), "the secret is in no column")
		self.assertNotIn(secret, json.dumps(access.describe(shop.CUSTOMER)))
		self.assertNotIn("secret_hash", access.describe(shop.CUSTOMER))

	def test_a_new_key_replaces_the_old_one_at_once(self):
		old = self.keyed()
		new, _refusal = access.new_key(shop.CUSTOMER)
		self.assertNotEqual(old, new)
		self.assertEqual(access.authenticate(new).customer, shop.CUSTOMER)
		with self.assertRaises(ApiError) as caught:
			access.authenticate(old)
		self.assertEqual(caught.exception.status, 401)

	def test_a_revoked_key_opens_nothing_and_the_access_stays_active(self):
		key = self.keyed()
		access.revoke_key(shop.CUSTOMER)
		with self.assertRaises(ApiError) as caught:
			access.authenticate(key)
		self.assertEqual(caught.exception.status, 401)
		self.assertEqual(access.get(shop.CUSTOMER).status, "Active")
		self.assertIsNone(access.new_key(shop.CUSTOMER)[1], "a new one can be made")

	# --- what a call must show ---------------------------------------------------------------------------

	def refusal(self, header, peer=None):
		with self.assertRaises(ApiError) as caught:
			access.authenticate(header, peer)
		return caught.exception

	def test_a_key_opens_its_own_customer_and_what_staff_allowed(self):
		row = access.authenticate(self.keyed(scope_orders=1, calls_per_minute=90))
		self.assertEqual((row.customer, row.scope_products, row.scope_orders, row.calls_per_minute), (shop.CUSTOMER, 1, 1, 90))
		self.assertEqual(row.requested_by, shop.USER)

	def test_every_way_a_key_can_be_wrong_is_the_same_401_with_the_reason_in_its_code_only(self):
		key = self.keyed()
		key_id, secret = access.KEY_PATTERN.match(key).groups()
		wrong = (
			(None, "invalid_key"),
			("", "invalid_key"),
			("not a key", "invalid_key"),
			(f"wsk_{key_id}.{'x' * 40}", "invalid_key"),
			(f"wsk_{'0' * 12}.{secret}", "invalid_key"),
			(key.replace("wsk_", "wsx_"), "invalid_key"),
			(key + " extra", "invalid_key"),
		)
		sentences = set()
		for header, code in wrong:
			error = self.refusal(header)
			with self.subTest(header=str(header)[:20]):
				self.assertEqual((error.status, error.code), (401, code))
			sentences.add(error.message)
		access.suspend(shop.CUSTOMER, note="Overload")
		suspended = self.refusal(key)
		self.assertEqual((suspended.status, suspended.code), (401, "access_suspended"))
		sentences.add(suspended.message)
		self.assertEqual(len(sentences), 1, "the sentence tells nothing the code does not")

	def test_suspending_cuts_the_key_and_resuming_gives_it_back_and_the_portal_is_untouched(self):
		key = self.keyed()
		access.suspend(shop.CUSTOMER)
		self.assertEqual(self.refusal(key).code, "access_suspended")
		self.assertTrue(catalogue_access.offered_to(shop.CUSTOMER), "the customer keeps the rest of their account")
		self.assertTrue(frappe.db.exists("User", shop.USER))
		access.resume(shop.CUSTOMER)
		self.assertEqual(access.authenticate(key).customer, shop.CUSTOMER)

	def test_a_customer_the_shop_no_longer_offers_the_catalogue_is_cut_too(self):
		key = self.keyed()
		self.settings.reseller_catalogue_groups = []
		error = self.refusal(key)
		self.assertEqual((error.status, error.code), (401, "access_closed"))

	def test_a_connection_that_sends_many_wrong_keys_is_slowed(self):
		with mock.patch.object(access.throttle, "hit", return_value=31):
			error = self.refusal("wsk_nothing", peer="203.0.113.9")
		self.assertEqual((error.status, error.code), (429, "too_many_attempts"))
		self.assertEqual(error.headers["Retry-After"], "600")

	def test_the_allowance_of_calls_a_minute_is_kept(self):
		row = access.authenticate(self.keyed(calls_per_minute=2))
		access.check_rate(row)
		access.check_rate(row)
		with self.assertRaises(ApiError) as caught:
			access.check_rate(row)
		self.assertEqual((caught.exception.status, caught.exception.code), (429, "rate_limited"))
		self.assertEqual(caught.exception.headers["Retry-After"], "60")

	def test_the_last_use_is_written_to_the_hour(self):
		key = self.keyed()
		row = access.authenticate(key)
		self.assertFalse(frappe.db.get_value(DOCTYPE, shop.CUSTOMER, "last_used_on"))
		access.record_use(row)
		self.assertTrue(frappe.db.get_value(DOCTYPE, shop.CUSTOMER, "last_used_on"))
		earlier = frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-5)
		frappe.db.set_value(DOCTYPE, shop.CUSTOMER, "last_used_on", earlier, update_modified=False)
		access.record_use(access.authenticate(key))
		self.assertEqual(frappe.db.get_value(DOCTYPE, shop.CUSTOMER, "last_used_on"), earlier, "five minutes ago is recent enough")

	# --- the reseller's page -----------------------------------------------------------------------------

	def test_a_visitor_an_account_the_shop_did_not_allow_and_staff_are_refused_by_every_endpoint(self):
		calls = (
			lambda: portal_api.get_integration(),
			lambda: portal_api.request_access(use_case="x"),
			lambda: portal_api.new_key(),
			lambda: portal_api.revoke_key(),
		)
		for user in ("Guest", shop.OUT_USER, "Administrator"):
			frappe.set_user(user)
			for call in calls:
				with self.subTest(user=user), self.assertRaises(frappe.PermissionError):
					call()

	def test_a_reseller_asks_reads_the_answer_makes_a_key_and_sees_it_once(self):
		frappe.set_user(shop.USER)
		self.assertIsNone(portal_api.get_integration()["access"])
		answer = portal_api.request_access(use_case="Sync my prices", wants_orders=1, expected_volume="hundreds")
		self.assertEqual(answer["access"]["status"], "Requested")
		self.assertFalse(portal_api.new_key()["ok"], "no key before the shop says yes")
		frappe.set_user("Administrator")
		access.approve(shop.CUSTOMER, scope_orders=1)
		frappe.set_user(shop.USER)
		made = portal_api.new_key()
		self.assertTrue(made["key"].startswith("wsk_"))
		self.assertEqual(made["access"]["key_id"], made["key"].split(".")[0])
		later = portal_api.get_integration()
		self.assertNotIn("key", later)
		self.assertNotIn(made["key"].split(".")[1], json.dumps(later))
		self.assertTrue(later["base_url"].endswith("/partner/v1"))
		portal_api.revoke_key()
		self.assertEqual(portal_api.get_integration()["access"]["key_id"], "")

	def test_one_reseller_never_sees_or_changes_the_access_of_another(self):
		self.assertIsNone(self.ask(shop.CUSTOMER, shop.USER))
		frappe.set_user(shop.OTHER_USER)
		self.assertIsNone(portal_api.get_integration()["access"])
		self.assertFalse(portal_api.new_key()["ok"])
		portal_api.revoke_key()
		frappe.set_user("Administrator")
		self.assertEqual(access.get(shop.CUSTOMER).status, "Requested")

	def test_a_reseller_cannot_read_an_access_through_the_generic_api(self):
		self.assertIsNone(self.ask())
		frappe.set_user(shop.USER)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_list(DOCTYPE)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(DOCTYPE, shop.CUSTOMER).check_permission("read")
