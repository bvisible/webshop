# //// Neoffice — added file (multi-warehouse feature test suite).
# Self-contained: creates its own warehouses, items, website items, customer
# and supplier (all prefixed MWTEST), configures Webshop Settings in-memory,
# and rolls everything back after each test. Runs on a real dev site (osiris)
# as well as on CI. The supplier source uses stock_basis "Item Field" on the
# standard Item.opening_stock field so no Stock Entry (hence no accounting) is
# needed for the logic tests; one dedicated test covers the Bin path.

import datetime
import unittest

import frappe
from frappe.utils import add_days, getdate, nowdate

from webshop.webshop.multi_warehouse.delays import (
	add_business_days,
	estimate_delivery_date,
	expected_receipt_date,
	next_order_departure,
)
from webshop.webshop.multi_warehouse.procurement import process_sales_order
from webshop.webshop.multi_warehouse.sources import (
	get_aggregate_stock,
	get_item_warehouse_sources,
	get_source_qty,
	is_enabled,
	resolve_target_warehouse,
)

ITEM = "MWTEST-ITEM"
ITEM_SINGLE = "MWTEST-ITEM-SINGLE"
STORE_LABEL = "Magasin"
SUPPLIER_LABEL = "Stock fournisseur"
SUPPLIER_NAME = "MWTEST Supplier"
CUSTOMER_NAME = "MWTEST Customer"
TEST_USER = "mwtest-customer@example.com"


def get_company():
	return (
		frappe.db.get_single_value("Webshop Settings", "company")
		or frappe.defaults.get_global_default("company")
		or frappe.db.get_value("Company", {}, "name")
	)


def get_abbr():
	return frappe.get_cached_value("Company", get_company(), "abbr")


def store_warehouse():
	return f"MWTEST Store - {get_abbr()}"


def supplier_warehouse():
	return f"MWTEST Supplier WH - {get_abbr()}"


def make_warehouse(warehouse_name):
	name = f"{warehouse_name} - {get_abbr()}"
	if not frappe.db.exists("Warehouse", name):
		frappe.get_doc(
			{
				"doctype": "Warehouse",
				"warehouse_name": warehouse_name,
				"company": get_company(),
			}
		).insert(ignore_permissions=True)
	return name


def get_leaf_item_group():
	# Some sites (nora app) forbid items in the root group: use a leaf group,
	# creating a dedicated test one when none exists.
	group = frappe.db.get_value("Item Group", {"is_group": 0}, "name")
	if group:
		return group
	root = frappe.db.get_value("Item Group", {"parent_item_group": ""}, "name")
	if not frappe.db.exists("Item Group", "MWTEST Group"):
		frappe.get_doc(
			{
				"doctype": "Item Group",
				"item_group_name": "MWTEST Group",
				"parent_item_group": root,
			}
		).insert(ignore_permissions=True)
	return "MWTEST Group"


def make_item(item_code, opening_supplier_stock=0):
	if not frappe.db.exists("Item", item_code):
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code,
				"item_name": item_code,
				"item_group": get_leaf_item_group(),
				"stock_uom": frappe.db.get_value("UOM", {}, "name") or "Nos",
				"is_stock_item": 1,
			}
		).insert(ignore_permissions=True)
	# The supplier source of the tests reads Item.opening_stock (standard
	# numeric field) as its quantity.
	frappe.db.set_value(
		"Item", item_code, "opening_stock", opening_supplier_stock, update_modified=False
	)

	if not frappe.db.exists("Website Item", {"item_code": item_code}):
		from webshop.webshop.doctype.website_item.website_item import make_website_item

		make_website_item(frappe.get_doc("Item", item_code), save=False).save(
			ignore_permissions=True
		)
	website_item = frappe.db.get_value("Website Item", {"item_code": item_code}, "name")
	frappe.db.set_value(
		"Website Item",
		website_item,
		{"website_warehouse": store_warehouse(), "published": 1},
		update_modified=False,
	)
	frappe.clear_document_cache("Website Item", website_item)
	return website_item


def make_supplier():
	if not frappe.db.exists("Supplier", SUPPLIER_NAME):
		frappe.get_doc(
			{
				"doctype": "Supplier",
				"supplier_name": SUPPLIER_NAME,
				"supplier_group": frappe.db.get_value("Supplier Group", {}, "name"),
			}
		).insert(ignore_permissions=True)
	return SUPPLIER_NAME


