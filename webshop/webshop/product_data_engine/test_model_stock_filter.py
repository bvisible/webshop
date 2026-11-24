# //// Neoffice — added file (no upstream equivalent). neoffice-maintenance#3343.
"""The "only what is in stock" box of a shop that lists MODELS: one card per model, its stock on variants.

A model's own item never holds stock (a bin belongs to a variant), so the rule that read the stock of the card's own item
took every card of a model off the list the moment the box was ticked, whatever its variants held. A model is in stock
when one of its live variants can be bought: the condition the size facet already uses (`VARIANT_IN_STOCK`), not
a second copy of it. A card of a plain item (no variants) is told as before.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.product_data_engine import model_attributes
from webshop.webshop.product_data_engine.query import ProductQuery
from webshop.webshop.tests.utils import (
	default_company,
	leaf_item_group,
	restore_webshop_settings,
	snapshot_webshop_settings,
)

PREFIX = "_WSTEST Stock"
SIZE = f"{PREFIX} Size"
GROUP_WAREHOUSE, CHILD_WAREHOUSE = f"{PREFIX} Group", f"{PREFIX} Child"

(SOME, NONE, DISABLED, GROUPED, ORDERED, SERVICE, EMPTY, OWN_CARD, FLAGGED, HIDDEN) = (
	f"{PREFIX} {name}"
	for name in ("Some", "None", "Disabled", "Grouped", "Ordered", "Service", "Empty", "OwnCard", "Flagged", "Hidden")
)
PLAIN_IN, PLAIN_OUT, PLAIN_FREE = (f"{PREFIX} {name}" for name in ("PlainIn", "PlainOut", "PlainFree"))

# model: (is_stock_item of the model, warehouse, published, [(size, is_stock_item of the variant, stock, reserved, disabled)])
# the stock of a variant is in the bin of the card's warehouse, or of its child
MODELS = {
	# one variant has stock: the model is in stock
	SOME: (1, "child", 1, [("S", 1, 5, 0, 0), ("M", 1, 0, 0, 0)]),
	# nothing to buy: no stock, and all of the rest reserved
	NONE: (1, "child", 1, [("S", 1, 0, 0, 0), ("M", 1, 4, 4, 0)]),
	# the only stock is on a variant that is disabled
	DISABLED: (1, "child", 1, [("S", 1, 9, 0, 1), ("M", 1, 0, 0, 0)]),
	# the card reads the group warehouse; the bin is in its child
	GROUPED: (1, "group", 1, [("S", 1, 2, 0, 0)]),
	# a model whose own flag says "not a stock item" is told by its variants too
	FLAGGED: (0, "child", 1, [("S", 1, 0, 0, 0)]),
	SERVICE: (0, "child", 1, [("S", 0, 0, 0, 0)]),
	# a card that is hidden stays hidden
	HIDDEN: (1, "child", 0, [("S", 1, 5, 0, 0)]),
	# a model with no variant has nothing to sell
	EMPTY: (1, "child", 1, []),
}
PLAIN = {PLAIN_IN: (1, 7), PLAIN_OUT: (1, 0), PLAIN_FREE: (0, 0)}  # item: (is_stock_item, stock of its own bin)


def no_display_details(self, result, discount_list, cart_items):
	"""The tiles' prices are not what this module is about."""
	return result, discount_list


def purge():
	frappe.db.delete("Bin", {"item_code": ("like", f"{PREFIX}%")})
	for doctype, filters in (
		("Website Item", {"item_code": ("like", f"{PREFIX}%")}),
		("Item", {"variant_of": ("like", f"{PREFIX}%")}),
		("Item", {"item_code": ("like", f"{PREFIX}%")}),
		("Item Attribute", {"name": SIZE}),
		("Warehouse", {"name": ("like", f"{PREFIX} Child%")}),
		("Warehouse", {"name": ("like", f"{PREFIX} Group%")}),
	):
		for name in frappe.get_all(doctype, filters=filters, pluck="name"):
			frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
	# the fixtures live across the tests and leave with the class (CLAUDE.md, "Fixtures built in setUpClass need a commit")
	frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit


