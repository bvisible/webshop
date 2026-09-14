# //// Neoffice — added file (no upstream equivalent).
"""The product page's context: the promises it prints and the brand it introduces."""

import json
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.doctype.website_item.test_website_item import create_regular_web_item
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
		if name:
			return frappe.get_doc("Website Item", name)
		# The per-push CI runs on a fresh site with no published item: make one, so these
		# tests run on every push and not only in the nightly suite (#399).
		return create_regular_web_item(web_args={"published": 1})

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

	def test_the_breadcrumb_json_ld_steps_aside_for_the_chrome(self):
		"""A site chrome that draws the trail in its own page header sets `no_breadcrumbs` and
		writes its own BreadcrumbList. The visible breadcrumb already stepped aside; the JSON-LD
		did not, and a product page carried two (2026-09-14)."""
		source = (Path(__file__).resolve().parents[2] / "templates" / "generators" / "item" / "item.html").read_text()
		start = source.index("{%- if not no_breadcrumbs %}")
		end = source.index("{%- endif %}", start) + len("{%- endif %}")
		snippet = source[start:end]
		self.assertIn('"BreadcrumbList"', snippet)
		doc = frappe._dict(web_item_name="Trail shoe", route="products/trail-shoe")
		parents = [{"route": "/", "label": "Home"}, {"route": "/all-products", "label": "Shop"}]
		self.assertEqual(frappe.render_template(snippet, {"no_breadcrumbs": 1, "parents": parents, "doc": doc}).strip(), "")
		html = frappe.render_template(snippet, {"no_breadcrumbs": 0, "parents": parents, "doc": doc})
		data = json.loads(html.split(">", 1)[1].rsplit("</script>", 1)[0])
		self.assertEqual([element["position"] for element in data["itemListElement"]], [1, 2, 3])
		self.assertEqual(data["itemListElement"][-1]["name"], "Trail shoe")

	def test_the_product_heading_yields_the_h1_to_the_band(self):
		"""A site chrome whose page header prints the page's title as the h1 sets
		`band_prints_title`; the product's own heading, hidden then, must not be a second h1
		(2026-09-14)."""
		source = (Path(__file__).resolve().parents[2] / "templates" / "generators" / "item" / "item.html").read_text()
		start = source.index("{%- set _title_tag")
		end = source.index("</{{ _title_tag }}>", start) + len("</{{ _title_tag }}>")
		snippet = source[start:end]
		doc = frappe._dict(web_item_name="Trail shoe")
		under_the_band = frappe.render_template(snippet, {"band_prints_title": 1, "doc": doc}).strip()
		self.assertTrue(under_the_band.startswith('<div class="product-title-main" itemprop="name">'), under_the_band)
		on_its_own = frappe.render_template(snippet, {"doc": doc}).strip()
		self.assertTrue(on_its_own.startswith('<h1 class="product-title-main" itemprop="name">'), on_its_own)
		self.assertTrue(on_its_own.endswith("</h1>"), on_its_own)