def make_customer_with_user():
	if not frappe.db.exists("Customer", CUSTOMER_NAME):
		frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": CUSTOMER_NAME,
				"customer_group": frappe.db.get_value(
					"Customer Group", {"is_group": 0}, "name"
				),
				"territory": frappe.db.get_value(
					"Territory", {"parent_territory": ""}, "name"
				),
			}
		).insert(ignore_permissions=True)

	if not frappe.db.exists("User", TEST_USER):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": TEST_USER,
				"first_name": "MWTEST",
				"user_type": "Website User",
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)

	if not frappe.db.exists("Contact", {"email_id": TEST_USER}):
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "MWTEST",
				"email_ids": [{"email_id": TEST_USER, "is_primary": 1}],
				"links": [{"link_doctype": "Customer", "link_name": CUSTOMER_NAME}],
			}
		)
		contact.insert(ignore_permissions=True)
	return CUSTOMER_NAME


class TestMultiWarehouseBase(unittest.TestCase):
	"""Shared environment: two sources (Store = Bin, Supplier = Item Field)."""

	def setUp(self):
		frappe.set_user("Administrator")
		make_warehouse("MWTEST Store")
		make_warehouse("MWTEST Supplier WH")
		make_supplier()
		make_item(ITEM, opening_supplier_stock=25)
		make_item(ITEM_SINGLE, opening_supplier_stock=0)
		make_customer_with_user()
		self.configure_settings()

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def configure_settings(self, **overrides):
		settings = frappe.get_doc("Webshop Settings")
		settings.enabled = 1
		if not settings.company:
			settings.company = get_company()
		if not settings.price_list:
			settings.price_list = frappe.db.get_value(
				"Price List", {"selling": 1, "enabled": 1}, "name"
			)
		if not settings.quotation_series:
			settings.quotation_series = frappe.get_meta("Quotation").get_options(
				"naming_series"
			).split("\n")[0]
		settings.allow_items_not_in_stock = 0
		settings.enable_multi_warehouse = 1
		settings.enable_supplier_procurement = 0
		settings.procurement_mode = "Purchase Order"
		settings.set("warehouse_sources", [])
		settings.append(
			"warehouse_sources",
			{
				"warehouse": store_warehouse(),
				"display_label": STORE_LABEL,
				"stock_basis": "Warehouse Bin",
				"lead_time_mode": "Fixed",
				"lead_time_days": 3,
			},
		)
		settings.append(
			"warehouse_sources",
			{
				"warehouse": supplier_warehouse(),
				"display_label": SUPPLIER_LABEL,
				"stock_basis": "Item Field",
				"stock_field": "opening_stock",
				"auto_enable_if_stock": 1,
				"is_supplier_source": 1,
				"supplier": SUPPLIER_NAME,
				"receiving_warehouse": store_warehouse(),
				"lead_time_mode": "Fixed",
				"lead_time_days": 15,
			},
		)
		for key, value in overrides.items():
			settings.set(key, value)
		settings.flags.ignore_mandatory = True
		settings.save(ignore_permissions=True)
		frappe.clear_document_cache("Webshop Settings", "Webshop Settings")

	def add_store_stock(self, qty, item_code=ITEM):
		from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry

		return make_stock_entry(
			item_code=item_code,
			target=store_warehouse(),
			qty=qty,
			basic_rate=42,
			company=get_company(),
		)

	def login_as_customer(self):
		frappe.set_user(TEST_USER)

	def get_cart(self):
		from webshop.webshop.shopping_cart.cart import _get_cart_quotation

		return _get_cart_quotation()


