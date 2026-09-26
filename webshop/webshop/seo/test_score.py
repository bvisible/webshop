# //// Neoffice — added file (no upstream equivalent): the SEO score (seo/score.py), its criteria, what
# //// the item stores and what the workspace reads. neoffice-maintenance#691, plan note 20, 2026-09-26.
"""The SEO score: each criterion, a criterion that does not concern the product, weights that make
100, a complete product and a bare one, what the item stores, and the workspace's cards and charts
reading it."""

import json
from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.seo import score
from webshop.webshop.seo.test_variants import _list_price
from webshop.webshop.tests.utils import (
	ensure_shop_settings,
	make_test_item,
	restore_webshop_settings,
	selling_price_list,
	snapshot_webshop_settings,
)

LONG_TEXT = " ".join(["word"] * 80)


def _found(**overrides):
	"""What gather() reads of a product that has everything."""
	found = frappe._dict(
		kind="product",
		name="Trail shoe",
		published=1,
		sold=0,
		refusal=None,
		title="Trail shoe Ridge Runner - Trailhead | Mountain shop",
		description="A light trail shoe for mountain paths, with a grippy sole and a breathable upper.",
		long_text=LONG_TEXT,
		sent=True,
		reason=None,
		brand="Trailhead",
		item_group="Shoes",
		no_product_identifier=0,
		specifications=4,
		videos=1,
		offer=frappe._dict(price="120.00 CHF", availability="in_stock"),
		pictures=4,
		first_picture_width=1200,
		alt_total=4,
		alt_described=4,
		gtin="4006381333931",
		mpn=None,
		google_category="187",
		reviews=3,
		rating=4.5,
	)
	found.update(overrides)
	return found


def _status(result, code):
	return next(criterion.status for criterion in result.criteria if criterion.code == code)


