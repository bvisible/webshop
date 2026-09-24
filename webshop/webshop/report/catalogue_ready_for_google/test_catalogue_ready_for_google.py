# //// Neoffice — added file (no upstream equivalent). neoffice-maintenance#691, lot 6.
"""The report Catalogue Ready for Google: what would make a listing better (seo/feeds/google.py
entry_warnings), and the report's rows, filters and summary over the feed's own rules — the feed's
decisions are scripted here, test_google_feed checks them."""

from contextlib import nullcontext
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.report.catalogue_ready_for_google import catalogue_ready_for_google as report
from webshop.webshop.seo.feeds import google

PICTURE_SIZE = "webshop.webshop.utils.renditions.picture_size"


def good_entry(**overrides):
	entry = {
		"id": "ITEM-1",
		"title": "Trail shoe",
		"description": "A trail shoe for mountain paths, " * 6,
		"image_link": "https://shop.test/files/a.jpg",
		"additional_image_link": ["https://shop.test/files/b.jpg"],
		"brand": "Trailhead",
		"gtin": "7612345678900",
		"google_product_category": "187",
		"price": "120.00 CHF",
		"availability": "in_stock",
	}
	entry.update(overrides)
	return {key: value for key, value in entry.items() if value is not None}


class TestWhatWouldMakeAListingBetter(FrappeTestCase):
	def warnings(self, entry, name="Trail shoe", size=(1200, 1200)):
		with patch(PICTURE_SIZE, return_value=size):
			return google.entry_warnings(entry, frappe._dict(web_item_name=name), "/files/a.jpg")

	def test_a_complete_listing_needs_nothing(self):
		self.assertEqual(self.warnings(good_entry()), [])

	def test_each_gap_is_named(self):
		cases = {
			"no_identifier": good_entry(gtin=None, identifier_exists="no"),
			"no_brand": good_entry(brand=None),
			"short_description": good_entry(description="Short."),
			"one_picture": good_entry(additional_image_link=None),
			"no_category": good_entry(google_product_category=None),
		}
		for code, entry in cases.items():
			with self.subTest(code=code):
				self.assertEqual(self.warnings(entry), [code])
		self.assertEqual(self.warnings(good_entry(), name="x" * 151), ["title_cut"])
		self.assertEqual(self.warnings(good_entry(), size=(1200, 600)), ["small_picture"])
		self.assertEqual(self.warnings(good_entry(), size=None), [], "an external picture is not measured")

	def test_a_description_that_only_repeats_the_name_says_nothing(self):
		entry = good_entry(title="Trail shoe " * 20, description="Trail shoe " * 20)
		self.assertIn("short_description", self.warnings(entry))

	def test_every_code_has_a_sentence(self):
		for code in ("no_identifier", "no_brand", "short_description", "title_cut", "one_picture", "small_picture", "no_category"):
			self.assertNotEqual(google.warning_label(code), code)


def in_users_language(label, code):
	"""A label as the report writes it: in the language of the person who asked for it."""
	language = frappe.local.lang
	frappe.set_user_lang(frappe.session.user)
	try:
		return label(code)
	finally:
		frappe.local.lang = language


class TestTheReport(FrappeTestCase):
	def run_report(self, filters=None, refusal=None):
		docs = {
			name: frappe._dict(name=name, item_code=name.replace("WI", "ITEM"), web_item_name=f"Product {name}", slideshow=None)
			for name in ("WI-1", "WI-2", "WI-3")
		}
		outcomes = {
			"WI-1": (good_entry(), None),
			"WI-2": (None, "no_price"),
			"WI-3": (good_entry(brand=None), None),
		}
		site = frappe._dict(key="default", profile=None)
		real_cached_doc = frappe.get_cached_doc

		def cached_doc(doctype, *args, **kwargs):
			if doctype == "Website Item":
				return docs[args[0]]
			return real_cached_doc(doctype, *args, **kwargs)

		with (
			patch.object(google, "feed_sites", return_value=[site]),
			patch.object(google, "serving", lambda site: nullcontext()),
			patch(
				"webshop.webshop.doctype.webshop_settings.webshop_settings.get_shopping_cart_settings",
				return_value=frappe._dict(),
			),
			patch.object(google, "site_refusal", return_value=refusal),
			patch.object(google, "excluded_groups", return_value=set()),
			patch.object(google, "attribute_map", return_value={}),
			patch.object(google, "feed_candidates", return_value=list(docs)),
			patch("frappe.get_cached_doc", side_effect=cached_doc),
			patch.object(google, "item_entry", side_effect=lambda doc, *args: outcomes[doc.name]),
			patch.object(report, "first_picture", return_value=None),
		):
			return report.execute(filters or {})

	def test_every_product_with_its_fate_and_what_it_lacks(self):
		columns, rows, message, chart, summary = self.run_report()
		self.assertIsNone(message)
		self.assertEqual([row["website_item"] for row in rows], ["WI-1", "WI-2", "WI-3"])
		by_name = {row["website_item"]: row for row in rows}
		self.assertEqual(by_name["WI-2"]["reason"], in_users_language(google.reason_label, "no_price"))
		self.assertEqual(by_name["WI-2"]["pictures"], 0)
		self.assertEqual(by_name["WI-3"]["suggestions"], in_users_language(google.warning_label, "no_brand"))
		self.assertEqual(by_name["WI-1"]["suggestions"], "")
		self.assertEqual(by_name["WI-1"]["price"], "120.00 CHF")
		self.assertEqual([item["value"] for item in summary], [2, 1, 1])
		self.assertTrue({"status", "reason", "suggestions"} <= {column["fieldname"] for column in columns})

	def test_the_filters(self):
		self.assertEqual([r["website_item"] for r in self.run_report({"show": "Left out"})[1]], ["WI-2"])
		self.assertEqual([r["website_item"] for r in self.run_report({"show": "Sent"})[1]], ["WI-1", "WI-3"])
		self.assertEqual([r["website_item"] for r in self.run_report({"show": "Suggestions"})[1]], ["WI-3"])
		self.assertEqual([r["website_item"] for r in self.run_report({"website_item": "WI-3"})[1]], ["WI-3"])

	def test_a_site_without_a_feed_says_why(self):
		columns, rows, message = self.run_report(refusal="prices are hidden from visitors")
		self.assertEqual(rows, [])
		self.assertIn("prices are hidden from visitors", message)

	def test_it_never_runs_inside_a_web_request(self):
		frappe.local.session_obj = object()
		self.addCleanup(delattr, frappe.local, "session_obj")
		with self.assertRaises(frappe.ValidationError):
			report.execute({})

	def test_the_language_is_given_back(self):
		before = frappe.local.lang
		self.run_report()
		self.assertEqual(frappe.local.lang, before)

	def test_the_sites_of_the_filter(self):
		profile = {"name": "B2B shop", "primary_domain": "b2b.shop.test"}
		with (
			patch("frappe.only_for"),
			patch.object(google, "feed_sites", return_value=[frappe._dict(key="b2b_shop", profile=profile)]),
		):
			self.assertEqual(report.sites(), [{"key": "b2b_shop", "label": "B2B shop"}])