class TestDelays(unittest.TestCase):
	"""Pure date logic — no database involved."""

	def test_business_days_skip_weekends(self):
		friday = getdate("2026-08-28")
		self.assertEqual(add_business_days(friday, 1), getdate("2026-08-31"))  # Monday
		self.assertEqual(add_business_days(friday, 0), friday)
		saturday = getdate("2026-08-29")
		# A weekend start first rolls to Monday
		self.assertEqual(add_business_days(saturday, 0), getdate("2026-08-31"))
		self.assertEqual(add_business_days(getdate("2026-08-24"), 4), getdate("2026-08-28"))
		self.assertEqual(add_business_days(getdate("2026-08-24"), 5), getdate("2026-08-31"))

	def test_periodic_end_of_month(self):
		row = frappe._dict(
			lead_time_mode="Periodic",
			order_day="End of Month",
			receipt_lead_days=7,
			handling_days=2,
		)
		# Jérémy's example: on the 28th, the supplier order leaves on the 31st,
		# 7 business days of transit, 2 of handling.
		on_the_28th = getdate("2026-08-28")
		self.assertEqual(next_order_departure(row, on_the_28th), getdate("2026-08-31"))
		receipt = expected_receipt_date(row, on_the_28th)
		self.assertEqual(receipt, getdate("2026-09-09"))  # 31.08 + 7 business days
		delivery = estimate_delivery_date(row, on_the_28th)
		self.assertEqual(delivery, getdate("2026-09-11"))  # + 2 handling days

	def test_periodic_weekly_and_day_of_month(self):
		weekly = frappe._dict(
			lead_time_mode="Periodic", order_day="Weekly", order_weekday="Monday"
		)
		self.assertEqual(
			next_order_departure(weekly, getdate("2026-08-26")), getdate("2026-08-31")
		)
		self.assertEqual(
			next_order_departure(weekly, getdate("2026-08-31")), getdate("2026-08-31")
		)
		day_of_month = frappe._dict(
			lead_time_mode="Periodic", order_day="Day of Month", order_day_of_month=15
		)
		self.assertEqual(
			next_order_departure(day_of_month, getdate("2026-08-16")),
			getdate("2026-09-15"),
		)
		self.assertEqual(
			next_order_departure(day_of_month, getdate("2026-12-20")),
			getdate("2027-01-15"),
		)

	def test_fixed_estimate(self):
		row = frappe._dict(lead_time_mode="Fixed", lead_time_days=3)
		self.assertEqual(
			estimate_delivery_date(row, getdate("2026-08-24")), getdate("2026-08-27")
		)


class TestSourceResolution(TestMultiWarehouseBase):
	def test_feature_off_returns_nothing(self):
		self.configure_settings(enable_multi_warehouse=0)
		self.assertFalse(is_enabled())
		self.assertEqual(get_item_warehouse_sources(ITEM), [])
		self.assertIsNone(get_aggregate_stock(ITEM))

	def test_auto_mode_exposes_supplier_source_with_stock(self):
		sources = get_item_warehouse_sources(ITEM)
		self.assertEqual(len(sources), 2)
		self.assertEqual(sources[0].warehouse, store_warehouse())
		self.assertEqual(sources[0].label, STORE_LABEL)
		self.assertTrue(sources[0].is_primary)
		self.assertEqual(sources[1].warehouse, supplier_warehouse())
		self.assertEqual(sources[1].label, SUPPLIER_LABEL)
		self.assertEqual(sources[1].stock_qty, 25)
		self.assertTrue(sources[1].is_supplier_source)
		self.assertEqual(sources[1].lead_days, (getdate(add_business_days(nowdate(), 15)) - getdate(nowdate())).days)

	def test_auto_mode_hides_empty_supplier_source(self):
		# ITEM_SINGLE has no supplier stock: only the primary remains, and
		# product_info will not render a selector for a single source.
		sources = get_item_warehouse_sources(ITEM_SINGLE)
		self.assertEqual([s.warehouse for s in sources], [store_warehouse()])

	def test_item_mode_off_disables_sources(self):
		website_item = frappe.db.get_value("Website Item", {"item_code": ITEM}, "name")
		frappe.db.set_value(
			"Website Item", website_item, "warehouse_sources_mode", "Off"
		)
		frappe.clear_document_cache("Website Item", website_item)
		self.assertEqual(get_item_warehouse_sources(ITEM), [])

	def test_item_mode_custom_lists_explicit_sources(self):
		website_item_name = frappe.db.get_value(
			"Website Item", {"item_code": ITEM}, "name"
		)
		website_item = frappe.get_doc("Website Item", website_item_name)
		website_item.warehouse_sources_mode = "Custom"
		website_item.append(
			"additional_warehouse_sources", {"warehouse": supplier_warehouse()}
		)
		website_item.flags.ignore_permissions = True
		website_item.save()
		sources = get_item_warehouse_sources(ITEM)
		self.assertEqual(
			[s.warehouse for s in sources], [store_warehouse(), supplier_warehouse()]
		)

		# Custom without the line: primary only, even though supplier has stock
		website_item.set("additional_warehouse_sources", [])
		website_item.save()
		sources = get_item_warehouse_sources(ITEM)
		self.assertEqual([s.warehouse for s in sources], [store_warehouse()])

	def test_resolve_target_prefers_first_covering_source(self):
		# Store (Bin) is empty, supplier holds 25.
		self.assertEqual(resolve_target_warehouse(ITEM, 5), supplier_warehouse())
		# Nothing covers 100: fall back to the primary.
		self.assertEqual(resolve_target_warehouse(ITEM, 100), store_warehouse())

	def test_aggregate_stock_sums_sources(self):
		aggregate = get_aggregate_stock(ITEM)
		self.assertEqual(aggregate.stock_qty, 25)
		self.assertEqual(aggregate.in_stock, 1)

	def test_settings_validation(self):
		settings = frappe.get_doc("Webshop Settings")
		settings.warehouse_sources[1].stock_field = "does_not_exist"
		self.assertRaises(frappe.ValidationError, settings.save)
		settings.reload()

		settings.warehouse_sources[1].warehouse = store_warehouse()
		self.assertRaises(frappe.ValidationError, settings.save)
		settings.reload()

		# Activation set the two ERPNext prerequisites
		self.assertEqual(
			frappe.db.get_single_value("Selling Settings", "allow_multiple_items"), 1
		)
		self.assertEqual(
			frappe.db.get_single_value("Buying Settings", "allow_multiple_items"), 1
		)


