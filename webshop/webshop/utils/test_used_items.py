# //// Neoffice — added file (second-hand feature, no upstream equivalent).
"""Second-hand units: the one-click creation, the mirror to the shop, the facet.

Everything a test creates is rolled back by FrappeTestCase; the only thing
that survives a rollback is the Webshop Settings row this class may add to
`filter_fields`, which tearDownClass removes again.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.doctype.website_item.website_item import make_website_item
from webshop.webshop.product_data_engine.filters import ProductFiltersBuilder
from webshop.webshop.tests.utils import (
	PREFIX,
	default_company,
	make_test_item,
	restore_webshop_settings,
	selling_price_list,
	snapshot_webshop_settings,
)
from webshop.webshop.utils import used_items


class TestUsedItems(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.suffix = frappe.generate_hash(length=5).upper()
		# a shop without a price list prices nothing (the CI site starts bare)
		cls.snapshot = snapshot_webshop_settings(("enabled", "show_price", "price_list", "company"))
		settings = frappe.get_single("Webshop Settings")
		settings.enabled = 1
		settings.show_price = 1
		if not settings.price_list:
			settings.price_list = selling_price_list()
		if not settings.company:
			settings.company = default_company()
		settings.flags.ignore_permissions = True
		settings.flags.ignore_mandatory = True
		settings.save()
		cls.price_list = settings.price_list
		cls.warehouse = frappe.db.get_value(
			"Warehouse", {"is_group": 0, "company": default_company()}, "name"
		)
		settings = frappe.get_single("Webshop Settings")
		cls.added_filter_row = not any(
			row.fieldname == "item_condition" for row in settings.filter_fields or []
		)
		if cls.added_filter_row:
			settings.append("filter_fields", {"fieldname": "item_condition"})
			settings.flags.ignore_permissions = True
			settings.flags.ignore_mandatory = True
			settings.save()
			frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		restore_webshop_settings(cls.snapshot)
		if cls.added_filter_row:
			settings = frappe.get_single("Webshop Settings")
			settings.filter_fields = [r for r in settings.filter_fields if r.fieldname != "item_condition"]
			settings.flags.ignore_permissions = True
			settings.flags.ignore_mandatory = True
			settings.save()
			frappe.db.commit()
		super().tearDownClass()

	def make_source(self, label, **properties):
		code = f"{PREFIX} {label} {self.suffix}"
		item = make_test_item(code, **properties)
		if not frappe.db.exists("Item Price", {"item_code": item.name, "price_list": self.price_list}):
			frappe.get_doc(
				{
					"doctype": "Item Price",
					"item_code": item.name,
					"price_list": self.price_list,
					"price_list_rate": 100,
					"selling": 1,
				}
			).insert(ignore_permissions=True)
		return frappe.get_doc("Item", item.name)

	# --- vocabulary -------------------------------------------------------

	def test_vocabulary_matches_schema_org(self):
		self.assertEqual(used_items.condition_schema_url("Second-hand"), "https://schema.org/UsedCondition")
		self.assertEqual(
			used_items.condition_schema_url("Refurbished"), "https://schema.org/RefurbishedCondition"
		)
		self.assertEqual(used_items.condition_schema_url(None), "https://schema.org/NewCondition")
		self.assertTrue(used_items.is_second_hand("Second-hand"))
		self.assertFalse(used_items.is_second_hand("New"))

	def test_warranty_reads_in_months(self):
		self.assertEqual(used_items.warranty_months(365), 12)
		self.assertEqual(used_items.warranty_months("730"), 24)
		self.assertEqual(used_items.warranty_months(None), 0)

	# --- one click on the new item -----------------------------------------

	def test_used_unit_is_its_own_item_priced_and_published(self):
		source = self.make_source("Mouse", is_stock_item=0)
		make_website_item(source)

		result = used_items.create_used_unit(
			source.name,
			price=40,
			condition="Second-hand",
			grade="Good",
			details="Scratches",
			cost=0,
			publish=1,
			price_list=self.price_list,
		)

		unit = frappe.get_doc("Item", result["item_code"])
		self.assertEqual(unit.name, f"{source.name}-USED-01")
		self.assertEqual(unit.item_condition, "Second-hand")
		self.assertEqual(unit.condition_grade, "Good")
		self.assertEqual(unit.condition_details, "Scratches")
		self.assertEqual(unit.condition_of_item, source.name)
		self.assertEqual(unit.warranty_period, "365")
		self.assertEqual(unit.item_group, source.item_group)

		self.assertEqual(
			frappe.db.get_value(
				"Item Price", {"item_code": unit.name, "price_list": self.price_list}, "price_list_rate"
			),
			40,
		)

		page = frappe.get_doc("Website Item", result["website_item"])
		self.assertTrue(page.published)
		self.assertEqual(page.item_condition, "Second-hand")
		self.assertEqual(page.condition_grade, "Good")
		self.assertEqual(page.condition_of_item, source.name)
		self.assertTrue(result["route"])

		# the new item now points at its used unit, cheapest first
		units = used_items.get_used_units(source.name)
		self.assertEqual([u.item_code for u in units], [unit.name])
		self.assertEqual(units[0].price, 40)
		self.assertTrue(units[0].formatted_price)

		# and the unit's page knows where it comes from
		info = used_items.condition_info(page)
		self.assertEqual(info.grade, "Good")
		self.assertEqual(info.warranty_months, 12)
		self.assertEqual(info.reference.route, frappe.db.get_value("Website Item", {"item_code": source.name}, "route"))

		# the second unit takes the next number
		second = used_items.create_used_unit(source.name, price=35, publish=0, price_list=self.price_list)
		self.assertEqual(second["item_code"], f"{source.name}-USED-02")
		self.assertIsNone(second["website_item"])

	def test_used_unit_enters_the_stock(self):
		if not self.warehouse:
			self.fail("no leaf warehouse on this site")
		source = self.make_source("Lamp", is_stock_item=1)

		result = used_items.create_used_unit(
			source.name, price=60, qty=1, cost=15, warehouse=self.warehouse, publish=0
		)

		self.assertTrue(result["stock_entry"])
		self.assertEqual(
			frappe.db.get_value(
				"Bin", {"item_code": result["item_code"], "warehouse": self.warehouse}, "actual_qty"
			),
			1,
		)

	def test_template_items_are_refused(self):
		source = self.make_source("Template", is_stock_item=0)
		# a template needs an attribute table to save; the guard only reads the flag
		frappe.db.set_value("Item", source.name, "has_variants", 1)
		self.assertRaises(frappe.ValidationError, used_items.create_used_unit, source.name, price=10)

	def test_price_is_mandatory(self):
		source = self.make_source("Free", is_stock_item=0)
		self.assertRaises(frappe.ValidationError, used_items.create_used_unit, source.name, price=0)

	# --- the shop follows the item ----------------------------------------

	def test_condition_change_reaches_the_website_item(self):
		source = self.make_source("Sync", is_stock_item=0)
		make_website_item(source)

		source = frappe.get_doc("Item", source.name)
		source.item_condition = "Refurbished"
		source.condition_grade = "Like New"
		source.save()

		page = frappe.db.get_value(
			"Website Item", {"item_code": source.name}, ["item_condition", "condition_grade"], as_dict=True
		)
		self.assertEqual(page.item_condition, "Refurbished")
		self.assertEqual(page.condition_grade, "Like New")

	def test_condition_facet_appears_once_there_is_a_choice(self):
		def facet():
			for df, values in ProductFiltersBuilder().get_field_filters():
				if df.fieldname == "item_condition":
					return values
			return None

		source = self.make_source("Facet", is_stock_item=0)
		make_website_item(source)
		before = facet()

		used_items.create_used_unit(source.name, price=20, condition="Refurbished", publish=1)
		after = facet()

		self.assertIsNotNone(after)
		self.assertIn("Refurbished", after)
		if before is not None:
			# some other second-hand unit was already published on this site
			self.assertTrue([v for v in before if v and v != "New"])
