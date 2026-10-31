# //// Neoffice — added file (no upstream equivalent).
"""A finished catalogue shown through a link, and sent by e-mail (reseller catalogue, lot 5d).

Same two resellers and the same shop as the other catalogue tests; the catalogues are made by the job, run inline, as CSV
files (no Chromium needed). What is proved is what would hurt: a file that carries what the reseller pays has no link, a
link serves the file of its catalogue and nothing else, every dead link is the same 404, one reseller cannot reach
another's catalogue, and an e-mail goes to one address, only when asked, with the link and not the file.
"""

import json
import uuid
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.catalogue import access, catalogue_api, jobs, share
from webshop.webshop.catalogue import api as brand_api
from webshop.webshop.catalogue import fixtures as shop
from webshop.webshop.doctype.reseller_catalogue.reseller_catalogue import READY
from webshop.webshop.utils import throttle

DOCTYPE = "Reseller Catalogue"
PICKED = {"item_groups": [shop.PARENT_GROUP, shop.OTHER_GROUP]}


class TestShare(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		shop.make()

	@classmethod
	def tearDownClass(cls):
		shop.purge()
		super().tearDownClass()

	def setUp(self):
		self.run_id = uuid.uuid4().hex[:10]
		self.settings = frappe.get_doc("Webshop Settings")
		self.settings.enable_reseller_catalogue = 1
		self.settings.reseller_catalogue_groups = [frappe._dict(allowed_customer_group=shop.RESELLER_GROUP)]
		self.settings.catalogue_credit_text = ""
		patcher = mock.patch.object(access, "shop_settings", return_value=self.settings)
		patcher.start()
		self.addCleanup(patcher.stop)
		self.addCleanup(frappe.set_user, "Administrator")
		for name in frappe.get_all(DOCTYPE, filters={"customer": ["in", [shop.CUSTOMER, shop.OTHER_CUSTOMER]]}, pluck="name"):
			frappe.delete_doc(DOCTYPE, name, force=True, ignore_permissions=True)
		for customer in (shop.CUSTOMER, shop.OTHER_CUSTOMER):
			throttle.reset("catalogue-ask", customer)
			throttle.reset("catalogue-mail", customer)
		for user in (shop.USER, shop.OTHER_USER):
			frappe.set_user(user)
			answer = brand_api.save_my_brand(
				{
					"brand_name": f"Brand of {user}",
					"contact_email": f"orders@{user.split('@')[0]}.example.ch",
					"default_markup_percent": 30,
					"price_rounding": "none",
					"price_display": "Excluding VAT",
					"markup_rules": [],
				}
			)
			self.assertTrue(answer["ok"], answer)
		frappe.db.commit()
		frappe.set_user(shop.USER)

	def made(self, prices="customers", fmt="csv", title="Spring 2027", customer=shop.CUSTOMER):
		"""A catalogue asked for and made by the job, run inline. Returns its name."""
		args = {"title": title, "picked": json.dumps(PICKED), "options": json.dumps({"prices": prices}), "format": fmt}
		with mock.patch("frappe.enqueue"), mock.patch.object(catalogue_api, "chromium_available", return_value=False):
			answer = catalogue_api.create_catalogue(**args)
		self.assertTrue(answer["ok"], answer)
		name = frappe.get_all(DOCTYPE, filters={"customer": customer}, fields=["name"], order_by="creation desc", limit=1)[0].name
		frappe.db.commit()
		jobs.generate(name)
		self.assertEqual(frappe.db.get_value(DOCTYPE, name, "status"), READY, frappe.db.get_value(DOCTYPE, name, "error"))
		return name

	def read(self, token):
		return share.ShareRenderer(path=f"shared-catalogue/{token}").render()

	def token(self, name):
		return frappe.get_doc(DOCTYPE, name).get_password("share_token")

	def shared(self, **kwargs):
		name = self.made(**kwargs)
		answer = catalogue_api.share_catalogue(name=name)
		self.assertTrue(answer["ok"], answer)
		return name, self.token(name)

	# --- what may be shared ------------------------------------------------------------------

	def test_a_shopify_file_follows_the_same_rule_and_is_served_as_a_csv(self):
		_name, token = self.shared(fmt="shopify")
		self.assertEqual(self.read(token).mimetype, "text/csv")
		answer = catalogue_api.share_catalogue(name=self.made(prices="both", fmt="shopify"))
		self.assertFalse(answer["ok"], "a Shopify file with their cost is theirs alone")

	def test_a_file_with_the_selling_prices_or_none_may_have_a_link_and_the_price_they_pay_never_may(self):
		for prices, allowed in (("customers", True), ("none", True), ("tariff", False), ("both", False)):
			with self.subTest(prices=prices):
				name = self.made(prices=prices)
				answer = catalogue_api.share_catalogue(name=name)
				self.assertEqual(answer["ok"], allowed, answer)
				if not allowed:
					self.assertIsNone(frappe.db.get_value(DOCTYPE, name, "share_hash"))
					self.assertTrue(answer["message"])
				row = next(row for row in catalogue_api.get_catalogues()["catalogues"] if row["name"] == name)
				self.assertEqual(row["sharable"], allowed)

	def test_a_catalogue_that_is_not_finished_has_no_link(self):
		name = self.made()
		frappe.db.set_value(DOCTYPE, name, "status", "Running")
		answer = catalogue_api.share_catalogue(name=name)
		self.assertFalse(answer["ok"])
		self.assertIsNone(frappe.db.get_value(DOCTYPE, name, "share_hash"))

	def test_the_days_come_from_a_closed_list_and_never_go_past_the_life_of_the_catalogue(self):
		name = self.made()
		for refused in ("0", "-1", "8", "365", "abc", "7; drop"):
			with self.subTest(days=refused):
				answer = catalogue_api.share_catalogue(name=name, days=refused)
				self.assertEqual((answer["ok"], answer["field"]), (False, "days"))
		for days in (7, 14, 30):
			catalogue_api.share_catalogue(name=name, days=str(days))
			expires = frappe.db.get_value(DOCTYPE, name, "share_expires_on")
			self.assertLessEqual(expires, frappe.db.get_value(DOCTYPE, name, "expires_on"))
			self.assertLessEqual((expires - frappe.utils.getdate()).days, days)

	# --- the link ----------------------------------------------------------------------------

	def test_the_link_serves_the_file_of_its_catalogue_and_says_it_is_not_for_search_engines(self):
		name, token = self.shared()
		response = self.read(token)
		self.assertEqual(response.status_code, 200)
		self.assertTrue(response.get_data(as_text=True).startswith("code,"), "the CSV the job made")
		self.assertEqual(response.headers["X-Robots-Tag"], "noindex, nofollow")
		self.assertIn("attachment", response.headers["Content-Disposition"])
		self.assertIn("private", response.headers["Cache-Control"])
		self.assertEqual(response.headers["Content-Type"], "text/csv")

	def test_only_the_hash_of_the_secret_is_in_the_table_and_the_page_is_given_the_link(self):
		name, token = self.shared()
		self.assertEqual(frappe.db.get_value(DOCTYPE, name, "share_hash"), share.digest(token))
		self.assertNotEqual(frappe.db.get_value(DOCTYPE, name, "share_hash"), token)
		row = next(row for row in catalogue_api.get_catalogues()["catalogues"] if row["name"] == name)
		self.assertTrue(row["share"]["url"].endswith(f"/shared-catalogue/{token}"))
		self.assertNotIn("share_hash", row)

	def test_a_new_link_stops_the_old_one_and_stopping_stops_them_all(self):
		name, first = self.shared()
		catalogue_api.share_catalogue(name=name)
		second = self.token(name)
		self.assertNotEqual(first, second)
		self.assertEqual(self.read(first).status_code, 404)
		self.assertEqual(self.read(second).status_code, 200)
		answer = catalogue_api.unshare_catalogue(name=name)
		self.assertTrue(answer["ok"])
		self.assertEqual(self.read(second).status_code, 404)
		self.assertIsNone(frappe.db.get_value(DOCTYPE, name, "share_hash"))
		self.assertIsNone(frappe.get_doc(DOCTYPE, name).get_password("share_token", raise_exception=False), "the secret itself goes too")

	def test_every_dead_link_is_the_same_404(self):
		name, token = self.shared()
		frappe.db.set_value(DOCTYPE, name, "share_expires_on", frappe.utils.add_days(frappe.utils.nowdate(), -1))
		bodies = set()
		for label, value in {"unknown": "A" * 32, "expired": token}.items():
			with self.subTest(link=label):
				response = self.read(value)
				self.assertEqual(response.status_code, 404)
				bodies.add(response.get_data(as_text=True))
		self.assertEqual(len(bodies), 1, "the same answer whatever is wrong")
		for value in ("abc", "../etc/passwd", "A" * 65, "a b" * 10, ""):
			with self.subTest(path=value):
				self.assertFalse(share.ShareRenderer(path=f"shared-catalogue/{value}").can_render(), "not even an address of this page")

	def test_a_link_stops_when_its_catalogue_is_deleted_or_the_shop_no_longer_offers_the_catalogue_to_its_owner(self):
		name, token = self.shared()
		self.settings.reseller_catalogue_groups = []
		self.assertEqual(self.read(token).status_code, 404)
		self.settings.reseller_catalogue_groups = [frappe._dict(allowed_customer_group=shop.RESELLER_GROUP)]
		self.assertEqual(self.read(token).status_code, 200)
		frappe.delete_doc(DOCTYPE, name, force=True, ignore_permissions=True)
		self.assertEqual(self.read(token).status_code, 404)

	def test_a_link_to_a_catalogue_that_later_turns_out_to_carry_the_price_they_pay_is_refused_too(self):
		"""The serving rule is the sharing rule: a catalogue whose options were changed after it was shared is not served."""
		name, token = self.shared()
		frappe.db.set_value(DOCTYPE, name, "options", json.dumps({"prices": "tariff"}))
		self.assertEqual(self.read(token).status_code, 404)

	def test_a_connection_that_asks_for_many_wrong_links_is_slowed(self):
		request = mock.Mock()
		with mock.patch.object(frappe.local, "request", request, create=True), mock.patch.object(share.throttle, "peer_ip", return_value="203.0.113.7"):
			throttle.reset("share-miss", "203.0.113.7")
			throttle.reset("share-read", "203.0.113.7")
			statuses = {self.read("A" * 32).status_code for _ in range(share.MISSES_PER_TEN_MINUTES + 3)}
		self.assertEqual(statuses, {404, 429})

	def test_opening_the_link_is_written_to_the_hour(self):
		name, token = self.shared()
		self.read(token)
		first = frappe.db.get_value(DOCTYPE, name, "share_opened_on")
		self.assertTrue(first)
		self.read(token)
		self.assertEqual(frappe.db.get_value(DOCTYPE, name, "share_opened_on"), first)

	# --- whose it is -------------------------------------------------------------------------

	def test_a_reseller_cannot_share_stop_or_send_another_resellers_catalogue(self):
		name, token = self.shared()
		frappe.set_user(shop.OTHER_USER)
		for call in (
			lambda: catalogue_api.share_catalogue(name=name),
			lambda: catalogue_api.unshare_catalogue(name=name),
			lambda: catalogue_api.send_catalogue(name=name, to=self.address()),
		):
			with self.assertRaises(frappe.DoesNotExistError):
				call()
		self.assertEqual(self.read(token).status_code, 200, "and the owner's link still works")

	def test_the_endpoints_are_for_the_allowed_customers_alone(self):
		name = self.made()
		for user in (shop.OUT_USER, "Guest"):
			frappe.set_user(user)
			for call in (
				lambda: catalogue_api.share_catalogue(name=name),
				lambda: catalogue_api.unshare_catalogue(name=name),
				lambda: catalogue_api.send_catalogue(name=name, to=self.address()),
			):
				with self.subTest(user=user), self.assertRaises(frappe.PermissionError):
					call()

	# --- the e-mail --------------------------------------------------------------------------

	def address(self, label="client"):
		"""An address of this test's own: the day's counters are in Redis and outlive a run."""
		return f"{label}-{self.run_id}@example.ch"

	def send(self, name, to=..., message="Here is our spring catalogue.", **kwargs):
		to = self.address() if to is ... else to
		with mock.patch("frappe.sendmail") as sendmail:
			answer = catalogue_api.send_catalogue(name=name, to=to, message=message, **kwargs)
		return answer, sendmail

	def test_an_email_goes_to_one_address_with_the_link_and_not_the_file(self):
		name = self.made()
		answer, sendmail = self.send(name)
		self.assertTrue(answer["ok"], answer)
		sendmail.assert_called_once()
		mail = sendmail.call_args.kwargs
		self.assertEqual(mail["recipients"], [self.address()])
		self.assertNotIn("attachments", mail)
		self.assertIn(f"/shared-catalogue/{self.token(name)}", mail["message"], "a link is made when there is none")
		self.assertIn("Here is our spring catalogue.", mail["message"])
		self.assertEqual(mail["reply_to"], "orders@wstest-cat-a.example.ch", "a reply goes to the reseller")
		self.assertIn("Brand of wstest-cat-a@example.com", mail["subject"])
		self.assertEqual((mail["reference_doctype"], mail["reference_name"]), (DOCTYPE, name))

	def test_the_link_is_the_one_that_already_exists_and_a_stopped_or_expired_one_is_made_again(self):
		name, token = self.shared()
		answer, sendmail = self.send(name)
		self.assertIn(token, sendmail.call_args.kwargs["message"])
		self.assertEqual(self.token(name), token)
		catalogue_api.unshare_catalogue(name=name)
		answer, sendmail = self.send(name, to=self.address("other"))
		self.assertTrue(answer["ok"], answer)
		self.assertIn(self.token(name), sendmail.call_args.kwargs["message"])

	def test_what_the_reseller_wrote_is_text_in_the_mail_and_never_markup(self):
		name = self.made()
		answer, sendmail = self.send(name, message='<script>alert(1)</script>\n<a href="http://evil.example">click</a>')
		self.assertTrue(answer["ok"], answer)
		body = sendmail.call_args.kwargs["message"]
		self.assertNotIn("<script>", body)
		self.assertNotIn('<a href="http://evil.example">', body)
		self.assertIn("&lt;script&gt;", body)
		self.assertIn("<br>", body, "a line break stays one")

	def test_only_one_address_is_accepted_and_nothing_else_rides_in_it(self):
		name = self.made()
		for refused in (
			"a@example.ch, b@example.ch",
			"a@example.ch;b@example.ch",
			"a@example.ch\nBcc: b@example.ch",
			"Name <a@example.ch>",
			"a b@example.ch",
			"not an address",
			"",
			None,
		):
			with self.subTest(address=repr(refused)):
				answer, sendmail = self.send(name, to=refused)
				self.assertEqual((answer["ok"], answer["field"]), (False, "to"))
				sendmail.assert_not_called()

	def test_the_message_is_bounded_and_control_characters_are_dropped(self):
		name = self.made()
		answer, sendmail = self.send(name, message="x" * (share.MESSAGE_MAX + 1))
		self.assertEqual((answer["ok"], answer["field"]), (False, "message"))
		sendmail.assert_not_called()
		answer, sendmail = self.send(name, message="Hello\x00 \x1bthere")
		self.assertTrue(answer["ok"], answer)
		self.assertIn("Hello there", sendmail.call_args.kwargs["message"])

	def test_a_file_with_the_price_they_pay_is_not_sent_either(self):
		name = self.made(prices="tariff")
		answer, sendmail = self.send(name)
		self.assertFalse(answer["ok"])
		sendmail.assert_not_called()
		self.assertIsNone(frappe.db.get_value(DOCTYPE, name, "share_hash"), "and no link was made on the way")

	def test_the_day_s_mails_are_bounded_per_reseller_and_per_address(self):
		name = self.made()
		same = self.address("same")
		for number in range(share.MAILS_PER_RECIPIENT):
			answer, _sent = self.send(name, to=same)
			self.assertTrue(answer["ok"], (number, answer))
		answer, sendmail = self.send(name, to=same)
		self.assertFalse(answer["ok"])
		sendmail.assert_not_called()
		throttle.reset("catalogue-mail", shop.CUSTOMER)
		for number in range(share.MAILS_PER_DAY):
			answer, _sent = self.send(name, to=self.address(f"client{number}"))
			self.assertTrue(answer["ok"], (number, answer))
		answer, sendmail = self.send(name, to=self.address("one-more"))
		self.assertFalse(answer["ok"])
		sendmail.assert_not_called()

	def test_a_mail_server_that_cannot_send_is_told_to_the_reseller_without_a_modal(self):
		name = self.made()
		# a fresh site's fixtures (users getting their role) leave notices of their own in the log: only the call is looked at
		frappe.local.message_log = []
		with mock.patch("frappe.sendmail", side_effect=frappe.OutgoingEmailError("no server")):
			answer = catalogue_api.send_catalogue(name=name, to=self.address())
		self.assertFalse(answer["ok"])
		self.assertTrue(answer["message"])
		self.assertEqual(list(frappe.local.message_log or []), [], "the mail server's error does not reach the browser")


if __name__ == "__main__":
	import unittest

	unittest.main()