class TestCartMultiSource(TestMultiWarehouseBase):
	def update_cart(self, **kwargs):
		from webshop.webshop.shopping_cart.cart import update_cart

		return update_cart(**kwargs)

	def test_two_lines_one_per_source(self):
		self.add_store_stock(4)
		self.login_as_customer()
		self.update_cart(item_code=ITEM, qty=2, warehouse=store_warehouse())
		self.update_cart(item_code=ITEM, qty=3, warehouse=supplier_warehouse())

		cart = self.get_cart()
		lines = [(d.item_code, d.warehouse, d.qty) for d in cart.items]
		self.assertEqual(len(lines), 2)
		self.assertIn((ITEM, store_warehouse(), 2), lines)
		self.assertIn((ITEM, supplier_warehouse(), 3), lines)

	def test_same_source_merges(self):
		self.add_store_stock(4)
		self.login_as_customer()
		self.update_cart(item_code=ITEM, qty=1, warehouse=store_warehouse())
		self.update_cart(
			item_code=ITEM, qty=2, warehouse=store_warehouse(), add_qty=True
		)
		cart = self.get_cart()
		self.assertEqual(len(cart.items), 1)
		self.assertEqual(cart.items[0].qty, 3)
		self.assertEqual(cart.items[0].warehouse, store_warehouse())

	def test_remove_only_targeted_source(self):
		self.add_store_stock(4)
		self.login_as_customer()
		self.update_cart(item_code=ITEM, qty=2, warehouse=store_warehouse())
		self.update_cart(item_code=ITEM, qty=3, warehouse=supplier_warehouse())
		self.update_cart(item_code=ITEM, qty=0, warehouse=supplier_warehouse())

		cart = self.get_cart()
		self.assertEqual(len(cart.items), 1)
		self.assertEqual(cart.items[0].warehouse, store_warehouse())

	def test_auto_pick_covers_quantity(self):
		# Store holds 2, supplier 25. Asking 5 without a source must land on
		# the supplier line ("switch entirely to the source that covers").
		self.add_store_stock(2)
		self.login_as_customer()
		self.update_cart(item_code=ITEM, qty=5)
		cart = self.get_cart()
		self.assertEqual(len(cart.items), 1)
		self.assertEqual(cart.items[0].warehouse, supplier_warehouse())

	def test_implicit_add_keeps_existing_source(self):
		self.add_store_stock(4)
		self.login_as_customer()
		self.update_cart(item_code=ITEM, qty=1, warehouse=store_warehouse())
		# Implicit +1 (grid button) must feed the existing store line, not
		# open a supplier one.
		self.update_cart(item_code=ITEM, qty=1, add_qty=True)
		cart = self.get_cart()
		self.assertEqual(len(cart.items), 1)
		self.assertEqual(cart.items[0].warehouse, store_warehouse())
		self.assertEqual(cart.items[0].qty, 2)

	def test_source_stock_validation(self):
		self.add_store_stock(2)
		self.login_as_customer()
		self.assertRaises(
			frappe.ValidationError,
			self.update_cart,
			item_code=ITEM,
			qty=3,
			warehouse=store_warehouse(),
		)
		# Unknown source refused
		self.assertRaises(
			frappe.ValidationError,
			self.update_cart,
			item_code=ITEM,
			qty=1,
			warehouse="Nonexistent - XX",
		)

	def test_decorate_preserves_line_source(self):
		from webshop.webshop.shopping_cart.cart import get_cart_quotation

		self.add_store_stock(4)
		self.login_as_customer()
		self.update_cart(item_code=ITEM, qty=3, warehouse=supplier_warehouse())
		context = get_cart_quotation()
		line = context["doc"].items[0]
		self.assertEqual(line.warehouse, supplier_warehouse())
		self.assertEqual(line.warehouse_source_label, SUPPLIER_LABEL)
		self.assertTrue(line.delivery_lead_days)

	def test_feature_off_keeps_historical_behaviour(self):
		self.configure_settings(enable_multi_warehouse=0, allow_items_not_in_stock=1)
		self.login_as_customer()
		# warehouse param is ignored, the single website_warehouse is applied
		self.update_cart(item_code=ITEM, qty=1, warehouse=supplier_warehouse())
		self.update_cart(item_code=ITEM, qty=2)
		cart = self.get_cart()
		self.assertEqual(len(cart.items), 1)
		self.assertEqual(cart.items[0].warehouse, store_warehouse())
		self.assertEqual(cart.items[0].qty, 2)


