# //// Neoffice — added file (no upstream equivalent). neoffice-maintenance#3337.
"""Attribute filters on a shop that lists MODELS: one card per model, its sizes and colours on variants that have no card.

Upstream's facet read the attribute rows of the listed items themselves, which on such a shop are the models' own and
hold no value: switched on, the facet offered nothing (or a stray value) and a tick found nothing. Now the facet offers
the values of the live variants of the listed models, and a tick lists the models that have a live variant carrying
every ticked value, in the same variant. Where the shop shows only what is in stock, that variant must be one a visitor
can buy. The category, the brand and any field filter keep working beside it, and a shop that switches nothing on lists
what it listed.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.product_data_engine import model_attributes
from webshop.webshop.product_data_engine.filters import ProductFiltersBuilder
from webshop.webshop.product_data_engine.query import ProductQuery
from webshop.webshop.tests.utils import (
	default_company,
	leaf_item_group,
	restore_webshop_settings,
	root_item_group,
	snapshot_webshop_settings,
)

PREFIX = "_WSTEST Models"
SIZE, COLOUR = f"{PREFIX} Size", f"{PREFIX} Colour"
TOPS, COATS, BOOTS = f"{PREFIX} Tops", f"{PREFIX} Coats", f"{PREFIX} Boots"
ONE, TWO = f"{PREFIX} Brand One", f"{PREFIX} Brand Two"
GENDER_FIELD = "wstest_gender"
GROUP_WAREHOUSE, CHILD_WAREHOUSE = f"{PREFIX} Group", f"{PREFIX} Child"

SHIRT, COAT, PARKA, TENT = (f"{PREFIX} {name}" for name in ("Shirt", "Coat", "Parka", "Tent"))
BOOT, SANDAL, CLOG, GROUPY = (f"{PREFIX} {name}" for name in ("Boot", "Sandal", "Clog", "Groupy"))

# model: (item group, brand, gender, published, [(size, colour, disabled)])
MODELS = {
	SHIRT: (TOPS, ONE, "Women", 1, [("S", "Red", 0), ("S", "Blue", 0), ("M", "Red", 0)]),
	COAT: (COATS, TWO, "Men", 1, [("L", "Blue", 0), ("XL", "Red", 0), ("XS", "Green", 1)]),
	PARKA: (COATS, TWO, "Men", 0, [("XXL", "Blue", 0)]),
}
# the models the stock reads: variants are stock items, the model is not (a shop lists the model only).
# model: (variant size, stock, reserved)
STOCKED = {
	BOOT: [("M", 5, 0), ("L", 0, 0), ("XL", 3, 3)],
	GROUPY: [("M", 2, 0)],
	SANDAL: [("S", 0, 0)],
	CLOG: [("S", 0, 0)],
}


def no_display_details(self, result, discount_list, cart_items):
	"""The tiles' prices are not what this module is about."""
	return result, discount_list


def purge():
	frappe.db.delete("Bin", {"item_code": ("like", f"{PREFIX}%")})
	for doctype, filters in (
		("Website Item", {"item_code": ("like", f"{PREFIX}%")}),
		("Item", {"variant_of": ("like", f"{PREFIX}%")}),
		("Item", {"item_code": ("like", f"{PREFIX}%")}),
		("Item Attribute", {"name": ("in", [SIZE, COLOUR])}),
		("Brand", {"name": ("like", f"{PREFIX}%")}),
		("Item Group", {"name": ("in", [TOPS, COATS, BOOTS])}),
		("Warehouse", {"name": ("like", f"{PREFIX} Child%")}),
		("Warehouse", {"name": ("like", f"{PREFIX} Group%")}),
		("Custom Field", {"name": f"Website Item-{GENDER_FIELD}"}),
	):
		for name in frappe.get_all(doctype, filters=filters, pluck="name"):
			frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
	# the fixtures live across the tests and leave with the class (CLAUDE.md, "Fixtures built in setUpClass need a commit")
	frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit


