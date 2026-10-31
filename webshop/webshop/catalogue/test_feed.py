# //// Neoffice — added file (no upstream equivalent).
"""The reseller's product feed, end to end: who may make one, what it carries, who may read it and who cannot.

Built on the small shop of `fixtures.py`: two resellers of one group (A: brand A's products, B: brand B's), the
same price list, a markup of 30 %. The refresh job is run inline, as the queue would run it; the address is
read through the page renderer, as a script would. What is proved is what would hurt: **what the reseller pays
is nowhere in the feed**, an address gives its own feed and nobody else's, a closed or replaced address answers
404, and a refresh that fails leaves the last good file in service.
"""

import csv
import io
import json
import os
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, add_to_date, now_datetime

from webshop.webshop.catalogue import access, catalogue_api, feed, feed_api, jobs, rows
from webshop.webshop.catalogue import api as brand_api
from webshop.webshop.catalogue import fixtures as shop
from webshop.webshop.catalogue.refusals import catalogue_message, feed_message
from webshop.webshop.catalogue.test_rows import COSTS, SHOP_PRICES
from webshop.webshop.utils import throttle

DOCTYPE = feed.DOCTYPE
PICKED_A = {"brands": [shop.BRAND_A], "item_groups": [shop.PARENT_GROUP]}
PICKED_B = {"items": [shop.THIRD]}
CUSTOMERS = (shop.CUSTOMER, shop.OTHER_CUSTOMER)