class TestProcurement(TestMultiWarehouseBase):
	def make_webshop_sales_order(self, qty=3, submit=True):
		sales_order = frappe.get_doc(
			{
				"doctype": "Sales Order",
				"customer": CUSTOMER_NAME,
				"company": get_company(),
				"order_type": "Shopping Cart",
				"transaction_date": nowdate(),
				"delivery_date": add_days(nowdate(), 30),
				"items": [
					{
						"item_code": ITEM,
						"qty": qty,
						"rate": 42,
						"warehouse": supplier_warehouse(),
						"delivery_date": add_days(nowdate(), 30),
					}
				],
			}
		)
		sales_order.flags.ignore_permissions = True
		sales_order.insert()
		if submit:
			sales_order.submit()
		return sales_order

	def get_webshop_po(self):
		po_name = frappe.db.get_value(
			"Purchase Order",
			{"docstatus": 0, "supplier": SUPPLIER_NAME, "neo_webshop_generated": 1},
			"name",
		)
		return frappe.get_doc("Purchase Order", po_name) if po_name else None

	def ensure_marker_field(self):
		from webshop.patches.add_webshop_po_marker_field import execute

		execute()
		frappe.clear_cache(doctype="Purchase Order")

	def test_po_draft_created_with_traceability(self):
		self.ensure_marker_field()
		self.configure_settings(enable_supplier_procurement=1)
		sales_order = self.make_webshop_sales_order(qty=3)

		po = self.get_webshop_po()
		self.assertIsNotNone(po, "a draft PO should have been prepared")
		self.assertEqual(po.docstatus, 0)
		line = po.items[-1]
		self.assertEqual(line.item_code, ITEM)
		self.assertEqual(line.qty, 3)
		self.assertEqual(line.sales_order, sales_order.name)
		self.assertEqual(
			line.sales_order_item, sales_order.items[0].name
		)
		self.assertEqual(line.warehouse, store_warehouse())  # receiving warehouse
		self.assertEqual(
			getdate(line.schedule_date), add_business_days(nowdate(), 15)
		)

	def test_second_order_stacks_into_same_po(self):
		self.ensure_marker_field()
		self.configure_settings(enable_supplier_procurement=1)
		self.make_webshop_sales_order(qty=3)
		po_first = self.get_webshop_po()
		self.make_webshop_sales_order(qty=2)
		po_second = self.get_webshop_po()

		self.assertEqual(po_first.name, po_second.name)
		self.assertEqual(len(po_second.items), len(po_first.items) + 1)

	def test_procurement_is_idempotent(self):
		self.ensure_marker_field()
		self.configure_settings(enable_supplier_procurement=1)
		sales_order = self.make_webshop_sales_order(qty=3)
		po = self.get_webshop_po()
		lines_before = len(po.items)

		# Re-processing the same order (e.g. hook fired twice) adds nothing
		process_sales_order(sales_order)
		po.reload()
		self.assertEqual(len(po.items), lines_before)

	def test_store_lines_do_not_procure(self):
		self.ensure_marker_field()
		self.configure_settings(enable_supplier_procurement=1)
		self.add_store_stock(5)
		sales_order = frappe.get_doc(
			{
				"doctype": "Sales Order",
				"customer": CUSTOMER_NAME,
				"company": get_company(),
				"order_type": "Shopping Cart",
				"transaction_date": nowdate(),
				"delivery_date": add_days(nowdate(), 30),
				"items": [
					{
						"item_code": ITEM,
						"qty": 2,
						"rate": 42,
						"warehouse": store_warehouse(),
						"delivery_date": add_days(nowdate(), 30),
					}
				],
			}
		)
		sales_order.flags.ignore_permissions = True
		sales_order.insert()
		sales_order.submit()
		self.assertIsNone(self.get_webshop_po())

	def test_non_webshop_orders_are_ignored(self):
		self.ensure_marker_field()
		self.configure_settings(enable_supplier_procurement=1)
		sales_order = frappe.get_doc(
			{
				"doctype": "Sales Order",
				"customer": CUSTOMER_NAME,
				"company": get_company(),
				"order_type": "Sales",
				"transaction_date": nowdate(),
				"delivery_date": add_days(nowdate(), 30),
				"items": [
					{
						"item_code": ITEM,
						"qty": 2,
						"rate": 42,
						"warehouse": supplier_warehouse(),
						"delivery_date": add_days(nowdate(), 30),
					}
				],
			}
		)
		sales_order.flags.ignore_permissions = True
		sales_order.insert()
		sales_order.submit()
		self.assertIsNone(self.get_webshop_po())

	def test_material_request_mode(self):
		self.configure_settings(
			enable_supplier_procurement=1, procurement_mode="Material Request"
		)
		sales_order = self.make_webshop_sales_order(qty=3)

		mr_item = frappe.db.get_value(
			"Material Request Item",
			{"sales_order_item": sales_order.items[0].name},
			["parent", "sales_order", "qty", "warehouse"],
			as_dict=True,
		)
		self.assertIsNotNone(mr_item, "a Material Request line should exist")
		self.assertEqual(mr_item.sales_order, sales_order.name)
		self.assertEqual(mr_item.qty, 3)
		self.assertEqual(mr_item.warehouse, store_warehouse())
		mr = frappe.get_doc("Material Request", mr_item.parent)
		self.assertEqual(mr.docstatus, 1)
		self.assertEqual(mr.material_request_type, "Purchase")

	def test_procurement_never_blocks_the_order(self):
		# Break the supplier on purpose: the order must still submit, the
		# failure must land in the Error Log.
		self.ensure_marker_field()
		self.configure_settings(enable_supplier_procurement=1)
		settings = frappe.get_doc("Webshop Settings")
		settings.warehouse_sources[1].supplier = None
		settings.flags.ignore_mandatory = True
		settings.save(ignore_permissions=True)
		frappe.clear_document_cache("Webshop Settings", "Webshop Settings")

		sales_order = self.make_webshop_sales_order(qty=3)
		self.assertEqual(sales_order.docstatus, 1)
		self.assertIsNone(self.get_webshop_po())


