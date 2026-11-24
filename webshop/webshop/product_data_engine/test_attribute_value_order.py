# //// Neoffice — added file (no upstream equivalent). neoffice-maintenance#3344.
"""The order of the values an attribute facet offers: the merchant's, then a natural one.

The fork sorted them alphabetically, so a size facet read "L, M, S, XL" and a shoe size "10, 12, 8". The order is now the one
the merchant gave the values on the Item Attribute (the rows of its form, `Item Attribute Value.idx`); a value the attribute
does not list follows, in a natural order (8 before 10). The order stays one fixed order whatever the database returns, which
is what the alphabetical sort protected.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.product_data_engine import attribute_value_order
from webshop.webshop.product_data_engine.attribute_value_order import natural_key, order_values
from webshop.webshop.product_data_engine.filters import ProductFiltersBuilder
from webshop.webshop.tests.utils import restore_webshop_settings, root_item_group, snapshot_webshop_settings

PREFIX = "_WSTEST Order"
SIZE, SHOE, RANGE = f"{PREFIX} Size", f"{PREFIX} Shoe", f"{PREFIX} Range"
SHIRTS, SHOES, RANGED = f"{PREFIX} Shirts", f"{PREFIX} Shoes", f"{PREFIX} Ranged"
SHIRT, BOOT, CLOG = f"{PREFIX} Shirt", f"{PREFIX} Boot", f"{PREFIX} Clog"

# attribute: values in the order the merchant gave them (the order of the rows of the Item Attribute form)
LISTED = {
	SIZE: ("S", "M", "L", "XL", "XXL"),
	SHOE: ("8", "10", "12"),
}
# model: (item group, attribute, values its variants carry, created in this order)
MODELS = {
	SHIRT: (SHIRTS, SIZE, ("XL", "S", "L", "M")),
	BOOT: (SHOES, SHOE, ("12", "8", "10")),
	CLOG: (RANGED, RANGE, ("12", "8", "10")),  # a numeric attribute: a range, no row to list
}


def purge():
	frappe.db.delete("Bin", {"item_code": ("like", f"{PREFIX}%")})
	for doctype, filters in (
		("Website Item", {"item_code": ("like", f"{PREFIX}%")}),
		("Item", {"variant_of": ("like", f"{PREFIX}%")}),
		("Item", {"item_code": ("like", f"{PREFIX}%")}),
		("Item Attribute", {"name": ("in", [SIZE, SHOE, RANGE])}),
		("Item Group", {"name": ("in", [SHIRTS, SHOES, RANGED])}),
	):
		for name in frappe.get_all(doctype, filters=filters, pluck="name"):
			frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
	# the fixtures live across the tests and leave with the class (CLAUDE.md, "Fixtures built in setUpClass need a commit")
	frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit


class TestTheOrderOfTheValues(FrappeTestCase):
	"""What the function does, with no database."""

	def test_the_merchants_order_comes_first(self):
		listed = {"S": 1, "M": 2, "L": 3, "XL": 4}
		self.assertEqual(order_values(["L", "XL", "M", "S"], listed), ["S", "M", "L", "XL"])
		# the merchant's order is the one given, not a better one he might have chosen
		self.assertEqual(order_values(["a", "b", "c"], {"c": 1, "a": 2, "b": 3}), ["c", "a", "b"])

	def test_the_values_the_attribute_does_not_list_follow_in_natural_order(self):
		self.assertEqual(order_values(["10", "XL", "8", "S", "9"], {"S": 1, "XL": 2}), ["S", "XL", "8", "9", "10"])

	def test_a_number_is_a_number_not_a_string(self):
		self.assertEqual(order_values(["10", "12", "8", "9", "100"]), ["8", "9", "10", "12", "100"])
		self.assertEqual(order_values(["Size 10", "Size 8", "Size 9"]), ["Size 8", "Size 9", "Size 10"])
		self.assertEqual(order_values(["9", "8,5", "8"]), ["8", "8,5", "9"])

	def test_the_words_keep_the_alphabetical_order_of_before_without_regard_to_case(self):
		self.assertEqual(order_values(["Rouge", "bleu", "Vert", "Anthracite"]), ["Anthracite", "bleu", "Rouge", "Vert"])

	def test_the_order_does_not_depend_on_the_order_the_values_come_in(self):
		values = ["B", "a", "A", "b", "10", "9", "x1", "X1"]
		expected = order_values(values)
		for rotation in range(len(values)):
			self.assertEqual(order_values(values[rotation:] + values[:rotation]), expected)
		self.assertEqual(order_values(list(reversed(values))), expected)

	def test_a_value_that_is_not_a_string_does_not_stop_the_facet(self):
		self.assertEqual(order_values([10, "8", 9.5]), ["8", 9.5, 10])
		self.assertEqual(order_values([None, "b", "a"])[1:], ["a", "b"])

	def test_an_exotic_digit_is_not_a_number_to_sort_by(self):
		# a superscript "digit" is no decimal digit: int() refuses it, and the facet must still be drawn
		self.assertEqual(len(order_values(["m²", "m3", "m1"])), 3)
		self.assertEqual(natural_key("a²10")[0], (1, 0, "a²"))

	def test_an_attribute_that_lists_a_value_in_another_case_still_places_it(self):
		self.assertEqual(order_values(["xl", "S"], {"S": 1, "XL": 2}), ["S", "xl"])


class TestTheOrderOfAFacet(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		purge()
		cls.settings = snapshot_webshop_settings(["hide_variants"])
		frappe.db.set_single_value("Webshop Settings", {"hide_variants": 0})

		from erpnext.controllers.item_variant import create_variant

		uom = frappe.db.get_value("UOM", {}, "name")
		for name in (SHIRTS, SHOES, RANGED):
			frappe.get_doc(
				{
					"doctype": "Item Group",
					"item_group_name": name,
					"parent_item_group": root_item_group(),
					"is_group": 0,
					"show_in_website": 1,
				}
			).insert(ignore_permissions=True)
		for attribute, values in LISTED.items():
			frappe.get_doc(
				{
					"doctype": "Item Attribute",
					"attribute_name": attribute,
					"item_attribute_values": [{"attribute_value": v, "abbr": v} for v in values],
				}
			).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Item Attribute",
				"attribute_name": RANGE,
				"numeric_values": 1,
				"from_range": 8,
				"to_range": 12,
				"increment": 1,
			}
		).insert(ignore_permissions=True)

		cls.variants = {}
		for code, (item_group, attribute, values) in MODELS.items():
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": code,
					"item_name": code,
					"item_group": item_group,
					"stock_uom": uom,
					"is_stock_item": 0,
					"has_variants": 1,
					"variant_based_on": "Item Attribute",
					# a numeric attribute is told to the model with its range, as the form of an item does when it is picked
					"attributes": [
						{"attribute": attribute, "numeric_values": 1, "from_range": 8, "to_range": 12, "increment": 1}
						if attribute == RANGE
						else {"attribute": attribute}
					],
				}
			).insert(ignore_permissions=True)
			frappe.get_doc(
				{
					"doctype": "Website Item",
					"item_code": code,
					"web_item_name": code,
					"item_group": item_group,
					"published": 1,
					"route": "products/" + frappe.scrub(code).replace("_", "-"),
				}
			).insert(ignore_permissions=True)
			frappe.db.set_value("Website Item", {"item_code": code}, "sold", 0)
			for value in values:
				made = create_variant(code, {attribute: value})
				made.insert(ignore_permissions=True)
				cls.variants[(code, value)] = made.name

		# a test's rollback would take the class's fixtures with it (see purge)
		frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit

	@classmethod
	def tearDownClass(cls):
		purge()
		restore_webshop_settings(cls.settings)
		super().tearDownClass()

	def facets(self, item_group, *attributes, **doc):
		builder = ProductFiltersBuilder(item_group=item_group)
		builder.doc = frappe._dict(
			{
				"enable_attribute_filters": 1,
				"hide_variants": 0,
				"filter_attributes": [frappe._dict(attribute=attribute) for attribute in attributes],
				**doc,
			}
		)
		return {facet.name: facet.item_attribute_values for facet in builder.get_attribute_filters() or []}

	def test_the_sizes_come_in_the_order_of_the_attribute_not_the_alphabet(self):
		# the variants were made XL, S, L, M and the alphabet says L, M, S, XL
		self.assertEqual(self.facets(SHIRTS, SIZE)[SIZE], ["S", "M", "L", "XL"])

	def test_the_shoe_sizes_come_in_the_order_of_the_attribute(self):
		self.assertEqual(self.facets(SHOES, SHOE)[SHOE], ["8", "10", "12"])

	def test_a_value_the_attribute_does_not_list_follows_the_listed_ones(self):
		# the boots made for the sizes 8 and 12 now carry a 7 and an 11: neither is a row of the attribute any more
		for old, new in (("8", "7"), ("12", "11")):
			row = frappe.db.get_value(
				"Item Variant Attribute", {"parent": self.variants[(BOOT, old)], "attribute": SHOE}, "name"
			)
			frappe.db.set_value("Item Variant Attribute", row, "attribute_value", new)
			self.addCleanup(frappe.db.set_value, "Item Variant Attribute", row, "attribute_value", old)
		# the 10 is a row of the attribute and comes first, though the natural order would put the 7 before it
		self.assertEqual(self.facets(SHOES, SHOE)[SHOE], ["10", "7", "11"])

	def test_an_attribute_that_holds_a_range_and_no_row_has_a_natural_order(self):
		self.assertEqual(self.facets(RANGED, RANGE)[RANGE], ["8", "10", "12"])

	def test_the_facet_of_several_attributes_reads_the_order_in_one_query(self):
		with patch.object(frappe, "get_all", wraps=frappe.get_all) as get_all:
			facets = self.facets(None, SIZE, SHOE, RANGE)
		reads = [call for call in get_all.call_args_list if call.args and call.args[0] == "Item Attribute Value"]
		self.assertEqual(len(reads), 1)
		self.assertEqual(facets[SIZE], ["S", "M", "L", "XL"])
		self.assertEqual(facets[SHOE], ["8", "10", "12"])

	def test_the_listed_positions_are_the_rows_of_the_form(self):
		positions = attribute_value_order.listed_positions([SIZE, SHOE, RANGE, f"{PREFIX} Nothing"])
		self.assertEqual(sorted(positions[SIZE], key=positions[SIZE].get), list(LISTED[SIZE]))
		self.assertEqual(sorted(positions[SHOE], key=positions[SHOE].get), list(LISTED[SHOE]))
		# a numeric attribute and an attribute that does not exist list nothing
		self.assertNotIn(RANGE, positions)
		self.assertNotIn(f"{PREFIX} Nothing", positions)
		self.assertEqual(attribute_value_order.listed_positions([]), {})

	def test_a_visitor_with_no_account_sees_the_same_order(self):
		frappe.set_user("Guest")
		self.addCleanup(frappe.set_user, "Administrator")
		self.assertEqual(self.facets(SHIRTS, SIZE)[SIZE], ["S", "M", "L", "XL"])