class TestTheStockBoxOnModels(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		purge()
		cls.settings = snapshot_webshop_settings(["hide_variants"])
		frappe.db.set_single_value("Webshop Settings", {"hide_variants": 0})

		from erpnext.controllers.item_variant import create_variant
		from erpnext.stock.utils import get_or_make_bin

		company, uom = default_company(), frappe.db.get_value("UOM", {}, "name")
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
		warehouses = {"group": group.name, "child": child.name}
		frappe.get_doc(
			{
				"doctype": "Item Attribute",
				"attribute_name": SIZE,
				"item_attribute_values": [{"attribute_value": v, "abbr": v} for v in ("S", "M", "L")],
			}
		).insert(ignore_permissions=True)

		def card(code, warehouse, published, **more):
			web_item = frappe.get_doc(
				{
					"doctype": "Website Item",
					"item_code": code,
					"web_item_name": code,
					"item_group": leaf_item_group(),
					"published": published,
					"website_warehouse": warehouse,
					"route": "products/" + frappe.scrub(code).replace("_", "-"),
				}
			).insert(ignore_permissions=True)
			# written straight: the card is what the listing reads
			frappe.db.set_value("Website Item", web_item.name, {"sold": 0, **more})

		def item(code, **fields):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": code,
					"item_name": code,
					"item_group": leaf_item_group(),
					"stock_uom": uom,
					**fields,
				}
			).insert(ignore_permissions=True)

		def stock(code, warehouse, qty, reserved=0):
			bin_name = get_or_make_bin(code, warehouse)
			frappe.db.set_value("Bin", bin_name, {"actual_qty": qty, "reserved_qty": reserved})

		def model(code, is_stock_item, warehouse, published, **more):
			item(
				code,
				is_stock_item=is_stock_item,
				has_variants=1,
				variant_based_on="Item Attribute",
				attributes=[{"attribute": SIZE}],
			)
			card(code, warehouses[warehouse] if warehouse else None, published, **more)

		def variant(code, size, is_stock_item, qty, reserved, disabled):
			made = create_variant(code, {SIZE: size})
			made.insert(ignore_permissions=True)
			frappe.db.set_value("Item", made.name, {"disabled": disabled, "is_stock_item": is_stock_item})
			if qty or reserved:
				stock(made.name, warehouses["child"], qty, reserved)
			return made.name

		for code, (is_stock_item, warehouse, published, variants) in MODELS.items():
			model(code, is_stock_item, warehouse, published)
			for size, variant_is_stock_item, qty, reserved, disabled in variants:
				variant(code, size, variant_is_stock_item, qty, reserved, disabled)

		# a model on backorder, with nothing in any bin
		model(ORDERED, 1, "child", 1, on_backorder=1)
		variant(ORDERED, "S", 1, 0, 0, 0)

		# a model whose only variant that holds stock has a card of its own: the model can still be bought through it
		model(OWN_CARD, 1, "child", 1)
		own = variant(OWN_CARD, "S", 1, 3, 0, 0)
		card(own, warehouses["child"], 1)
		cls.own_card_variant = own

		# the cards of plain items (no variants) are told by their own bin
		for code, (is_stock_item, qty) in PLAIN.items():
			item(code, is_stock_item=is_stock_item, has_variants=0)
			card(code, warehouses["child"], 1)
			if qty:
				stock(code, warehouses["child"], qty)

		# a test's rollback would take the class's fixtures with it (see purge)
		frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit

	@classmethod
	def tearDownClass(cls):
		purge()
		restore_webshop_settings(cls.settings)
		super().tearDownClass()

	def setUp(self):
		patcher = patch.object(ProductQuery, "add_display_details", no_display_details)
		patcher.start()
		self.addCleanup(patcher.stop)

	def listing(self, fields=None):
		"""The cards of the run that the shop lists, with the box ticked or not."""
		engine = ProductQuery()
		engine.page_length = 1000
		result = engine.query({}, dict(fields or {}), search_term=None, start=0, item_group=None)
		codes = [row["item_code"] for row in result["items"]]
		self.assertEqual(result["total_count"], len(codes), "the count and the page disagree")
		return {code for code in codes if code.startswith(PREFIX)}

	def in_stock(self):
		return self.listing({"in_stock": ["1"]})

	def test_a_model_is_in_stock_when_one_of_its_variants_is(self):
		listed = self.in_stock()
		for model in (SOME, GROUPED):
			with self.subTest(model):
				self.assertIn(model, listed)

	def test_a_model_none_of_whose_variants_can_be_bought_leaves(self):
		listed = self.in_stock()
		# no stock at all, all of it reserved, the only stock on a disabled variant, no variant at all
		for model in (NONE, DISABLED, EMPTY):
			with self.subTest(model):
				self.assertNotIn(model, listed)

	def test_a_model_is_told_by_its_variants_whatever_its_own_flag_says(self):
		listed = self.in_stock()
		# the model is flagged "not a stock item": that made it always in stock, though its variants hold nothing
		self.assertNotIn(FLAGGED, listed)
		# and a model whose variants are not stock items is always in stock, as a service is
		self.assertIn(SERVICE, listed)

	def test_a_model_on_backorder_stays(self):
		self.assertIn(ORDERED, self.in_stock())

	def test_a_variant_with_a_card_of_its_own_still_makes_its_model_sellable(self):
		listed = self.in_stock()
		self.assertIn(OWN_CARD, listed)
		self.assertIn(self.own_card_variant, listed)

	def test_a_card_that_is_hidden_stays_hidden(self):
		self.assertNotIn(HIDDEN, self.in_stock())

	def test_the_card_of_a_plain_item_is_told_as_before(self):
		listed = self.in_stock()
		self.assertIn(PLAIN_IN, listed)
		self.assertIn(PLAIN_FREE, listed)
		self.assertNotIn(PLAIN_OUT, listed)

	def test_without_the_box_every_published_card_is_listed(self):
		listed = self.listing()
		expected = {
			SOME, NONE, DISABLED, GROUPED, ORDERED, SERVICE, EMPTY, OWN_CARD, FLAGGED,
			self.own_card_variant, PLAIN_IN, PLAIN_OUT, PLAIN_FREE,
		}  # fmt: skip
		self.assertEqual(listed, expected)

	def test_the_box_and_the_size_facet_agree_on_what_can_be_bought(self):
		# the same condition (VARIANT_IN_STOCK) answers both: the models the box keeps are the ones a tick on any size finds
		# when the shop shows only what is in stock (the model with a variant of its own card is found as that variant)
		models = [SOME, NONE, DISABLED, GROUPED, ORDERED, SERVICE, EMPTY, FLAGGED]
		by_the_facet = model_attributes.models_matching_attributes({SIZE: ["S", "M", "L"]}, only_in_stock=True)
		listed = self.in_stock()
		for model in models:
			with self.subTest(model):
				self.assertEqual(model in listed, model in by_the_facet)

	def test_a_visitor_with_no_account_gets_the_same_answer(self):
		expected = self.in_stock()
		frappe.set_user("Guest")
		self.addCleanup(frappe.set_user, "Administrator")
		self.assertEqual(self.in_stock(), expected)