class TestHolidays(TestMultiWarehouseBase):
	HOLIDAY_LIST = "MWTEST Holidays"

	def make_holiday_list(self, dates):
		if frappe.db.exists("Holiday List", self.HOLIDAY_LIST):
			frappe.delete_doc(
				"Holiday List", self.HOLIDAY_LIST, force=True, ignore_permissions=True
			)
		frappe.get_doc(
			{
				"doctype": "Holiday List",
				"holiday_list_name": self.HOLIDAY_LIST,
				"from_date": "2026-01-01",
				"to_date": "2026-12-31",
				"holidays": [
					{"holiday_date": d, "description": "MWTEST"} for d in dates
				],
			}
		).insert(ignore_permissions=True)
		frappe.db.set_single_value(
			"Webshop Settings", "delivery_holiday_list", self.HOLIDAY_LIST
		)
		frappe.clear_document_cache("Webshop Settings", "Webshop Settings")
		frappe.local.webshop_delivery_holidays = None

	def tearDown(self):
		frappe.local.webshop_delivery_holidays = None
		super().tearDown()

	def test_business_days_skip_holidays(self):
		# Monday 2026-08-31 is a holiday: one business day from Friday 28.08
		# lands on Tuesday 01.09 instead of Monday.
		self.make_holiday_list(["2026-08-31"])
		self.assertEqual(
			add_business_days(getdate("2026-08-28"), 1), getdate("2026-09-01")
		)

	def test_holiday_start_rolls_forward(self):
		self.make_holiday_list(["2026-08-31"])
		self.assertEqual(
			add_business_days(getdate("2026-08-31"), 0), getdate("2026-09-01")
		)

	def test_no_holiday_list_keeps_weekends_only(self):
		frappe.db.set_single_value("Webshop Settings", "delivery_holiday_list", None)
		frappe.clear_document_cache("Webshop Settings", "Webshop Settings")
		frappe.local.webshop_delivery_holidays = None
		self.assertEqual(
			add_business_days(getdate("2026-08-28"), 1), getdate("2026-08-31")
		)


