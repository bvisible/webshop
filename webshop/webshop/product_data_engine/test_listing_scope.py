# //// Neoffice — added file (no upstream equivalent). neoffice-maintenance#737.
"""One scope per listing. Every query path of the grid (relevance, price, newest, the discount
tick) lists the same products, and every facet of the sidebar counts what a tick on it lists.

Each SQL path used to render its own share of the filters, and each facet its own copy of the
scope. Measured on osiris on 2026-09-24: a category of 12 products sorted by price listed the
whole catalogue (306), and a two-word search too; ticked "discounted", a category listed every
discounted product of the shop; a brand's page offered the catalogue's 23 categories, each
counted over the whole shop; the brand facet counted the variants the grid hides."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import nowdate

from webshop.webshop.product_data_engine.filters import ProductFiltersBuilder
from webshop.webshop.product_data_engine.query import ProductQuery, count_discounted_items
from webshop.webshop.tests.utils import (
	default_company,
	ensure_shop_settings,
	restore_webshop_settings,
	root_item_group,
	selling_price_list,
	snapshot_webshop_settings,
)

PREFIX = "_WSTEST Scope"
PARENT, CHILD_A, CHILD_B, ELSEWHERE = (f"{PREFIX} {name}" for name in ("Parent", "Child A", "Child B", "Elsewhere"))
ONE, TWO = f"{PREFIX} Brand One", f"{PREFIX} Brand Two"
SIZE = f"{PREFIX} Size"
SORTS = ("relevance", "price_low_to_high", "price_high_to_low", "new_arrivals")
SECOND_HAND = ["Second-hand", "Refurbished"]

# code: (group, brand, condition, rate). The lanterns are what the searches find.
ITEMS = {
	f"{PREFIX} Lantern": (CHILD_A, ONE, "New", 10),
	f"{PREFIX} Lantern Used": (CHILD_A, TWO, "Second-hand", 20),
	f"{PREFIX} Kettle": (CHILD_B, ONE, "New", 30),
	f"{PREFIX} Lantern Far": (ELSEWHERE, ONE, "New", 40),
}
LANTERN, USED, KETTLE, FAR = ITEMS
TEMPLATE = f"{PREFIX} Tent"


def no_display_details(self, result, discount_list, cart_items):
	"""The tiles' prices are not what this module is about, and on stock ERPNext (the CI)
	get_product_info_for_website passes a keyword only the fleet's fork knows."""
	return result, discount_list


def purge():
	for doctype, filters in (
		("Pricing Rule", {"title": ("like", f"{PREFIX}%")}),
		("Item Price", {"item_code": ("like", f"{PREFIX}%")}),
		("Website Item", {"item_code": ("like", f"{PREFIX}%")}),
		("Item", {"variant_of": ("like", f"{PREFIX}%")}),
		("Item", {"item_code": ("like", f"{PREFIX}%")}),
		("Item Attribute", {"name": SIZE}),
		("Brand", {"name": ("like", f"{PREFIX}%")}),
		("Item Group", {"name": ("in", [CHILD_A, CHILD_B, ELSEWHERE])}),
		("Item Group", {"name": PARENT}),
	):
		for name in frappe.get_all(doctype, filters=filters, pluck="name"):
			frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
	# the fixtures live across the tests and leave with the class (CLAUDE.md, "Fixtures built in
	# setUpClass need a commit")
	frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit


