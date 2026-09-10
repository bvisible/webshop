# //// Neoffice — added file (no upstream equivalent).
"""What /shop-by-category makes of the shop's filter fields.

The page died in production because one filter field was of a type its controller
had never met: it read a **Select** field's options as a doctype name, and the
`frappe.get_meta("New\\nRefurbished\\nSecond-hand")` that followed raised outside
the only try/except in the function. A website page that raises answers 403, so
the whole page read "Non autorisé" to every visitor — signed in or not — on any
shop whose filters included the Condition field the second-hand feature adds.

Nothing caught it because nothing tested the page: `get_category_records` was only
ever exercised through a browser, on shops configured with Link fields.

So what is asserted here is the shape of what the page builds, per field type, and
above all that a filter field the controller cannot make sense of costs its own
tab and not the page.
"""

import importlib.util
import json
import os
from urllib.parse import unquote

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.tests.utils import leaf_item_group, make_test_item

ITEM = "_WSTEST SBC second-hand"


def _controller():
	"""The page's controller, loaded by path.

	`www/shop-by-category` is not an importable package name — the hyphen makes it
	a route, not an identifier — so the framework loads it by path and so does this.
	`get_app_path` scrubs the segments it is handed (it would look for
	`shop_by_category`), hence the plain join.
	"""
	path = os.path.join(frappe.get_app_path("webshop"), "www", "shop-by-category", "index.py")
	spec = importlib.util.spec_from_file_location("webshop_shop_by_category", path)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


class TestShopByCategory(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.controller = _controller()
		cls.has_condition = frappe.get_meta("Website Item", cached=True).has_field("item_condition")
		cls.web_item = None
		if cls.has_condition:
			# A published item carrying a Select value, so the facet has something to show.
			item = make_test_item(ITEM, is_stock_item=0)
			cls.web_item = frappe.db.get_value("Website Item", {"item_code": item.name}, "name")
			if not cls.web_item:
				doc = frappe.get_doc(
					{
						"doctype": "Website Item",
						"item_code": item.name,
						"web_item_name": ITEM,
						"item_group": leaf_item_group(),
						"published": 1,
					}
				)
				doc.flags.ignore_permissions = True
				doc.insert()
				cls.web_item = doc.name
			frappe.db.set_value(
				"Website Item", cls.web_item, {"published": 1, "item_condition": "Second-hand"}
			)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		if cls.web_item:
			frappe.delete_doc_if_exists("Website Item", cls.web_item, force=True)
			frappe.delete_doc_if_exists("Item", ITEM, force=True)
			frappe.db.commit()
		super().tearDownClass()

	def records(self, categories):
		return self.controller.get_category_records(categories)

	# --- the type that broke the page ------------------------------------------------

	def test_a_select_filter_field_no_longer_takes_the_page_down(self):
		"""Its options are values, not a doctype: reading them as one raised, and a
		website page that raises answers 403 to everybody."""
		if not self.has_condition:
			self.skipTest("this site has no item_condition field on Website Item")
		self.assertIn("item_condition", self.records(["item_condition"]))

	def test_a_select_card_offers_only_a_value_the_shop_actually_sells(self):
		if not self.has_condition:
			self.skipTest("this site has no item_condition field on Website Item")
		values = {row.value for row in self.records(["item_condition"])["item_condition"]}
		self.assertIn("Second-hand", values)
		# A value no published item carries gets no card: it would lead to an empty
		# catalogue. Nothing here publishes a refurbished unit.
		refurbished = frappe.db.count(
			"Website Item", {"published": 1, "item_condition": "Refurbished"}
		)
		if not refurbished:
			self.assertNotIn("Refurbished", values)

	def test_a_select_card_links_to_the_catalogue_filtered_on_its_own_value(self):
		if not self.has_condition:
			self.skipTest("this site has no item_condition field on Website Item")
		rows = self.records(["item_condition"])["item_condition"]
		card = next(row for row in rows if row.value == "Second-hand")
		route, _sep, query = card.route.partition("?field_filters=")
		self.assertEqual(route, "/all-products")
		self.assertEqual(json.loads(unquote(query)), {"item_condition": ["Second-hand"]})
		# the card reads in the visitor's language, the link carries what is stored
		self.assertEqual(card.name, frappe._("Second-hand"))

	def test_a_field_offering_no_choice_gets_no_tab_at_all(self):
		"""The sidebar's rule, which this page now shares: a "Condition" tab holding the
		single card "New" told the visitor nothing, on a shop that has never sold
		anything else — while the sidebar right beside it showed no Condition facet."""
		from webshop.webshop.product_data_engine.filters import select_facet_is_useful

		self.assertFalse(select_facet_is_useful("item_condition", ["New"]))
		self.assertFalse(select_facet_is_useful("item_condition", ["New", None]))
		self.assertTrue(select_facet_is_useful("item_condition", ["New", "Second-hand"]))
		# any other Select field: one published value is still something to filter on
		self.assertTrue(select_facet_is_useful("_wstest_other_select", ["A"]))
		self.assertFalse(select_facet_is_useful("_wstest_other_select", [None, ""]))

	# --- and every other type still answers what it used to ---------------------------

	def test_item_group_still_comes_back(self):
		data = self.records(["item_group"])
		self.assertIn("item_group", data)
		for row in data["item_group"]:
			self.assertTrue(row.name)

	def test_a_link_filter_field_still_lists_records_of_its_doctype(self):
		data = self.records(["brand"])
		self.assertIn("brand", data)
		known = set(frappe.get_all("Brand", pluck="name"))
		self.assertTrue({row.name for row in data["brand"]} <= known)

	# --- a misconfigured filter costs its tab, not the page ---------------------------

	def test_a_filter_field_absent_from_website_item_is_skipped(self):
		"""A field removed from Website Item, or a stale row left in the settings."""
		self.assertEqual(self.records(["_wstest_no_such_field"]), {})

	def test_one_broken_field_does_not_take_the_others_with_it(self):
		data = self.records(["_wstest_no_such_field", "item_group", "brand"])
		self.assertIn("item_group", data)
		self.assertIn("brand", data)