class TestTheCriteria(FrappeTestCase):
	def test_the_weights_make_100_and_every_criterion_is_judged(self):
		self.assertEqual(sum(points for _code, points in score.CRITERIA), 100)
		self.assertEqual({code for code, _points in score.CRITERIA}, set(score.JUDGES))

	def test_a_product_that_has_everything_scores_100(self):
		result = score.evaluate(_found())
		self.assertEqual(result.score, 100)
		self.assertEqual(result.missing, [])
		self.assertEqual(result.google_status, "sent")

	def test_a_bare_product_scores_almost_nothing(self):
		result = score.evaluate(
			_found(
				title="Shoe | Shop",
				description="Trail shoe",
				long_text="Trail shoe",
				sent=False,
				reason="no_price",
				brand=None,
				specifications=0,
				offer=None,
				pictures=0,
				first_picture_width=None,
				alt_total=0,
				alt_described=0,
				gtin=None,
				google_category="",
			)
		)
		# the title is the only thing it has, half of it; the pictures' descriptions do not count
		# without a picture
		self.assertEqual(result.score, round(100 * 5 / (100 - 8)))
		self.assertEqual(_status(result, "alt_text"), score.NOT_APPLICABLE)
		self.assertEqual(
			result.missing,
			[
				"search_description",
				"long_description",
				"pictures",
				"identifier",
				"brand",
				"google_category",
				"specifications",
				"offer",
				"sent_to_google",
			],
		)
		self.assertEqual(result.google_status, "no_price")

	def test_what_does_not_concern_the_product_leaves_the_total(self):
		gift_card = score.evaluate(_found(kind="gift_card", gtin=None, brand=None, offer=None, sent=False, reason="gift_card"))
		for code in ("identifier", "brand", "google_category", "specifications", "offer", "sent_to_google"):
			self.assertEqual(_status(gift_card, code), score.NOT_APPLICABLE, code)
		self.assertEqual(gift_card.score, 100)
		self.assertEqual(gift_card.google_status, "gift_card")

		variant = score.evaluate(_found(kind="grouped_variant", title="", description="", alt_described=0, specifications=0))
		for code in ("title", "search_description", "alt_text", "specifications"):
			self.assertEqual(_status(variant, code), score.NOT_APPLICABLE, code)
		self.assertEqual(variant.score, 100)

	def test_a_model_is_judged_on_its_variants(self):
		on_sale = score.evaluate(
			_found(kind="model", gtin=None, sent=False, reason="model", offer=None, variants=frappe._dict(shown=True, priced=3, available=2))
		)
		self.assertEqual(_status(on_sale, "identifier"), score.NOT_APPLICABLE)
		self.assertEqual(_status(on_sale, "sent_to_google"), score.NOT_APPLICABLE)
		self.assertEqual(_status(on_sale, "offer"), score.GOOD)
		sold_out = score.evaluate(_found(kind="model", offer=None, variants=frappe._dict(shown=True, priced=3, available=0)))
		self.assertEqual(_status(sold_out, "offer"), score.IMPROVE)
		unpriced = score.evaluate(_found(kind="model", offer=None, variants=frappe._dict(shown=True, priced=0, available=0)))
		self.assertEqual(_status(unpriced, "offer"), score.MISSING)
		own_pages = score.evaluate(_found(kind="model", offer=None, variants=frappe._dict(shown=False)))
		self.assertEqual(_status(own_pages, "offer"), score.NOT_APPLICABLE)

	def test_the_identifier(self):
		self.assertEqual(_status(score.evaluate(_found()), "identifier"), score.GOOD)
		self.assertEqual(_status(score.evaluate(_found(gtin=None, mpn="TR-01")), "identifier"), score.IMPROVE)
		self.assertEqual(_status(score.evaluate(_found(gtin=None)), "identifier"), score.MISSING)
		# a product made here has no barcode: declared, it is not counted
		declared = score.evaluate(_found(gtin=None, no_product_identifier=1))
		self.assertEqual(_status(declared, "identifier"), score.NOT_APPLICABLE)
		# a GTIN counts, whatever the box says
		self.assertEqual(_status(score.evaluate(_found(no_product_identifier=1)), "identifier"), score.GOOD)

	def test_titles_descriptions_pictures_and_characteristics(self):
		cases = (
			({"title": "x" * 61}, "title", score.IMPROVE),
			({"title": "Trail shoe | Shop"}, "title", score.IMPROVE),
			({"description": "Light shoe."}, "search_description", score.IMPROVE),
			({"description": "x" * 200}, "search_description", score.IMPROVE),
			({"description": "trail shoe"}, "search_description", score.MISSING),
			({"long_text": "A light shoe for the mountains."}, "long_description", score.IMPROVE),
			({"long_text": ""}, "long_description", score.MISSING),
			# ERPNext writes the item's code as the description of an item nobody described
			({"long_text": "TRAIL-01", "bare": frozenset({"trail shoe", "trail-01"})}, "long_description", score.MISSING),
			({"description": "TRAIL-01", "bare": frozenset({"trail shoe", "trail-01"})}, "search_description", score.MISSING),
			({"pictures": 2}, "pictures", score.IMPROVE),
			({"first_picture_width": 500}, "pictures", score.IMPROVE),
			({"alt_described": 2}, "alt_text", score.IMPROVE),
			({"alt_described": 0}, "alt_text", score.MISSING),
			({"specifications": 1}, "specifications", score.IMPROVE),
			({"brand": None}, "brand", score.MISSING),
			({"google_category": ""}, "google_category", score.MISSING),
			({"offer": frappe._dict(price="120.00 CHF", availability="out_of_stock")}, "offer", score.IMPROVE),
			({"offer": frappe._dict(price="120.00 CHF", availability="backorder")}, "offer", score.GOOD),
		)
		for overrides, code, expected in cases:
			with self.subTest(overrides=overrides):
				self.assertEqual(_status(score.evaluate(_found(**overrides)), code), expected)

	def test_google_shopping_by_the_merchant_s_choice_or_the_site_s(self):
		excluded = score.evaluate(_found(sent=False, reason="excluded"))
		self.assertEqual(_status(excluded, "sent_to_google"), score.NOT_APPLICABLE)
		self.assertEqual(_status(excluded, "google_category"), score.NOT_APPLICABLE)
		self.assertEqual(excluded.google_status, "excluded")
		no_feed = score.evaluate(_found(refusal="prices are hidden from visitors", sent=False, offer=None))
		for code in ("offer", "sent_to_google", "google_category"):
			self.assertEqual(_status(no_feed, code), score.NOT_APPLICABLE, code)
		self.assertEqual(no_feed.google_status, "no_feed")
		unpublished = score.evaluate(_found(published=0))
		self.assertEqual(_status(unpublished, "sent_to_google"), score.NOT_APPLICABLE)
		self.assertEqual(unpublished.google_status, "unpublished")
		failed = score.evaluate(_found(sent=False, reason="error", offer=None))
		self.assertEqual(_status(failed, "offer"), score.MISSING)
		self.assertEqual(_status(failed, "sent_to_google"), score.MISSING)

	def test_the_checklist_says_why_a_barcode_is_not_used(self):
		result = score.evaluate(_found(gtin=None, barcode_problem=frappe._dict(barcode="2000000012346", problem="restricted")))
		identifier = next(criterion for criterion in result.criteria if criterion.code == "identifier")
		self.assertEqual(identifier.status, score.MISSING)
		self.assertIn("2000000012346", score.explain(identifier)["message"])

	def test_bands(self):
		self.assertEqual([score.band_of(value) for value in (0, 49, 50, 79, 80, 100)], [0, 0, 1, 1, 2, 2])
		self.assertIsNone(score.band_of(None))

	def test_every_criterion_says_what_it_found(self):
		"""Every status of every criterion has its sentence: no KeyError waits for a merchant."""
		fixtures = (
			_found(),
			_found(title="x" * 61, description="x" * 200, gtin=None, mpn="TR-01", pictures=1, alt_described=1, specifications=1),
			_found(title="Shoe", description="Short.", long_text="A few words.", first_picture_width=300),
			_found(description="Trail shoe", long_text="", pictures=0, alt_total=0, gtin=None, brand=None, google_category="", specifications=0, offer=None, sent=False, reason="no_price"),
			_found(kind="gift_card", sent=False, reason="gift_card"),
			_found(kind="grouped_variant"),
			_found(kind="model", sent=False, reason="model", variants=frappe._dict(shown=True, priced=2, available=1)),
			_found(refusal="no", sent=False),
			_found(offer=frappe._dict(price="120.00 CHF", availability="out_of_stock")),
			_found(gtin=None, no_product_identifier=1, published=0),
			_found(gtin=None, barcode_problem=frappe._dict(barcode="12345", problem="length")),
			_found(gtin=None, mpn="TR-01", barcode_problem=frappe._dict(barcode="4006381333931", problem="other_unit", uom="Box")),
		)
		for found in fixtures:
			result = score.evaluate(found)
			for criterion in result.criteria:
				with self.subTest(code=criterion.code, status=criterion.status):
					explained = score.explain(criterion)
					self.assertTrue(explained["label"])
					self.assertTrue(explained["message"], criterion)
			for row in result.informative:
				self.assertTrue(score.explain_informative(row)["message"])