class TestSourceVisibility(TestMultiWarehouseBase):
	def set_supplier_visibility(self, visibility):
		settings = frappe.get_doc("Webshop Settings")
		settings.warehouse_sources[1].visibility = visibility
		settings.flags.ignore_mandatory = True
		settings.save(ignore_permissions=True)
		frappe.clear_document_cache("Webshop Settings", "Webshop Settings")

	def set_site_profile(self, b2b_only):
		frappe.local.website_profile_doc = frappe._dict({"b2b_only": b2b_only})

	def tearDown(self):
		frappe.local.website_profile_doc = None
		super().tearDown()

	def test_b2b_only_source_hidden_on_public_site(self):
		self.set_supplier_visibility("B2B sites only")
		self.set_site_profile(b2b_only=0)
		self.assertEqual(
			[s.warehouse for s in get_item_warehouse_sources(ITEM)], [store_warehouse()]
		)
		self.set_site_profile(b2b_only=1)
		self.assertEqual(
			[s.warehouse for s in get_item_warehouse_sources(ITEM)],
			[store_warehouse(), supplier_warehouse()],
		)

	def test_public_only_source_hidden_on_b2b_site(self):
		self.set_supplier_visibility("Public sites only")
		self.set_site_profile(b2b_only=1)
		self.assertEqual(
			[s.warehouse for s in get_item_warehouse_sources(ITEM)], [store_warehouse()]
		)

	def test_no_profile_shows_everything(self):
		self.set_supplier_visibility("B2B sites only")
		frappe.local.website_profile_doc = None
		self.assertEqual(len(get_item_warehouse_sources(ITEM)), 2)

	def test_hidden_source_still_resolves_for_existing_lines(self):
		# A line already placed on a source hidden here must keep its label,
		# lead time and supplier (procurement and cart rendering).
		from webshop.webshop.multi_warehouse.sources import get_source_for_warehouse

		self.set_supplier_visibility("B2B sites only")
		self.set_site_profile(b2b_only=0)
		row = get_source_for_warehouse(supplier_warehouse())
		self.assertIsNotNone(row)
		self.assertEqual(row.display_label, SUPPLIER_LABEL)


class TestBulkSourceAction(TestMultiWarehouseBase):
	def get_mode_and_sources(self, item_code=ITEM):
		name = frappe.db.get_value("Website Item", {"item_code": item_code}, "name")
		doc = frappe.get_doc("Website Item", name)
		return doc.warehouse_sources_mode, [
			d.warehouse for d in doc.get("additional_warehouse_sources") or []
		]

	def test_bulk_add_and_remove(self):
		from webshop.webshop.multi_warehouse.sources import bulk_set_item_source

		names = [
			frappe.db.get_value("Website Item", {"item_code": code}, "name")
			for code in (ITEM, ITEM_SINGLE)
		]

		result = bulk_set_item_source(names, supplier_warehouse(), "add")
		self.assertEqual(result["updated"], 2)
		for code in (ITEM, ITEM_SINGLE):
			mode, sources = self.get_mode_and_sources(code)
			self.assertEqual(mode, "Custom")
			self.assertIn(supplier_warehouse(), sources)

		# ITEM_SINGLE has no supplier stock but is now explicitly listed:
		# Custom mode shows the source regardless of stock.
		self.assertEqual(
			[s.warehouse for s in get_item_warehouse_sources(ITEM_SINGLE)],
			[store_warehouse(), supplier_warehouse()],
		)

		result = bulk_set_item_source(names, supplier_warehouse(), "remove")
		self.assertEqual(result["updated"], 2)
		mode, sources = self.get_mode_and_sources(ITEM)
		self.assertEqual(mode, "Custom")
		self.assertNotIn(supplier_warehouse(), sources)
		self.assertEqual(
			[s.warehouse for s in get_item_warehouse_sources(ITEM)], [store_warehouse()]
		)

	def test_bulk_refuses_unknown_warehouse(self):
		from webshop.webshop.multi_warehouse.sources import bulk_set_item_source

		name = frappe.db.get_value("Website Item", {"item_code": ITEM}, "name")
		self.assertRaises(
			frappe.ValidationError, bulk_set_item_source, [name], "Nope - XX", "add"
		)

	def test_configured_sources_listing(self):
		from webshop.webshop.multi_warehouse.sources import get_configured_sources

		listing = get_configured_sources()
		self.assertEqual(
			[s["warehouse"] for s in listing],
			[store_warehouse(), supplier_warehouse()],
		)
		self.assertEqual(listing[1]["label"], SUPPLIER_LABEL)
		self.assertEqual(listing[1]["is_supplier_source"], 1)