class TestAttributeFiltersOnModels(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		purge()
		cls.settings = snapshot_webshop_settings(["hide_variants", "enable_attribute_filters", "enable_field_filters"])
		frappe.db.set_single_value("Webshop Settings", {"hide_variants": 0})

		from frappe.custom.doctype.custom_field.custom_field import create_custom_field
		from erpnext.controllers.item_variant import create_variant
		from erpnext.stock.utils import get_or_make_bin

		create_custom_field(
			"Website Item",
			dict(
				owner="Administrator",
				fieldname=GENDER_FIELD,
				label="Gender of the test",
				fieldtype="Select",
				options="\nMen\nWomen\nJunior",
				insert_after="item_group",
			),
		)
		frappe.clear_cache(doctype="Website Item")

		company, uom = default_company(), frappe.db.get_value("UOM", {}, "name")
		for name in (TOPS, COATS, BOOTS):
			frappe.get_doc(
				{
					"doctype": "Item Group",
					"item_group_name": name,
					"parent_item_group": root_item_group(),
					"is_group": 0,
					"show_in_website": 1,
				}
			).insert(ignore_permissions=True)
		for brand in (ONE, TWO):
			frappe.get_doc({"doctype": "Brand", "brand": brand}).insert(ignore_permissions=True)
		for attribute, values in (
			(SIZE, ("S", "M", "L", "XL", "XXL", "XS")),
			(COLOUR, ("Red", "Blue", "Green")),
		):
			frappe.get_doc(
				{
					"doctype": "Item Attribute",
					"attribute_name": attribute,
					"item_attribute_values": [{"attribute_value": v, "abbr": v[:3].upper()} for v in values],
				}
			).insert(ignore_permissions=True)

		group = frappe.get_doc(
			{"doctype": "Warehouse", "warehouse_name": GROUP_WAREHOUSE, "company": company, "is_group": 1}
		).insert(ignore_permissions=True)
		child = frappe.get_doc(
			{
				"doctype": "Warehouse",
				"warehouse_name": CHILD_WAREHOUSE,
				"company": company,
				"parent_warehouse": group.name,
			}
		).insert(ignore_permissions=True)
		cls.group_warehouse, cls.child_warehouse = group.name, child.name

		def model(code, item_group, brand, gender, published, warehouse=None, attributes=(SIZE, COLOUR), **card):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": code,
					"item_name": code,
					"item_group": item_group or leaf_item_group(),
					"brand": brand,
					"stock_uom": uom,
					"is_stock_item": 0,
					"has_variants": 1,
					"variant_based_on": "Item Attribute",
					"attributes": [{"attribute": attribute} for attribute in attributes],
				}
			).insert(ignore_permissions=True)
			web_item = frappe.get_doc(
				{
					"doctype": "Website Item",
					"item_code": code,
					"web_item_name": code,
					"item_group": item_group or leaf_item_group(),
					"published": published,
					"website_warehouse": warehouse,
					"route": "products/" + frappe.scrub(code).replace("_", "-"),
				}
			).insert(ignore_permissions=True)
			# written straight: the card of a model is what the listing reads
			frappe.db.set_value(
				"Website Item",
				web_item.name,
				{"brand": brand, GENDER_FIELD: gender, "sold": 0, **card},
			)

		def variant(code, size, colour_or_none, disabled=0, stock_item=0):
			args = {SIZE: size}
			if colour_or_none:
				args[COLOUR] = colour_or_none
			made = create_variant(code, args)
			made.insert(ignore_permissions=True)
			frappe.db.set_value("Item", made.name, {"disabled": disabled, "is_stock_item": stock_item})
			return made.name

		for code, (item_group, brand, gender, published, variants) in MODELS.items():
			model(code, item_group, brand, gender, published)
			for size, colour, disabled in variants:
				variant(code, size, colour, disabled)

		# the models the stock reads: BOOT in a leaf warehouse, GROUPY in a group whose child holds the stock, SANDAL on
		# backorder, CLOG with no shop warehouse at all
		only_sizes = {"attributes": (SIZE,)}
		model(BOOT, BOOTS, ONE, "Men", 1, warehouse=cls.child_warehouse, **only_sizes)
		model(GROUPY, BOOTS, ONE, "Men", 1, warehouse=cls.group_warehouse, **only_sizes)
		model(SANDAL, BOOTS, ONE, "Men", 1, warehouse=cls.child_warehouse, on_backorder=1, **only_sizes)
		model(CLOG, BOOTS, ONE, "Men", 1, warehouse=None, **only_sizes)
		for code, rows in STOCKED.items():
			for size, qty, reserved in rows:
				name = variant(code, size, None, stock_item=1)
				bin_name = get_or_make_bin(name, cls.child_warehouse)
				frappe.db.set_value("Bin", bin_name, {"actual_qty": qty, "reserved_qty": reserved})

		# a shop that carries its models AND some of its variants: the tent's S has no card, its M has one of its own
		model(TENT, BOOTS, TWO, "Men", 1, **only_sizes)
		variant(TENT, "S", None)
		cls.tent_m = variant(TENT, "M", None)
		own_card = frappe.get_doc(
			{
				"doctype": "Website Item",
				"item_code": cls.tent_m,
				"web_item_name": cls.tent_m,
				"item_group": BOOTS,
				"published": 1,
				"route": "products/" + frappe.scrub(cls.tent_m).replace("_", "-"),
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Website Item", own_card.name, {"brand": TWO, GENDER_FIELD: "Men", "sold": 0})
		# what publishing a variant from the desk does: the direct lookup reads it off the item
		frappe.db.set_value("Item", cls.tent_m, "published_in_website", 1)

		# a test's rollback would take the class's fixtures with it (see purge)
		frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit

	@classmethod
	def tearDownClass(cls):
		purge()
		restore_webshop_settings(cls.settings)
		frappe.clear_cache(doctype="Website Item")
		super().tearDownClass()

	def setUp(self):
		patcher = patch.object(ProductQuery, "add_display_details", no_display_details)
		patcher.start()
		self.addCleanup(patcher.stop)

	# ---- what a visitor does ----
	def listing(self, attributes=None, fields=None, hide_variants=0):
		engine = ProductQuery()
		engine.settings.hide_variants = hide_variants
		engine.page_length = 1000
		result = engine.query(
			dict(attributes or {}), dict(fields or {}), search_term=None, start=0, item_group=None
		)
		codes = [row["item_code"] for row in result["items"]]
		self.assertEqual(result["total_count"], len(codes), "the count and the page disagree")
		return {code for code in codes if code.startswith(PREFIX)}

	def facets(self, item_group=None, **doc):
		builder = ProductFiltersBuilder(item_group=item_group)
		builder.doc = frappe._dict(
			{
				"enable_attribute_filters": 1,
				"hide_variants": 0,
				"filter_attributes": [frappe._dict(attribute=SIZE), frappe._dict(attribute=COLOUR)],
				**doc,
			}
		)
		return {facet.name: facet.item_attribute_values for facet in builder.get_attribute_filters() or []}

	def in_stock_rule(self, on=True):
		patcher = patch.object(model_attributes, "shows_only_what_is_in_stock", return_value=on)
		patcher.start()
		self.addCleanup(patcher.stop)

	# ---- the facet ----
	def test_the_facet_offers_the_values_of_the_live_variants_of_the_listed_models(self):
		facets = self.facets(item_group=TOPS)
		# the shirts' variants only: S and M, Red and Blue, in the order of their attributes (neoffice-maintenance#3344)
		self.assertEqual(facets[SIZE], ["S", "M"])
		self.assertEqual(facets[COLOUR], ["Red", "Blue"])

		facets = self.facets(item_group=COATS)
		# L and XL, Blue and Red; not XXL (the parka's card is unpublished), not XS nor Green (a disabled variant)
		self.assertEqual(facets[SIZE], ["L", "XL"])
		self.assertEqual(facets[COLOUR], ["Red", "Blue"])

	def test_the_facet_of_the_whole_shop_offers_every_listed_model_once(self):
		facets = self.facets()
		for value in ("S", "M", "L", "XL"):
			self.assertEqual(facets[SIZE].count(value), 1, value)
		for absent in ("XXL", "XS"):
			self.assertNotIn(absent, facets[SIZE])
		self.assertNotIn("Green", facets[COLOUR])

	def test_a_models_own_row_is_not_a_value_a_visitor_can_buy(self):
		own = frappe.db.get_value("Item Variant Attribute", {"parent": SHIRT, "attribute": SIZE}, "name")
		frappe.db.set_value("Item Variant Attribute", own, "attribute_value", "XXL")
		self.addCleanup(frappe.db.set_value, "Item Variant Attribute", own, "attribute_value", None)
		self.assertNotIn("XXL", self.facets(item_group=TOPS)[SIZE])

	def test_a_shop_that_hides_its_variants_keeps_the_exclusion(self):
		# Webshop Settings refuses attribute facets there; were the facet asked anyway it reads nothing of the variants
		self.assertEqual(self.facets(item_group=TOPS, hide_variants=1), {})
		self.assertEqual(self.listing({SIZE: ["M"]}, hide_variants=1), set())

	def test_a_shop_with_attribute_filters_off_has_no_attribute_facet(self):
		builder = ProductFiltersBuilder()
		builder.doc = frappe._dict({"enable_attribute_filters": 0, "hide_variants": 0})
		self.assertIsNone(builder.get_attribute_filters())

	# ---- the tick ----
	def test_a_tick_lists_the_models_that_have_a_variant_with_the_value(self):
		self.assertEqual(self.listing({SIZE: ["M"]}) & {SHIRT, COAT, PARKA}, {SHIRT})
		self.assertEqual(self.listing({SIZE: ["XL"]}) & {SHIRT, COAT, PARKA}, {COAT})
		self.assertEqual(self.listing({SIZE: ["S", "L"]}) & {SHIRT, COAT, PARKA}, {SHIRT, COAT})
		self.assertEqual(self.listing({COLOUR: ["Red"]}) & {SHIRT, COAT, PARKA}, {SHIRT, COAT})

	def test_a_value_only_a_disabled_or_unpublished_model_carries_finds_nothing(self):
		for value in ("XXL", "XS"):
			with self.subTest(value):
				self.assertEqual(self.listing({SIZE: [value]}), set())
		self.assertEqual(self.listing({COLOUR: ["Green"]}), set())

	def test_two_ticks_ask_for_the_same_variant(self):
		# the shirt has an M (red) and a blue (small), no blue M: it is not what "M" and "Blue" ask for
		self.assertEqual(self.listing({SIZE: ["M"], COLOUR: ["Blue"]}), set())
		self.assertEqual(self.listing({SIZE: ["S"], COLOUR: ["Blue"]}) & {SHIRT, COAT}, {SHIRT})
		self.assertEqual(self.listing({SIZE: ["L"], COLOUR: ["Blue"]}) & {SHIRT, COAT}, {COAT})
		self.assertEqual(self.listing({SIZE: ["M", "L"], COLOUR: ["Blue"]}) & {SHIRT, COAT}, {COAT})

	def test_an_attribute_ticked_with_no_value_asks_nothing_of_the_variants(self):
		# the page never sends one; if a request does, it reads as no tick of that attribute
		self.assertEqual(model_attributes.models_matching_attributes({SIZE: []}), set())
		self.assertEqual(
			model_attributes.models_matching_attributes({SIZE: ["M"], COLOUR: []}),
			model_attributes.models_matching_attributes({SIZE: ["M"]}),
		)

	def test_a_visitor_with_no_account_gets_the_same_answer(self):
		frappe.set_user("Guest")
		self.addCleanup(frappe.set_user, "Administrator")
		self.assertEqual(self.listing({SIZE: ["M"]}) & {SHIRT, COAT}, {SHIRT})
		self.assertEqual(self.facets(item_group=TOPS)[SIZE], ["S", "M"])

	def test_one_query_serves_every_model_whatever_their_number(self):
		for run in (
			lambda: model_attributes.variant_attribute_values({SHIRT, COAT, BOOT, GROUPY, SANDAL}, [SIZE, COLOUR], True),
			lambda: model_attributes.models_matching_attributes({SIZE: ["M"], COLOUR: ["Red"]}, True),
		):
			with patch.object(frappe.db, "sql", wraps=frappe.db.sql) as sql:
				run()
			self.assertEqual(sql.call_count, 1)

	def test_a_value_sent_by_a_visitor_is_a_value_never_a_statement(self):
		hostile = "M') OR 1=1 -- "
		self.assertEqual(self.listing({SIZE: [hostile]}), set())
		self.assertEqual(self.listing({f"{SIZE}' OR 1=1 -- ": ["M"]}), set())

	def test_a_variant_with_a_card_of_its_own_is_found_as_itself_and_does_not_list_its_model(self):
		# the tent's M is a card of its own: the tick finds it, as it always did, and not the tent; its S has none
		self.assertEqual(self.listing({SIZE: ["M"]}) & {TENT, self.tent_m}, {self.tent_m})
		self.assertEqual(self.listing({SIZE: ["S"]}) & {TENT, self.tent_m}, {TENT})
		self.assertEqual(model_attributes.models_matching_attributes({SIZE: ["M"]}) & {TENT}, set())

	# ---- beside the other filters ----
	def test_the_category_the_brand_and_a_field_filter_combine_with_a_size(self):
		cases = (
			("the category the shirt is in", {"item_group": [TOPS]}, {SIZE: ["M"]}, {SHIRT}),
			("another category", {"item_group": [COATS]}, {SIZE: ["M"]}, set()),
			("the coat's category", {"item_group": [COATS]}, {SIZE: ["L"]}, {COAT}),
			("the brand of the shirt", {"brand": [ONE]}, {SIZE: ["M"]}, {SHIRT}),
			("another brand", {"brand": [TWO]}, {SIZE: ["M"]}, set()),
			("a gender", {GENDER_FIELD: ["Women"]}, {SIZE: ["M"]}, {SHIRT}),
			("the other gender", {GENDER_FIELD: ["Men"]}, {SIZE: ["M"]}, set()),
			("the other gender, another size", {GENDER_FIELD: ["Men"]}, {SIZE: ["XL"]}, {COAT}),
			("a size no model of the gender has", {GENDER_FIELD: ["Women"]}, {SIZE: ["XL"]}, set()),
		)
		for label, fields, attributes, expected in cases:
			with self.subTest(label):
				self.assertEqual(self.listing(attributes, fields) & {SHIRT, COAT, PARKA}, expected)

	def test_a_field_filter_alone_lists_the_models_of_the_gender(self):
		self.assertEqual(self.listing({}, {GENDER_FIELD: ["Women"]}) & {SHIRT, COAT, PARKA}, {SHIRT})
		self.assertEqual(self.listing({}, {GENDER_FIELD: ["Men"]}) & {SHIRT, COAT, PARKA}, {COAT})

	def test_a_select_field_is_a_facet_in_the_order_of_its_options(self):
		builder = ProductFiltersBuilder()
		builder.doc = frappe._dict(
			{"enable_field_filters": 1, "filter_fields": [frappe._dict(fieldname=GENDER_FIELD)]}
		)
		facets = builder.get_field_filters()
		self.assertEqual(len(facets), 1)
		field, values = facets[0]
		self.assertEqual(field.fieldname, GENDER_FIELD)
		self.assertEqual([v for v in values if v in ("Men", "Women", "Junior")], ["Men", "Women"])

	def test_a_shop_that_ticks_nothing_lists_the_models_and_no_variant(self):
		listed = self.listing()
		self.assertTrue({SHIRT, COAT, BOOT} <= listed)
		self.assertFalse(listed - set(MODELS) - set(STOCKED) - {TENT, self.tent_m})

	# ---- the stock ----
	def test_without_the_stock_rule_a_variant_out_of_stock_still_counts(self):
		self.assertEqual(self.listing({SIZE: ["L"]}) & {COAT, BOOT}, {COAT, BOOT})
		self.assertEqual(self.listing({SIZE: ["XL"]}) & {COAT, BOOT}, {COAT, BOOT})

	def test_where_the_shop_shows_only_what_is_in_stock_a_tick_finds_a_variant_that_can_be_bought(self):
		self.in_stock_rule()
		# the coat's variants are not stock items: always there. The boot's L has no stock, its XL is all reserved
		self.assertEqual(self.listing({SIZE: ["L"]}) & {COAT, BOOT}, {COAT})
		self.assertEqual(self.listing({SIZE: ["XL"]}) & {COAT, BOOT}, {COAT})
		self.assertEqual(self.listing({SIZE: ["M"]}) & {SHIRT, BOOT, GROUPY}, {SHIRT, BOOT, GROUPY})

	def test_the_card_on_backorder_and_the_card_with_no_shop_warehouse_keep_their_variants(self):
		self.in_stock_rule()
		self.assertEqual(self.listing({SIZE: ["S"]}) & {SHIRT, SANDAL, CLOG}, {SHIRT, SANDAL, CLOG})

	def test_the_stock_of_a_group_warehouse_is_the_stock_of_its_children(self):
		self.in_stock_rule()
		# GROUPY's card reads the group; the bin of its M is in the child
		self.assertEqual(self.listing({SIZE: ["M"]}) & {GROUPY}, {GROUPY})
		frappe.db.set_value("Bin", {"item_code": ("like", f"{GROUPY}%")}, "actual_qty", 0)
		self.addCleanup(frappe.db.set_value, "Bin", {"item_code": ("like", f"{GROUPY}%")}, "actual_qty", 2)
		self.assertEqual(self.listing({SIZE: ["M"]}) & {GROUPY}, set())

	def test_the_facet_offers_only_the_values_that_can_be_bought_when_the_shop_asks(self):
		self.assertEqual(self.facets(item_group=BOOTS)[SIZE], ["S", "M", "L", "XL"])
		self.in_stock_rule()
		# the boot's L has no stock and its XL is all reserved: they leave; M (stock, and in a group's child) and the
		# sandal's and the clog's S (backorder, no shop warehouse) stay
		self.assertEqual(self.facets(item_group=BOOTS)[SIZE], ["S", "M"])

	def test_the_visitors_in_stock_toggle_asks_for_a_variant_that_can_be_bought_too(self):
		self.assertEqual(self.listing({SIZE: ["L"]}, {"in_stock": ["1"]}) & {COAT, BOOT}, {COAT})
		self.assertEqual(self.listing({SIZE: ["M"]}, {"in_stock": ["1"]}) & {SHIRT, BOOT, GROUPY}, {SHIRT, BOOT, GROUPY})

	def test_the_switch_of_the_theme_is_read_only_where_the_theme_adds_it(self):
		field = model_attributes.SHOW_ONLY_IN_STOCK
		with_theme = frappe.get_meta("Webshop Settings").has_field(field)
		self.assertEqual(model_attributes.shows_only_what_is_in_stock(frappe._dict({field: 1})), with_theme)
		self.assertFalse(model_attributes.shows_only_what_is_in_stock(frappe._dict({field: 0})))
		self.assertFalse(model_attributes.shows_only_what_is_in_stock(frappe._dict()))