class TestWhereConditions(FrappeTestCase):
	"""The one rendering of a listing's conditions (ProductQuery.where_conditions)."""

	def test_every_or_group_is_one_alternative_and_the_groups_are_anded(self):
		query = ProductQuery()
		query.filters = [["published", "=", 1]]
		query.or_groups = [
			[["item_group", "in", ["A", "B"]], ["name", "in", ["X"]]],
			[["_user_tags", "like", "%red%"], ["_user_tags", "like", "%blue%"]],
		]
		conditions, values = query.where_conditions()
		self.assertEqual(
			conditions,
			[
				"wi.`published` = %s",
				"(wi.`item_group` IN (%s, %s) OR wi.`name` IN (%s))",
				"(wi.`_user_tags` LIKE %s OR wi.`_user_tags` LIKE %s)",
			],
		)
		self.assertEqual(values, [1, "A", "B", "X", "%red%", "%blue%"])

	def test_every_word_of_a_search_must_be_found_in_one_of_the_fields(self):
		query = ProductQuery()
		query.build_search_filters("Chaise  Pliante")
		self.assertEqual(query._search_words, ["chaise", "pliante"])
		self.assertIn("item_name", query._search_fields)
		query.filters = []
		conditions, values = query.where_conditions("x.")
		self.assertEqual(len(conditions), 2)
		for condition in conditions:
			self.assertTrue(condition.startswith("(LOWER(x.`") and condition.endswith("LIKE %s)"))
		fields = len(query._search_fields)
		self.assertEqual(values, ["%chaise%"] * fields + ["%pliante%"] * fields)

	def test_empty_lists_and_unset_values_read_as_the_orm_reads_them(self):
		query = ProductQuery()
		query.filters = [
			["item_code", "in", []],
			["name", "not in", []],
			["variant_of", "is", "not set"],
			["brand", "is", "set"],
		]
		conditions, values = query.where_conditions()
		self.assertEqual(
			conditions, ["1=0", "IFNULL(wi.`variant_of`, '') = ''", "IFNULL(wi.`brand`, '') != ''"]
		)
		self.assertEqual(values, [])

	def test_a_key_that_is_no_column_is_never_rendered(self):
		query = ProductQuery()
		query.filters = [["published", "=", 1], ["no_such_column", "=", 1], ["doctype", "=", "x"]]
		conditions, _values = query.where_conditions()
		self.assertEqual(conditions, ["wi.`published` = %s"])
		query.build_fields_filters({"no_such_column": ["x"]})
		self.assertEqual(query.where_conditions()[0], ["wi.`published` = %s"])

	def test_a_table_multiselect_filter_reads_its_child_table(self):
		query = ProductQuery()
		query.filters = [["Website Item Group", "item_group", "IN", ["A"]]]
		conditions, values = query.where_conditions()
		self.assertEqual(
			conditions, ["wi.`name` IN (SELECT parent FROM `tabWebsite Item Group` WHERE `item_group` IN (%s))"]
		)
		self.assertEqual(values, ["A"])