class TestReceiptNotification(TestMultiWarehouseBase):
	def test_receipt_comments_the_sales_order(self):
		from webshop.patches.add_webshop_po_marker_field import execute

		execute()
		frappe.clear_cache(doctype="Purchase Order")
		self.configure_settings(enable_supplier_procurement=1)

		sales_order = frappe.get_doc(
			{
				"doctype": "Sales Order",
				"customer": CUSTOMER_NAME,
				"company": get_company(),
				"order_type": "Shopping Cart",
				"transaction_date": nowdate(),
				"delivery_date": add_days(nowdate(), 30),
				"items": [
					{
						"item_code": ITEM,
						"qty": 3,
						"rate": 42,
						"warehouse": supplier_warehouse(),
						"delivery_date": add_days(nowdate(), 30),
					}
				],
			}
		)
		sales_order.flags.ignore_permissions = True
		sales_order.insert()
		sales_order.submit()

		po_name = frappe.db.get_value(
			"Purchase Order",
			{"docstatus": 0, "supplier": SUPPLIER_NAME, "neo_webshop_generated": 1},
			"name",
		)
		self.assertIsNotNone(po_name)

		po = frappe.get_doc("Purchase Order", po_name)
		for item in po.items:
			item.rate = 20
		po.flags.ignore_permissions = True
		po.save()
		po.submit()

		from erpnext.buying.doctype.purchase_order.purchase_order import (
			make_purchase_receipt,
		)

		receipt = make_purchase_receipt(po.name)
		receipt.flags.ignore_permissions = True
		receipt.insert()
		receipt.submit()

		# The receipt line kept the traceability to the customer order line…
		receipt.reload()
		self.assertEqual(receipt.items[0].sales_order, sales_order.name)
		self.assertEqual(receipt.items[0].sales_order_item, sales_order.items[0].name)

		# …and the seller side was told.
		comments = frappe.get_all(
			"Comment",
			filters={
				"reference_doctype": "Sales Order",
				"reference_name": sales_order.name,
				"comment_type": "Info",
			},
			pluck="content",
		)
		self.assertTrue(
			any(receipt.name in (c or "") for c in comments),
			f"no receipt comment on the Sales Order, got: {comments}",
		)


class TestStockBasisBin(TestMultiWarehouseBase):
	def test_bin_source_reads_real_stock(self):
		self.add_store_stock(5)
		settings = frappe.get_cached_doc("Webshop Settings")
		store_row = settings.warehouse_sources[0]
		self.assertEqual(get_source_qty(ITEM, store_row), 5)

	def test_item_field_source_reads_item_field(self):
		settings = frappe.get_cached_doc("Webshop Settings")
		supplier_row = settings.warehouse_sources[1]
		self.assertEqual(get_source_qty(ITEM, supplier_row), 25)
		frappe.db.set_value("Item", ITEM, "opening_stock", 0, update_modified=False)
		self.assertEqual(get_source_qty(ITEM, supplier_row), 0)


class TestPlaceOrderDeliveryDates(TestMultiWarehouseBase):
	def test_delivery_dates_follow_sources(self):
		from webshop.webshop.shopping_cart.cart import _set_delivery_dates_from_sources

		sales_order = frappe.get_doc(
			{
				"doctype": "Sales Order",
				"customer": CUSTOMER_NAME,
				"company": get_company(),
				"order_type": "Shopping Cart",
				"transaction_date": nowdate(),
				"items": [
					{
						"item_code": ITEM,
						"qty": 1,
						"rate": 42,
						"warehouse": store_warehouse(),
					},
					{
						"item_code": ITEM,
						"qty": 2,
						"rate": 42,
						"warehouse": supplier_warehouse(),
					},
				],
			}
		)
		_set_delivery_dates_from_sources(sales_order)

		store_line, supplier_line = sales_order.items
		self.assertEqual(
			getdate(store_line.delivery_date), add_business_days(nowdate(), 3)
		)
		self.assertEqual(
			getdate(supplier_line.delivery_date), add_business_days(nowdate(), 15)
		)
		# Header takes the latest line
		self.assertEqual(
			getdate(sales_order.delivery_date), getdate(supplier_line.delivery_date)
		)