class TestStoredOnTheItem(FrappeTestCase):
	"""A published product with a price and a picture, scored through the database as the job does."""

	FIELDS = ("enabled", "show_price", "hide_price_for_guest", "enable_variants")

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.written = ensure_shop_settings()
		cls.snapshot = snapshot_webshop_settings(cls.FIELDS)
		frappe.db.set_single_value("Webshop Settings", "hide_price_for_guest", 0)
		# class fixtures survive FrappeTestCase's rollback only committed (CLAUDE.md, Testing Strategy)
		frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit
		frappe.local.shopping_cart_settings = None
		frappe.clear_cache(doctype="Webshop Settings")

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		restore_webshop_settings({**cls.snapshot, **cls.written})
		super().tearDownClass()

	def setUp(self):
		self.prices = [
			patch("webshop.webshop.shopping_cart.product_info.get_price", side_effect=_list_price),
			patch("erpnext.utilities.product.get_price", side_effect=_list_price),
		]
		for price in self.prices:
			price.start()
		frappe.local.shopping_cart_settings = None

	def tearDown(self):
		for price in self.prices:
			price.stop()
		frappe.set_user("Administrator")

	def product(self):
		from webshop.webshop.doctype.website_item.website_item import make_website_item

		code = f"_Test SEO score {frappe.generate_hash(length=8)}"
		make_test_item(code, item_name="Trail shoe", brand=None)
		frappe.get_doc(
			{
				"doctype": "Item Price",
				"item_code": code,
				"price_list": selling_price_list(),
				"price_list_rate": 120,
				"selling": 1,
			}
		).insert(ignore_permissions=True)
		name = make_website_item(frappe.get_doc("Item", code), save=True)[0]
		frappe.db.set_value("Website Item", name, {"published": 1, "website_image": "/files/wsp-seo-score.jpg"})
		return name

	def test_the_job_stores_the_score_the_checklist_reads(self):
		name = self.product()
		result = score.score_item(name)
		self.assertIsNotNone(result)
		stored = frappe.db.get_value(
			"Website Item",
			name,
			["seo_score", "seo_score_checked_on", "seo_score_details", "seo_missing", "seo_google_status", "modified"],
			as_dict=True,
		)
		self.assertEqual(stored.seo_score, result.score)
		self.assertTrue(stored.seo_score_checked_on)
		details = json.loads(stored.seo_score_details)
		self.assertEqual([row["code"] for row in details["criteria"]], [code for code, _points in score.CRITERIA])
		# the item says nothing yet and carries no barcode: both are missing, and findable by a card
		self.assertIn(",long_description,", stored.seo_missing)
		self.assertIn(",identifier,", stored.seo_missing)
		self.assertEqual(stored.seo_google_status, result.google_status)

		answer = score.checklist(name, refresh=0)
		self.assertEqual(answer["score"], result.score)
		self.assertEqual(len(answer["criteria"]), len(score.CRITERIA))
		self.assertTrue(all(row["label"] and "message" in row for row in answer["criteria"]))

	def test_the_score_leaves_modified_alone(self):
		name = self.product()
		before = frappe.db.get_value("Website Item", name, "modified")
		score.score_item(name)
		self.assertEqual(frappe.db.get_value("Website Item", name, "modified"), before)

	def test_a_visitor_and_a_portal_customer_read_no_score(self):
		"""The score is the merchant's: neither the checklist nor the charts answer anyone else."""
		from webshop.webshop.dashboard_chart_source.webshop_seo_score_bands import (
			webshop_seo_score_bands as bands_chart,
		)
		from webshop.webshop.tests.utils import portal_customer

		name = self.product()
		score.score_item(name)
		email = f"seo-score-{frappe.generate_hash(length=8)}@example.com"
		portal_customer(email, f"_Test SEO score customer {frappe.generate_hash(length=8)}")
		for user in ("Guest", email):
			with self.subTest(user=user):
				frappe.set_user(user)
				with self.assertRaises(frappe.PermissionError):
					score.checklist(name, refresh=0)
				with self.assertRaises(frappe.PermissionError):
					bands_chart.get(chart_name="Products by SEO Score", no_cache=1)
				frappe.set_user("Administrator")

	def test_the_form_queues_the_computation_and_a_save_does_not(self):
		"""A sync saving thousands of items through the API must not flood the short queue: only
		the form asks, when it opens or reloads after its own save."""
		name = self.product()
		with patch.object(score, "queue_item") as queued:
			frappe.get_doc("Website Item", name).save()
			queued.assert_not_called()
			score.checklist(name, refresh=1)
		queued.assert_called_once_with(name)

	def test_the_workspace_reads_the_stored_scores(self):
		from frappe.desk.doctype.number_card.number_card import get_result

		from webshop.webshop.dashboard_chart_source.webshop_google_shopping_status import (
			webshop_google_shopping_status as status_chart,
		)
		from webshop.webshop.dashboard_chart_source.webshop_seo_score_bands import (
			webshop_seo_score_bands as bands_chart,
		)

		name = self.product()
		result = score.score_item(name)
		bands = bands_chart.get(chart_name="Products by SEO Score", no_cache=1)
		self.assertEqual(len(bands["labels"]), len(score.BANDS))
		self.assertGreaterEqual(bands["datasets"][0]["values"][score.band_of(result.score)], 1)
		statuses = status_chart.get(chart_name="Google Shopping Status", no_cache=1)
		self.assertIn(score.google_status_label(result.google_status), statuses["labels"])
		for card in frappe.get_all("Number Card", filters={"module": "Webshop", "document_type": "Website Item"}, pluck="name"):
			with self.subTest(card=card):
				doc = frappe.get_doc("Number Card", card)
				self.assertGreaterEqual(get_result(doc.as_dict(), doc.filters_json), 0)
		without_identifier = frappe.get_doc("Number Card", "Products Without GTIN or Reference")
		self.assertGreaterEqual(get_result(without_identifier.as_dict(), without_identifier.filters_json), 1)

	def test_the_stored_score_is_the_main_site_s_with_a_feed(self):
		"""A business site hides its prices: its score leaves the offer and Google out, and would
		flatter the product. The first site with a feed that shows it wins, the main one first."""
		from webshop.webshop.seo.feeds import google

		name = self.product()
		sites = [
			frappe._dict(key="shop", profile={"name": "Shop"}),
			frappe._dict(key="business", profile={"name": "Business", "is_default": 1}),
		]
		refusals = {"business": "prices are hidden from visitors", "shop": None}
		results = {key: frappe._dict(score=score_value, missing=[], google_status="sent", sent=True) for key, score_value in (("business", 90), ("shop", 60))}
		serving_now = {}

		@contextmanager
		def serving(site):
			serving_now["key"] = site.key
			yield

		with (
			patch.object(google, "feed_sites", return_value=sites),
			patch.object(google, "serving", serving),
			patch.object(google, "feed_candidates", return_value=[name]),
			patch.object(score, "site_context", side_effect=lambda: frappe._dict(refusal=refusals[serving_now["key"]])),
			patch.object(score, "product_score", side_effect=lambda doc, context: results[serving_now["key"]]),
			patch.object(score, "store") as store,
			patch.object(score, "write_snapshot"),
		):
			self.assertEqual([site.key for site in score.scoring_sites()], ["business", "shop"])
			self.assertEqual(score.score_item(name).score, 60)
			self.assertEqual(store.call_args.args, (name, results["shop"], "shop"))
			store.reset_mock()
			score.refresh_all()
			self.assertEqual(store.call_args.args, (name, results["shop"], "shop"))

	def test_the_night_writes_one_snapshot_per_site_and_day(self):
		from webshop.webshop.seo.feeds import google

		name = self.product()
		# this product alone, and no commit in the middle of the test's transaction
		with patch.object(google, "feed_candidates", return_value=[name]), patch.object(score, "COMMIT_EVERY", 10**9):
			score.refresh_all()
			score.refresh_all()
		self.assertTrue(frappe.db.get_value("Website Item", name, "seo_score_checked_on"))
		# the curve draws the days measured, and only them
		from webshop.webshop.dashboard_chart_source.webshop_seo_score_history import (
			webshop_seo_score_history as history,
		)

		curve = history.get(chart_name="Average SEO Score", no_cache=1)
		today = frappe.utils.nowdate()
		self.assertIn(frappe.utils.formatdate(today), curve["labels"])
		self.assertEqual(len(curve["labels"]), len(set(curve["labels"])))
		snapshots = frappe.get_all("Webshop SEO Snapshot", filters={"date": today}, fields=["site", "products", "average_score"])
		self.assertEqual(len(snapshots), len({row.site for row in snapshots}))
		self.assertTrue(all(row.products >= 1 for row in snapshots))
