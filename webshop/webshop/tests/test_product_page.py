# //// Neoffice — added file (no upstream equivalent).
"""The product page's context: the promises it prints and the brand it introduces."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.tests.utils import restore_webshop_settings, snapshot_webshop_settings
from webshop.webshop.utils.promises import PROMISE_FIELDS


class TestProductPage(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.snapshot = snapshot_webshop_settings(PROMISE_FIELDS)

	@classmethod
	def tearDownClass(cls):
		restore_webshop_settings(cls.snapshot)
		super().tearDownClass()

	def _published_item(self):
		name = frappe.db.get_value("Website Item", {"published": 1}, "name")
		if not name:
			self.skipTest("no published website item on this site")
		return frappe.get_doc("Website Item", name)

	def _context(self, doc):
		# A request's context carries the page route; set_metatags() builds the page URL from it.
		context = frappe._dict(metatags={}, shopping_cart=frappe._dict(), route=doc.route)
		doc.get_context(context)
		return context

	def test_the_page_renders_without_a_request(self):
		"""A job, a test or the console renders the page with no HTTP request bound.

		Upstream's breadcrumb builder read `frappe.request.environ` unconditionally, and
		the whole page raised "object is not bound" in the nightly suite (2026-09-13).
		"""
		doc = self._published_item()
		# create=True: outside a request, frappe.local has no "request" attribute to patch at all.
		with patch.object(frappe.local, "request", None, create=True):
			context = self._context(doc)
		self.assertTrue(context.parents)
		self.assertEqual(context.parents[0]["route"], "/")

	def test_promises_follow_the_settings(self):
		doc = self._published_item()
		frappe.db.set_single_value("Webshop Settings", "free_shipping_from", 0)
		frappe.db.set_single_value("Webshop Settings", "delivery_delay", "")
		frappe.db.set_single_value("Webshop Settings", "return_days", 0)
		frappe.db.set_single_value("Webshop Settings", "promise_note", "")
		frappe.clear_cache(doctype="Webshop Settings")
		self.assertEqual(self._context(doc).promises, [])

		frappe.db.set_single_value("Webshop Settings", "return_days", 14)
		frappe.db.set_single_value("Webshop Settings", "delivery_delay", "48 h")
		frappe.clear_cache(doctype="Webshop Settings")
		lines = self._context(doc).promises
		self.assertEqual([line["key"] for line in lines], ["delay", "returns"])
		self.assertIn("48 h", lines[0]["text"])
		self.assertIn("14", lines[1]["text"])

	def test_brand_info_only_when_the_brand_has_something_to_say(self):
		doc = self._published_item()
		context = self._context(doc)
		if not doc.brand:
			self.assertIsNone(context.brand_info)
			return
		brand = frappe.get_cached_value("Brand", doc.brand, ["description", "image"], as_dict=True)
		if frappe.utils.strip_html(brand.description or "").strip() or brand.image:
			self.assertEqual(context.brand_info.name, doc.brand)
		else:
			self.assertIsNone(context.brand_info)

	def test_the_heading_stays_the_product_name(self):
		doc = self._published_item()
		context = self._context(doc)
		self.assertEqual(context.title, doc.web_item_name)
		self.assertNotIn(" | ", context.title)
