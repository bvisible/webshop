# //// Neoffice — added file (no upstream equivalent).
"""The reseller's catalogues, end to end: who may ask, what is refused, the job, the download, the night's cleaning.

Three identities (anonymous, an account the shop did not allow, staff) and two resellers: the second must
never reach the first's catalogues. The job is run inline (`jobs.generate`), as the queue would run it; the
tests that need the PDF skip on a bench without Chromium and say so.
"""

import json
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, add_to_date, now_datetime, nowdate

from webshop.webshop.catalogue import access, book, catalogue_api, jobs, selection
from webshop.webshop.catalogue import api as brand_api
from webshop.webshop.catalogue import fixtures as shop
from webshop.webshop.catalogue.pdf import chromium_available
from webshop.webshop.catalogue.refusals import catalogue_message
from webshop.webshop.doctype.reseller_catalogue.reseller_catalogue import FAILED, QUEUED, READY, RUNNING

DOCTYPE = "Reseller Catalogue"
PICKED = {"item_groups": [shop.PARENT_GROUP]}


class TestCatalogueApi(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		shop.make()

	@classmethod
	def tearDownClass(cls):
		shop.purge()
		super().tearDownClass()

	def setUp(self):
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
		for user in (shop.USER, shop.OTHER_USER):
			frappe.set_user(user)
			answer = brand_api.save_my_brand(
				{"brand_name": f"Brand of {user}", "primary_colour": "#0b6e4f", "default_markup_percent": 30, "price_rounding": "none"}
			)
			self.assertTrue(answer["ok"], answer)
		frappe.db.commit()
		frappe.set_user(shop.USER)

	def ask(self, **kwargs):
		"""create_catalogue as the signed-in reseller, with the job's enqueueing caught."""
		args = {"title": "Spring 2027", "picked": json.dumps(PICKED), "options": json.dumps({"layout": "grid"})}
		args.update(kwargs)
		with mock.patch("frappe.enqueue") as enqueue:
			answer = catalogue_api.create_catalogue(**args)
		self.enqueue = enqueue
		return answer

	def newest(self, customer=shop.CUSTOMER):
		return frappe.get_all(DOCTYPE, filters={"customer": customer}, fields=["name"], order_by="creation desc", limit=1)[0].name

	# --- who may ask -------------------------------------------------------------------------------

	def test_a_visitor_an_account_the_shop_did_not_allow_and_staff_are_refused_by_every_endpoint(self):
		calls = (
			lambda: catalogue_api.get_catalogues(),
			lambda: catalogue_api.get_choices(),
			lambda: catalogue_api.search_products(text="Cat"),
			lambda: catalogue_api.count_products(picked=json.dumps(PICKED)),
			lambda: catalogue_api.create_catalogue(title="x", picked=json.dumps(PICKED)),
			lambda: catalogue_api.remake_catalogue(name="x"),
			lambda: catalogue_api.delete_catalogue(name="x"),
			lambda: catalogue_api.download_catalogue(name="x"),
		)
		for user in ("Guest", shop.OUT_USER, "Administrator"):
			frappe.set_user(user)
			for call in calls:
				with self.subTest(user=user):
					with self.assertRaises(frappe.PermissionError):
						call()

	def test_a_reseller_cannot_read_the_catalogues_through_the_generic_api(self):
		self.ask()
		frappe.set_user(shop.USER)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_list(DOCTYPE)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(DOCTYPE, self.newest()).check_permission("read")

	def test_the_switch_off_closes_the_door_to_a_reseller_too(self):
		self.settings.enable_reseller_catalogue = 0
		with self.assertRaises(frappe.PermissionError):
			catalogue_api.get_catalogues()

	# --- what is refused -----------------------------------------------------------------------------

	def test_a_catalogue_needs_a_saved_brand(self):
		frappe.set_user("Administrator")
		frappe.delete_doc("Reseller Catalogue Profile", shop.OTHER_CUSTOMER, force=True, ignore_permissions=True)
		frappe.set_user(shop.OTHER_USER)
		answer = self.ask()
		self.assertFalse(answer["ok"])
		self.assertEqual(answer["message"], catalogue_message("no_brand"))
		self.enqueue.assert_not_called()

	def test_what_is_wrong_in_a_request_is_refused_beside_its_field(self):
		for kwargs, field in (
			({"title": ""}, "title"),
			({"title": "x" * 81}, "title"),
			({"options": json.dumps({"markup_percent": 500})}, "markup_percent"),
			({"options": json.dumps({"prices": "cost"})}, "prices"),
			({"options": json.dumps({"layout": "poster"})}, "layout"),
			({"picked": json.dumps({})}, "selection"),
			({"picked": "not json"}, "selection"),
			({"picked": json.dumps({"items": ["no such product"]})}, "selection"),
		):
			with self.subTest(field=field, kwargs=str(kwargs)[:40]):
				answer = self.ask(**kwargs)
				self.assertFalse(answer["ok"])
				self.assertEqual(answer["field"], field)
				self.assertTrue(answer["message"])
		self.assertFalse(frappe.db.count(DOCTYPE, {"customer": shop.CUSTOMER}), "nothing was written")

	def test_a_selection_over_the_cap_is_refused_before_any_work(self):
		with mock.patch.object(selection, "MAX_PRODUCTS", 1):
			answer = self.ask()
		self.assertEqual(answer["field"], "selection")
		self.assertEqual(answer["message"], catalogue_message("too_many_products", 1))

	def test_a_second_catalogue_waits_for_the_first(self):
		self.assertTrue(self.ask()["ok"])
		again = self.ask()
		self.assertFalse(again["ok"])
		self.assertEqual(again["message"], catalogue_message("busy"))
		self.assertEqual(frappe.db.count(DOCTYPE, {"customer": shop.CUSTOMER}), 1)

	def test_the_day_has_a_limit(self):
		with mock.patch.object(jobs, "DAILY_LIMIT", 1):
			first = self.ask()
			frappe.db.set_value(DOCTYPE, self.newest(), "status", READY)
			second = self.ask()
		self.assertTrue(first["ok"])
		self.assertEqual(second["message"], catalogue_message("daily_limit", 1))

	# --- asking ---------------------------------------------------------------------------------------

	def test_a_request_is_written_cleaned_for_the_signed_in_customer_and_queued_after_the_commit(self):
		answer = self.ask(picked=json.dumps({**PICKED, "price": 1, "customer": "someone else"}))
		self.assertTrue(answer["ok"], answer)
		record = frappe.get_doc(DOCTYPE, self.newest())
		self.assertEqual((record.customer, record.status, record.title), (shop.CUSTOMER, QUEUED, "Spring 2027"))
		self.assertEqual(json.loads(record.selection), {"item_groups": [shop.PARENT_GROUP], "brands": [], "items": []})
		self.assertEqual(json.loads(record.options), {"markup_percent": 30.0, "prices": "customers", "layout": "grid"})
		self.assertEqual(record.expires_on, frappe.utils.getdate(add_days(nowdate(), jobs.KEEP_DAYS)))
		self.enqueue.assert_called_once()
		args, kwargs = self.enqueue.call_args
		self.assertEqual(args[0], "webshop.webshop.catalogue.jobs.generate")
		self.assertEqual((kwargs["queue"], kwargs["enqueue_after_commit"], kwargs["catalogue"]), ("long", True, record.name))
		self.assertTrue(answer["busy"])
		self.assertEqual([row["name"] for row in answer["catalogues"]], [record.name])

	def test_the_state_lists_the_resellers_own_catalogues_only(self):
		self.ask()
		first = self.newest()
		frappe.set_user(shop.OTHER_USER)
		self.assertEqual(catalogue_api.get_catalogues()["catalogues"], [])
		self.assertTrue(first)

	def test_the_page_offers_the_shops_groups_and_brands_and_finds_products(self):
		choices = catalogue_api.get_choices()
		self.assertIn(shop.PARENT_GROUP, [group["name"] for group in choices["groups"]])
		self.assertIn(shop.BRAND_A, [brand["name"] for brand in choices["brands"]])
		found = catalogue_api.search_products(text="Cat First")["products"]
		self.assertIn(shop.FIRST, [row["item_code"] for row in found])
		counted = catalogue_api.count_products(picked=json.dumps({"brands": [shop.BRAND_A]}))
		self.assertEqual((counted["count"], counted["too_many"]), (2, False))
		self.assertEqual(catalogue_api.count_products(picked="not json")["count"], 0)

	# --- the job ----------------------------------------------------------------------------------------

	def run_job(self, name):
		jobs.generate(name)
		return frappe.get_doc(DOCTYPE, name)

	def test_the_job_makes_the_catalogue_and_attaches_a_private_pdf(self):
		if not chromium_available():
			self.skipTest("no Chromium on this bench")
		self.ask()
		name = self.newest()
		record = self.run_job(name)
		self.assertEqual((record.status, record.progress, record.error), (READY, 100, ""))
		self.assertGreaterEqual(record.page_count, 3)
		self.assertEqual(record.item_count, selection.count_products(selection.clean_selection(PICKED)))
		self.assertEqual(record.prices_as_of, frappe.utils.getdate(nowdate()))
		self.assertTrue(record.file)
		file = frappe.get_doc("File", {"attached_to_doctype": DOCTYPE, "attached_to_name": name})
		self.assertEqual(file.is_private, 1)
		self.assertFalse(catalogue_api.get_catalogues()["busy"], "the next one may start")

	def test_the_owner_downloads_it_and_nobody_else_can_reach_it(self):
		if not chromium_available():
			self.skipTest("no Chromium on this bench")
		self.ask()
		name = self.newest()
		self.run_job(name)
		response = catalogue_api.download_catalogue(name=name)
		self.assertEqual(response.mimetype, "application/pdf")
		self.assertEqual(response.headers["X-Robots-Tag"], "noindex")
		self.assertIn("no-store", response.headers["Cache-Control"])
		self.assertTrue(response.data.startswith(b"%PDF"))
		self.assertIn("attachment", response.headers["Content-Disposition"])
		frappe.set_user(shop.OTHER_USER)
		for call in (
			lambda: catalogue_api.download_catalogue(name=name),
			lambda: catalogue_api.delete_catalogue(name=name),
			lambda: catalogue_api.remake_catalogue(name=name),
		):
			with self.assertRaises(frappe.DoesNotExistError):
				call()
		self.assertTrue(frappe.db.exists(DOCTYPE, name), "a foreign delete deleted nothing")

	def test_a_catalogue_not_ready_has_no_download(self):
		self.ask()
		with self.assertRaises(frappe.DoesNotExistError):
			catalogue_api.download_catalogue(name=self.newest())

	def test_a_catalogue_can_be_made_again_and_deleted_with_its_file(self):
		if not chromium_available():
			self.skipTest("no Chromium on this bench")
		self.ask()
		name = self.newest()
		self.run_job(name)
		again = None
		with mock.patch("frappe.enqueue"):
			again = catalogue_api.remake_catalogue(name=name)
		self.assertTrue(again["ok"], again)
		self.assertEqual(frappe.db.count(DOCTYPE, {"customer": shop.CUSTOMER}), 2)
		self.assertEqual(frappe.db.get_value(DOCTYPE, self.newest(), "title"), "Spring 2027")
		self.assertTrue(frappe.db.exists("File", {"attached_to_doctype": DOCTYPE, "attached_to_name": name}))
		catalogue_api.delete_catalogue(name=name)
		self.assertFalse(frappe.db.exists(DOCTYPE, name))
		self.assertFalse(frappe.db.exists("File", {"attached_to_doctype": DOCTYPE, "attached_to_name": name}))

	def test_a_job_that_breaks_leaves_a_sentence_and_a_log_never_the_trace(self):
		self.ask()
		name = self.newest()
		logged = frappe.db.count("Error Log", {"method": "Reseller catalogue failed"})
		with mock.patch.object(jobs, "chromium_available", return_value=True), mock.patch.object(
			book, "build_book", side_effect=RuntimeError("secret internal detail")
		):
			record = self.run_job(name)
		self.assertEqual(record.status, FAILED)
		self.assertEqual(record.error, catalogue_message("failed"))
		self.assertNotIn("secret", record.error)
		self.assertGreater(frappe.db.count("Error Log", {"method": "Reseller catalogue failed"}), logged)
		self.assertFalse(catalogue_api.get_catalogues()["busy"], "a failure does not shut the reseller out")

	def test_a_selection_that_grew_over_the_cap_while_it_waited_fails_with_the_limit_named(self):
		self.ask()
		name = self.newest()
		with mock.patch.object(jobs, "chromium_available", return_value=True), mock.patch.object(
			selection, "MAX_PRODUCTS", 1
		), mock.patch.object(jobs, "NUMBERS", {"too_many_products": 1}):
			record = self.run_job(name)
		self.assertEqual((record.status, record.error), (FAILED, catalogue_message("too_many_products", 1)))

	def test_a_bench_without_chromium_says_so_instead_of_failing_in_silence(self):
		self.ask()
		name = self.newest()
		with mock.patch.object(jobs, "chromium_available", return_value=False):
			record = self.run_job(name)
		self.assertEqual((record.status, record.error), (FAILED, catalogue_message("no_engine")))

	def test_a_catalogue_that_is_not_waiting_is_left_alone(self):
		self.ask()
		name = self.newest()
		frappe.db.set_value(DOCTYPE, name, "status", READY)
		with mock.patch.object(book, "build_book") as build:
			self.run_job(name)
		build.assert_not_called()

	def test_the_progress_goes_up_with_each_stage_and_never_down(self):
		self.ask()
		name = self.newest()
		seen = []
		real = jobs._set

		def spy(catalogue, **values):
			if "progress" in values:
				seen.append(values["progress"])
			return real(catalogue, **values)

		with mock.patch.object(jobs, "_set", side_effect=spy):
			self.run_job(name)
		self.assertEqual(seen, sorted(seen))
		self.assertIn(1, seen[:1])

	# --- the night's cleaning --------------------------------------------------------------------------------

	def test_a_catalogue_whose_worker_is_gone_blocks_nobody_and_is_closed_at_night(self):
		self.ask()
		name = self.newest()
		old = add_to_date(now_datetime(), minutes=-(jobs.STALLED_MINUTES + 5))
		frappe.db.set_value(DOCTYPE, name, {"status": RUNNING, "creation": old}, update_modified=False)
		self.assertFalse(jobs.is_running(shop.CUSTOMER))
		self.assertTrue(self.ask()["ok"], "the reseller can ask again")
		jobs.purge()
		self.assertEqual(frappe.db.get_value(DOCTYPE, name, "status"), FAILED)
		self.assertEqual(frappe.db.get_value(DOCTYPE, name, "error"), catalogue_message("stalled"))

	def test_a_catalogue_kept_long_enough_goes_with_its_file(self):
		if not chromium_available():
			self.skipTest("no Chromium on this bench")
		self.ask()
		name = self.newest()
		self.run_job(name)
		frappe.db.set_value(DOCTYPE, name, "expires_on", add_days(nowdate(), -1))
		jobs.purge()
		self.assertFalse(frappe.db.exists(DOCTYPE, name))
		self.assertFalse(frappe.db.exists("File", {"attached_to_doctype": DOCTYPE, "attached_to_name": name}))

	def test_a_catalogue_still_within_its_days_is_kept(self):
		self.ask()
		name = self.newest()
		frappe.db.set_value(DOCTYPE, name, {"status": READY, "expires_on": add_days(nowdate(), 1)})
		jobs.purge()
		self.assertTrue(frappe.db.exists(DOCTYPE, name))