class TestOneScope(FrappeTestCase):
	"""A small catalogue: a parent category with two children and a group elsewhere, two brands,
	a used unit, a discounted lantern, a template with two variants."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		purge()
		cls.written = ensure_shop_settings()
		cls.settings = snapshot_webshop_settings(["hide_variants", "enable_price_filter", "enable_attribute_filters"])
		frappe.db.set_single_value(
			"Webshop Settings", {"hide_variants": 1, "enable_price_filter": 1, "enable_attribute_filters": 0}
		)
		price_list = selling_price_list()
		uom = frappe.db.get_value("UOM", {}, "name")

		for name, parent, is_group in (
			(PARENT, root_item_group(), 1),
			(CHILD_A, PARENT, 0),
			(CHILD_B, PARENT, 0),
			(ELSEWHERE, root_item_group(), 0),
		):
			frappe.get_doc(
				{
					"doctype": "Item Group",
					"item_group_name": name,
					"parent_item_group": parent,
					"is_group": is_group,
					"show_in_website": 1,
				}
			).insert(ignore_permissions=True)
		for brand in (ONE, TWO):
			frappe.get_doc({"doctype": "Brand", "brand": brand}).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Item Attribute",
				"attribute_name": SIZE,
				"item_attribute_values": [
					{"attribute_value": "S", "abbr": "S"},
					{"attribute_value": "M", "abbr": "M"},
				],
			}
		).insert(ignore_permissions=True)

		def item(code, group, brand, **extra):
			return frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": code,
					"item_name": code,
					"item_group": group,
					"brand": brand,
					"stock_uom": uom,
					"is_stock_item": 0,
					**extra,
				}
			).insert(ignore_permissions=True)

		def publish(code, group, brand, condition="New"):
			web_item = frappe.get_doc(
				{
					"doctype": "Website Item",
					"item_code": code,
					"web_item_name": code,
					"item_group": group,
					"published": 1,
					"route": "products/" + frappe.scrub(code).replace("_", "-"),
				}
			).insert(ignore_permissions=True)
			# written straight: a used unit without stock is "sold" on save, and what the page
			# shows is read off the Website Item
			frappe.db.set_value(
				"Website Item", web_item.name, {"brand": brand, "item_condition": condition, "sold": 0}
			)

		def price(code, rate):
			frappe.get_doc(
				{"doctype": "Item Price", "item_code": code, "price_list": price_list, "price_list_rate": rate}
			).insert(ignore_permissions=True)

		for code, (group, brand, condition, rate) in ITEMS.items():
			item(code, group, brand)
			publish(code, group, brand, condition)
			price(code, rate)

		from erpnext.controllers.item_variant import create_variant

		item(TEMPLATE, CHILD_B, TWO, has_variants=1, variant_based_on="Item Attribute", attributes=[{"attribute": SIZE}])
		publish(TEMPLATE, CHILD_B, TWO)
		cls.variants = []
		for size, rate in (("S", 50), ("M", 60)):
			variant = create_variant(TEMPLATE, {SIZE: size})
			variant.insert(ignore_permissions=True)
			cls.variants.append(variant.name)
			publish(variant.name, CHILD_B, TWO)
			price(variant.name, rate)

		frappe.get_doc(
			{
				"doctype": "Pricing Rule",
				"title": f"{PREFIX} Lantern discount",
				"apply_on": "Item Code",
				"items": [{"item_code": LANTERN}],
				"selling": 1,
				"rate_or_discount": "Discount Percentage",
				"discount_percentage": 10,
				"company": default_company(),
				"valid_from": nowdate(),
				"price_or_product_discount": "Price",
			}
		).insert(ignore_permissions=True)
		# a test's rollback would take the class's fixtures with it (see purge)
		frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit

	@classmethod
	def tearDownClass(cls):
		purge()
		restore_webshop_settings({**cls.settings, **cls.written})
		super().tearDownClass()

	def setUp(self):
		patcher = patch.object(ProductQuery, "add_display_details", no_display_details)
		patcher.start()
		self.addCleanup(patcher.stop)

	def listing(self, fields=None, search=None, item_group=None, sort_order="relevance"):
		engine = ProductQuery()
		engine.page_length = 1000
		result = engine.query(
			{}, dict(fields or {}), search_term=search, start=0, item_group=item_group, sort_order=sort_order
		)
		codes = [row["item_code"] for row in result["items"]]
		self.assertEqual(result["total_count"], len(codes), "the count and the page disagree")
		return set(codes)

	def ours(self, codes):
		return {code for code in codes if code.startswith(PREFIX)}

	def test_every_sort_order_lists_the_same_products(self):
		discount = {"discount": ["100"]}
		cases = [
			("a category and its sub-categories", {}, None, PARENT, {LANTERN, USED, KETTLE, TEMPLATE}),
			("a sub-category", {}, None, CHILD_A, {LANTERN, USED}),
			("a one-word search", {}, "lantern", None, {LANTERN, USED, FAR}),
			("a two-word search", {}, "scope lantern", None, {LANTERN, USED, FAR}),
			("a search inside a category", {}, "lantern", PARENT, {LANTERN, USED}),
			("a two-word search inside a category", {}, "scope lantern", PARENT, {LANTERN, USED}),
			("the discount tick", discount, None, None, {LANTERN}),
			("the discount tick in a category", discount, None, PARENT, {LANTERN}),
			("the discount tick where nothing is discounted", discount, None, ELSEWHERE, set()),
			("the discount tick under a search", discount, "kettle", None, set()),
			("a locked brand", {"brand": [ONE]}, None, None, {LANTERN, KETTLE, FAR}),
			("a locked condition", {"item_condition": SECOND_HAND}, None, None, {USED}),
			("the second-hand toggle in a category", {"second_hand": ["1"]}, None, PARENT, {USED}),
		]
		for label, fields, search, group, expected in cases:
			with self.subTest(label):
				first = self.listing(fields, search, group)
				self.assertEqual(self.ours(first), expected)
				for sort_order in SORTS[1:]:
					self.assertEqual(self.listing(fields, search, group, sort_order), first, sort_order)

	def facets(self, builder):
		builder.doc = frappe._dict(
			enable_field_filters=1,
			filter_fields=[frappe._dict(fieldname=f) for f in ("item_group", "brand", "item_condition")],
		)
		out = {}
		for df, values in builder.get_field_filters() or []:
			if df.fieldname == "item_group":
				pairs, stack = [], list(values)
				while stack:
					node = stack.pop()
					pairs.append((node["name"], node["count"]))
					stack.extend(node.get("children") or [])
			elif df.fieldname == "brand":
				pairs = [(value["name"], value["count"]) for value in values]
			else:
				pairs = [(value, None) for value in values]
			out[df.fieldname] = pairs
		return out

	def assert_each_tick_lists_its_count(self, facets, locked, group=None):
		for fieldname, pairs in facets.items():
			for value, count in pairs:
				listed = self.listing({**locked, fieldname: [value]}, None, group)
				if count is None:
					self.assertTrue(listed, f"{fieldname} {value} is offered and lists nothing")
				else:
					self.assertEqual(len(listed), count, f"{fieldname} {value}")

	def test_a_locked_brand_counts_inside_the_brand(self):
		facets = self.facets(ProductFiltersBuilder(locked_field_filters={"brand": [ONE]}))
		self.assertNotIn("brand", facets, "a locked facet is not offered")
		groups = dict(facets["item_group"])
		self.assertEqual((groups[PARENT], groups[CHILD_A], groups[CHILD_B], groups[ELSEWHERE]), (2, 1, 1, 1))
		self.assert_each_tick_lists_its_count(facets, {"brand": [ONE]})

	def test_a_locked_condition_counts_inside_the_condition(self):
		facets = self.facets(ProductFiltersBuilder(locked_field_filters={"item_condition": SECOND_HAND}))
		self.assertNotIn("item_condition", facets)
		self.assertEqual(dict(facets["brand"]).get(TWO), 1)
		self.assertNotIn(ONE, dict(facets["brand"]), "a brand with no used unit is not offered")
		self.assert_each_tick_lists_its_count(facets, {"item_condition": SECOND_HAND})

	def test_a_category_counts_its_sub_categories_and_hidden_variants_stay_out(self):
		for hide_variants in (1, 0):
			with self.subTest(hide_variants=hide_variants):
				frappe.db.set_single_value("Webshop Settings", "hide_variants", hide_variants)
				facets = self.facets(ProductFiltersBuilder(item_group=PARENT))
				brands = dict(facets["brand"])
				# the used lantern and the tent, plus the tent's two sizes when they are shown
				self.assertEqual(brands[TWO], 2 if hide_variants else 4)
				self.assertEqual(brands[ONE], 2)
				self.assertEqual(dict(facets["item_group"])[CHILD_B], 2 if hide_variants else 4)
				self.assert_each_tick_lists_its_count(facets, {}, PARENT)
		frappe.db.set_single_value("Webshop Settings", "hide_variants", 1)

	def test_the_price_slider_reads_the_locks_and_the_ticks(self):
		self.assertEqual(
			ProductFiltersBuilder(locked_field_filters={"brand": [ONE]}).get_price_filters()[0],
			{"min_value": 10, "max_value": 40},
		)
		used_of_brand_two = {"second_hand": ["1"], "brand": [TWO]}
		self.assertEqual(
			ProductFiltersBuilder().get_price_filters(used_of_brand_two)[0], {"min_value": 20, "max_value": 20}
		)
		self.assertEqual(
			ProductFiltersBuilder(locked_field_filters={"item_condition": SECOND_HAND}).get_price_filters(
				{"brand": [TWO]}
			)[0],
			{"min_value": 20, "max_value": 20},
		)

	def test_the_toggle_counts_read_the_scope(self):
		from webshop.webshop.product_data_engine.listing_context import (
			clear_discount_count,
			count_discounted,
			count_second_hand,
		)

		self.assertEqual(count_second_hand({"brand": [TWO]}), 1)
		self.assertEqual(count_second_hand({"brand": [ONE]}), 0)
		self.assertEqual(count_second_hand(item_group=PARENT), 1)
		self.assertEqual(count_second_hand(item_group=ELSEWHERE), 0)
		self.assertEqual(count_discounted_items(item_group=PARENT), 1)
		self.assertEqual(count_discounted_items(item_group=ELSEWHERE), 0)
		self.assertEqual(count_discounted_items(locked_field_filters={"brand": [TWO]}), 0)
		clear_discount_count()
		self.addCleanup(clear_discount_count)
		# one cached figure per listing, never another listing's
		self.assertEqual(count_discounted(item_group=PARENT), 1)
		self.assertEqual(count_discounted(item_group=ELSEWHERE), 0)
		self.assertEqual(count_discounted(locked_field_filters={"brand": [ONE]}), 1)