class TestTheFeed(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		shop.make()

	@classmethod
	def tearDownClass(cls):
		cls.clean()
		shop.purge()
		super().tearDownClass()

	@staticmethod
	def clean():
		for customer in CUSTOMERS:
			if frappe.db.exists(DOCTYPE, customer):
				frappe.delete_doc(DOCTYPE, customer, force=True, ignore_permissions=True)
			feed.remove_files(customer)
			throttle.reset("feed-refresh", customer)
		frappe.db.commit()

	def setUp(self):
		self.settings = frappe.get_doc("Webshop Settings")
		self.settings.enable_reseller_catalogue = 1
		self.settings.reseller_catalogue_groups = [frappe._dict(allowed_customer_group=shop.RESELLER_GROUP)]
		self.settings.catalogue_credit_text = ""
		patcher = mock.patch.object(access, "shop_settings", return_value=self.settings)
		patcher.start()
		self.addCleanup(patcher.stop)
		self.addCleanup(frappe.set_user, "Administrator")
		self.clean()
		for user in (shop.USER, shop.OTHER_USER):
			frappe.set_user(user)
			answer = brand_api.save_my_brand(
				{"brand_name": f"Brand of {user}", "default_markup_percent": 30, "price_rounding": "none", "price_display": "Excluding VAT"}
			)
			self.assertTrue(answer["ok"], answer)
		frappe.db.commit()
		frappe.set_user("Administrator")
		self.payloads = {customer: brand_api._payload(customer) for customer in CUSTOMERS}

	def tearDown(self):
		self.clean()

	def make(self, customer=shop.CUSTOMER, picked=None, options=None):
		"""feed.save with the job's enqueueing caught; returns what save answers (None when it worked)."""
		with mock.patch("frappe.enqueue") as enqueue:
			answer = feed.save(customer, self.payloads[customer], picked or PICKED_A, options or {})
		self.enqueue = enqueue
		return answer

	def made(self, customer=shop.CUSTOMER, picked=None, options=None):
		"""A feed saved and refreshed."""
		self.assertIsNone(self.make(customer, picked, options))
		frappe.db.commit()
		feed.refresh(customer)
		return feed.get_feed(customer)

	def token(self, customer=shop.CUSTOMER):
		return feed.get_feed(customer).get_password("token")

	def read(self, token, kind="csv", extra=None):
		renderer = feed.FeedRenderer(path=f"feeds/reseller/{token}/products.{kind}")
		with mock.patch.object(feed.FeedRenderer, "header", staticmethod(lambda name: (extra or {}).get(name))):
			return renderer.render()

	def records(self, token):
		response = self.read(token)
		self.assertEqual(response.status_code, 200)
		return list(csv.DictReader(io.StringIO(response.get_data(as_text=True), newline="")))

	# --- making it --------------------------------------------------------------------------------

	def test_saving_a_feed_queues_a_refresh_and_keeps_the_token_only_hashed_and_encrypted(self):
		self.assertIsNone(self.make())
		doc = feed.get_feed(shop.CUSTOMER)
		self.assertEqual(doc.status, "Queued")
		self.assertEqual(self.enqueue.call_args.args[0], "webshop.webshop.catalogue.feed.refresh")
		token = self.token()
		self.assertGreaterEqual(len(token), 32)
		self.assertEqual(doc.token_hash, feed.digest(token))
		row = frappe.db.sql("select * from `tabReseller Feed` where name = %s", shop.CUSTOMER, as_dict=True)[0]
		self.assertNotIn(token, [str(value) for value in row.values()], "the secret is in no column of the table")
		stored = frappe.db.get_value("__Auth", {"doctype": DOCTYPE, "name": shop.CUSTOMER, "fieldname": "token"}, "password")
		self.assertTrue(stored)
		self.assertNotEqual(stored, token, "and it is encrypted where it is kept")

	def test_saving_again_changes_what_it_is_made_from_and_keeps_the_address(self):
		self.made()
		token = self.token()
		throttle.reset("feed-refresh", shop.CUSTOMER)
		self.assertIsNone(self.make(picked=PICKED_B, options={"markup_percent": 50}))
		self.assertEqual(self.token(), token)
		self.assertEqual(json.loads(feed.get_feed(shop.CUSTOMER).selection), {"item_groups": [], "brands": [], "items": [shop.THIRD]})

	def test_a_refresh_writes_both_files_with_the_resellers_price(self):
		doc = self.made()
		self.assertEqual(doc.status, "Ready")
		self.assertEqual(doc.item_count, len(self.records(self.token())))
		first = {record["code"]: record for record in self.records(self.token())}[shop.FIRST]
		self.assertEqual(first["price"], "104.00", "80 on their list, plus 30 %")
		self.assertTrue(first["currency"])
		document = json.loads(self.read(self.token(), "json").get_data())
		self.assertEqual(document["count"], doc.item_count)
		self.assertEqual({product["code"]: product for product in document["products"]}[shop.FIRST]["price"], 104.0)

	def test_what_the_reseller_pays_and_what_the_shop_charges_are_nowhere_in_the_feed(self):
		self.made(picked={"item_groups": [shop.PARENT_GROUP, shop.OTHER_GROUP], "items": [shop.MODEL]})
		forbidden = COSTS | SHOP_PRICES
		csv_figures = set()
		for record in self.records(self.token()):
			for value in record.values():
				try:
					csv_figures.add(float(value))
				except ValueError:
					pass
		self.assertIn(104.0, csv_figures, "the test reads the real prices")
		self.assertFalse(forbidden & csv_figures, "CSV")
		document = json.loads(self.read(self.token(), "json").get_data())
		json_figures = {
			float(value)
			for product in document["products"]
			for value in product.values()
			if isinstance(value, (int, float)) and not isinstance(value, bool)
		}
		self.assertIn(104.0, json_figures)
		self.assertFalse(forbidden & json_figures, "JSON")
		for kind in ("csv", "json"):
			self.assertNotIn("purchase_price", self.read(self.token(), kind).get_data(as_text=True))

	def test_only_their_customers_price_or_none_is_ever_a_choice(self):
		for mode in ("tariff", "both", "cost"):
			with self.subTest(mode=mode):
				answer = self.make(options={"prices": mode})
				self.assertEqual((answer["ok"], answer["field"]), (False, "prices"))
		self.assertFalse(frappe.db.exists(DOCTYPE, shop.CUSTOMER))

	def test_a_feed_without_prices_has_no_price_column(self):
		self.made(options={"prices": "none"})
		record = self.records(self.token())[0]
		self.assertFalse({"price", "purchase_price", "currency"} & set(record))

	def test_a_feed_with_prices_needs_a_saved_brand_and_one_without_does_not(self):
		frappe.delete_doc("Reseller Catalogue Profile", shop.OTHER_CUSTOMER, force=True, ignore_permissions=True)
		payload = brand_api._payload(shop.OTHER_CUSTOMER)
		self.payloads[shop.OTHER_CUSTOMER] = payload
		self.assertFalse(payload["saved"])
		self.assertIsNone(self.make(shop.OTHER_CUSTOMER, PICKED_B, {"prices": "none"}))
		frappe.db.set_value(DOCTYPE, shop.OTHER_CUSTOMER, "status", "Ready")
		answer = self.make(shop.OTHER_CUSTOMER, PICKED_B, {"prices": "customers"})
		self.assertEqual((answer["ok"], answer["message"]), (False, feed_message("no_brand")), "refused for the brand, not for being busy")

	def test_a_selection_that_holds_nothing_or_too_much_is_refused(self):
		self.assertEqual(self.make(picked={"items": ["no such product"]})["field"], "selection")
		with mock.patch.object(rows, "MAX_ROWS", 2):
			answer = self.make(picked={"items": [shop.MODEL, shop.FIRST]})
		self.assertEqual(answer["field"], "selection")
		self.assertFalse(frappe.db.exists(DOCTYPE, shop.CUSTOMER))

	def test_saves_and_refreshes_are_limited_to_a_few_a_day(self):
		with mock.patch.object(feed, "REFRESHES_PER_DAY", 2):
			self.assertIsNone(self.make())
			frappe.db.set_value(DOCTYPE, shop.CUSTOMER, "status", "Ready")
			self.assertIsNone(self.make())
			frappe.db.set_value(DOCTYPE, shop.CUSTOMER, "status", "Ready")
			answer = self.make()
		self.assertEqual((answer["ok"], answer["message"]), (False, feed_message("refresh_limit", 2)))

	def test_a_second_refresh_waits_for_the_first(self):
		self.assertIsNone(self.make())
		answer = self.make()
		self.assertEqual((answer["ok"], answer["message"]), (False, feed_message("busy")), "the feed is still Queued")

	# --- reading it ---------------------------------------------------------------------------------

	def test_the_address_serves_the_file_as_a_file_nobody_indexes(self):
		self.made()
		response = self.read(self.token())
		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.mimetype, "text/csv")
		self.assertIn("utf-8", response.headers["Content-Type"])
		self.assertIn("noindex", response.headers["X-Robots-Tag"])
		self.assertTrue(response.headers["Cache-Control"].startswith("private"))
		self.assertTrue(response.headers["ETag"].startswith('"'))
		self.assertEqual(self.read(self.token(), "json").mimetype, "application/json")

	def test_an_unchanged_file_answers_304_to_the_etag_it_gave(self):
		self.made()
		etag = self.read(self.token()).headers["ETag"]
		response = self.read(self.token(), extra={"If-None-Match": etag})
		self.assertEqual(response.status_code, 304)
		self.assertEqual(response.get_data(), b"")
		self.assertEqual(self.read(self.token(), extra={"If-None-Match": '"other"'}).status_code, 200)

	def test_a_wrong_or_malformed_address_is_a_404_or_not_ours(self):
		self.made()
		self.assertEqual(self.read("A" * 32).status_code, 404)
		self.assertTrue(feed.FeedRenderer(path="feeds/reseller/short/products.csv").can_render() is False)
		self.assertFalse(feed.FeedRenderer(path="feeds/reseller/../../etc/passwd").can_render())
		self.assertFalse(feed.FeedRenderer(path=f"feeds/reseller/{self.token()}/products.exe").can_render())
		self.assertTrue(feed.FeedRenderer(path=f"feeds/reseller/{self.token()}/products.csv").can_render())

	def test_an_address_gives_its_own_resellers_feed_and_nobody_elses(self):
		self.made(shop.CUSTOMER, PICKED_A)
		self.made(shop.OTHER_CUSTOMER, PICKED_B)
		mine = {record["code"] for record in self.records(self.token(shop.CUSTOMER))}
		theirs = {record["code"] for record in self.records(self.token(shop.OTHER_CUSTOMER))}
		self.assertIn(shop.FIRST, mine)
		self.assertNotIn(shop.THIRD, mine)
		self.assertEqual(theirs, {shop.THIRD})
		self.assertNotEqual(self.token(shop.CUSTOMER), self.token(shop.OTHER_CUSTOMER))

	def test_a_reseller_the_shop_no_longer_allows_is_a_404_and_gets_the_file_back_when_allowed_again(self):
		self.made()
		token = self.token()
		self.settings.reseller_catalogue_groups = []
		self.assertEqual(self.read(token).status_code, 404)
		self.settings.reseller_catalogue_groups = [frappe._dict(allowed_customer_group=shop.RESELLER_GROUP)]
		self.assertEqual(self.read(token).status_code, 200)

	def test_a_new_address_closes_the_old_one_at_once(self):
		self.made()
		old = self.token()
		self.assertIsNone(feed.rotate(shop.CUSTOMER))
		frappe.db.commit()
		self.assertNotEqual(self.token(), old)
		self.assertEqual(self.read(old).status_code, 404)
		self.assertEqual(self.read(self.token()).status_code, 200, "the file did not have to be made again")

	def test_stopping_the_feed_closes_the_address_and_removes_the_files(self):
		self.made()
		token = self.token()
		paths = [feed.feed_path(shop.CUSTOMER, kind) for kind in feed.KINDS]
		self.assertTrue(all(os.path.exists(path) for path in paths))
		feed.delete(shop.CUSTOMER)
		self.assertEqual(self.read(token).status_code, 404)
		self.assertFalse(any(os.path.exists(path) for path in paths))

	def test_the_last_read_is_written_to_the_hour_not_at_every_read(self):
		self.made()
		self.assertFalse(frappe.db.get_value(DOCTYPE, shop.CUSTOMER, "last_fetched"))
		self.read(self.token())
		first = frappe.db.get_value(DOCTYPE, shop.CUSTOMER, "last_fetched")
		self.assertTrue(first)
		earlier = add_to_date(now_datetime(), minutes=-5)
		frappe.db.set_value(DOCTYPE, shop.CUSTOMER, "last_fetched", earlier, update_modified=False)
		self.read(self.token())
		self.assertEqual(frappe.db.get_value(DOCTYPE, shop.CUSTOMER, "last_fetched"), earlier)

	# --- refreshing ---------------------------------------------------------------------------------

	def test_a_refresh_that_fails_leaves_the_last_good_file_in_service(self):
		self.made()
		before = self.read(self.token()).get_data()
		frappe.db.set_value(DOCTYPE, shop.CUSTOMER, "status", "Queued")
		with mock.patch.object(rows, "build_rows", side_effect=RuntimeError("boom")), mock.patch("frappe.log_error"):
			feed.refresh(shop.CUSTOMER)
		doc = feed.get_feed(shop.CUSTOMER)
		self.assertEqual(doc.status, "Failed")
		self.assertTrue(doc.error)
		self.assertNotIn("boom", doc.error, "the reseller reads a sentence, not a traceback")
		self.assertEqual(self.read(self.token()).get_data(), before)

	def test_a_refresh_that_the_selection_cannot_serve_says_why(self):
		self.assertIsNone(self.make())
		frappe.db.commit()
		with mock.patch.object(rows, "MAX_ROWS", 1), mock.patch.dict(jobs.NUMBERS, {"too_many_rows": 1}):
			feed.refresh(shop.CUSTOMER)
		doc = feed.get_feed(shop.CUSTOMER)
		self.assertEqual(doc.status, "Failed")
		self.assertEqual(doc.error, catalogue_message("too_many_rows", 1))

	def test_only_a_waiting_feed_is_refreshed(self):
		self.made()
		generated = feed.get_feed(shop.CUSTOMER).generated_on
		with mock.patch.object(rows, "build_rows", side_effect=AssertionError("must not run")):
			feed.refresh(shop.CUSTOMER)
		self.assertEqual(feed.get_feed(shop.CUSTOMER).generated_on, generated)

	def test_two_resellers_with_the_same_bytes_each_keep_their_own_file(self):
		self.made(shop.CUSTOMER, PICKED_A)
		self.made(shop.OTHER_CUSTOMER, PICKED_A)
		self.assertEqual(self.read(self.token(shop.CUSTOMER)).get_data(), self.read(self.token(shop.OTHER_CUSTOMER)).get_data())
		throttle.reset("feed-refresh", shop.CUSTOMER)
		self.made(shop.CUSTOMER, PICKED_B)
		self.assertEqual(self.read(self.token(shop.OTHER_CUSTOMER)).status_code, 200)
		self.assertIn(shop.FIRST, self.read(self.token(shop.OTHER_CUSTOMER)).get_data(as_text=True))
		feed.delete(shop.CUSTOMER)
		self.assertIn(shop.FIRST, self.read(self.token(shop.OTHER_CUSTOMER)).get_data(as_text=True))

	# --- the night ----------------------------------------------------------------------------------

	def test_the_night_refreshes_the_feeds_that_are_read_or_new_and_leaves_the_forgotten_ones(self):
		self.made(shop.CUSTOMER, PICKED_A)
		self.made(shop.OTHER_CUSTOMER, PICKED_B)
		old = add_days(now_datetime(), -30)
		for customer in CUSTOMERS:
			frappe.db.set_value(DOCTYPE, customer, "creation", old, update_modified=False)
		frappe.db.set_value(DOCTYPE, shop.CUSTOMER, "last_fetched", add_days(now_datetime(), -2), update_modified=False)
		with mock.patch("frappe.enqueue") as enqueue:
			feed.refresh_all()
		queued = [call.kwargs["customer"] for call in enqueue.call_args_list]
		self.assertEqual(queued, [shop.CUSTOMER], "read two days ago: refreshed; made 30 days ago and never read: left")
		self.assertEqual(feed.get_feed(shop.CUSTOMER).status, "Queued")
		self.assertEqual(feed.get_feed(shop.OTHER_CUSTOMER).status, "Ready")

	def test_the_night_does_not_queue_a_feed_twice_nor_one_the_shop_no_longer_allows(self):
		self.assertIsNone(self.make(shop.CUSTOMER, PICKED_A))
		self.made(shop.OTHER_CUSTOMER, PICKED_B)
		self.settings.reseller_catalogue_groups = []
		with mock.patch("frappe.enqueue") as enqueue:
			feed.refresh_all()
		self.assertFalse(enqueue.called)
		self.settings.reseller_catalogue_groups = [frappe._dict(allowed_customer_group=shop.RESELLER_GROUP)]
		with mock.patch("frappe.enqueue") as enqueue:
			feed.refresh_all()
		self.assertEqual([call.kwargs["customer"] for call in enqueue.call_args_list], [shop.OTHER_CUSTOMER], "the first is still Queued")

	def test_the_night_closes_a_refresh_that_lost_its_worker(self):
		self.assertIsNone(self.make())
		frappe.db.set_value(DOCTYPE, shop.CUSTOMER, "modified", add_to_date(now_datetime(), hours=-3), update_modified=False)
		self.assertFalse(feed.is_refreshing(shop.CUSTOMER))
		with mock.patch("frappe.enqueue"):
			feed.refresh_all()
		self.assertEqual(feed.get_feed(shop.CUSTOMER).status, "Queued", "closed, then queued again: it was just made, so it is new")

	# --- the endpoints ------------------------------------------------------------------------------

	def test_a_visitor_an_account_the_shop_did_not_allow_and_staff_are_refused_by_every_endpoint(self):
		calls = (
			lambda: feed_api.save_feed(picked=json.dumps(PICKED_A)),
			lambda: feed_api.refresh_feed(),
			lambda: feed_api.new_feed_address(),
			lambda: feed_api.delete_feed(),
		)
		for user in ("Guest", shop.OUT_USER, "Administrator"):
			frappe.set_user(user)
			for call in calls:
				with self.subTest(user=user):
					with self.assertRaises(frappe.PermissionError):
						call()

	def test_a_reseller_cannot_read_the_feed_through_the_generic_api(self):
		self.made()
		frappe.set_user(shop.USER)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_list(DOCTYPE)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(DOCTYPE, shop.CUSTOMER).check_permission("read")

	def test_the_page_state_shows_a_reseller_their_own_feed_with_its_addresses_and_nobody_elses(self):
		self.made(shop.CUSTOMER, PICKED_A)
		frappe.set_user(shop.USER)
		mine = catalogue_api.get_catalogues()["feed"]
		self.assertEqual(mine["status"], "Ready")
		self.assertTrue(mine["addresses"]["csv"].endswith(f"/feeds/reseller/{self.token()}/products.csv"))
		self.assertTrue(mine["addresses"]["json"].endswith("/products.json"))
		self.assertEqual((mine["groups"], mine["brands"], mine["products"]), (1, 1, 0))
		frappe.set_user(shop.OTHER_USER)
		self.assertIsNone(catalogue_api.get_catalogues()["feed"])

	def test_one_reseller_cannot_stop_refresh_or_replace_the_feed_of_another(self):
		self.made(shop.CUSTOMER, PICKED_A)
		token = self.token()
		frappe.set_user(shop.OTHER_USER)
		answer = feed_api.new_feed_address()
		self.assertFalse(answer["ok"], "they have no feed to change")
		answer = feed_api.refresh_feed()
		self.assertFalse(answer["ok"])
		feed_api.delete_feed()
		frappe.set_user("Administrator")
		self.assertEqual(self.token(), token)
		self.assertEqual(self.read(token).status_code, 200)

	def test_the_endpoints_make_refresh_replace_and_stop_the_feed_of_the_caller(self):
		frappe.set_user(shop.USER)
		with mock.patch("frappe.enqueue"):
			answer = feed_api.save_feed(picked=json.dumps(PICKED_A), options=json.dumps({"prices": "customers"}))
		self.assertTrue(answer["ok"], answer)
		self.assertEqual(answer["feed"]["status"], "Queued")
		frappe.set_user("Administrator")
		feed.refresh(shop.CUSTOMER)
		frappe.set_user(shop.USER)
		old = catalogue_api.get_catalogues()["feed"]["addresses"]["csv"]
		self.assertTrue(feed_api.new_feed_address()["ok"])
		self.assertNotEqual(catalogue_api.get_catalogues()["feed"]["addresses"]["csv"], old)
		self.assertIsNone(feed_api.delete_feed()["feed"])

	def test_a_request_that_is_not_json_is_a_refusal_not_a_server_error(self):
		frappe.set_user(shop.USER)
		for picked in ("not json", json.dumps([1]), json.dumps({"items": "FIRST"})):
			with self.subTest(picked=picked):
				answer = feed_api.save_feed(picked=picked)
				self.assertEqual((answer["ok"], answer["field"]), (False, "selection"))
		self.assertFalse(frappe.db.exists(DOCTYPE, shop.CUSTOMER))
		with mock.patch("frappe.enqueue"):
			answer = feed_api.save_feed(picked=json.dumps(PICKED_A), options="not json")
		self.assertTrue(answer["ok"], "options that are not JSON are the defaults")
		self.assertEqual(answer["feed"]["markup_percent"], 30.0)
