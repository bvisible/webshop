# //// Neoffice — added file (second-hand feature, no upstream equivalent).
"""Second-hand units: the one-click creation, the mirror to the shop, the facet.

Everything a test creates is rolled back by FrappeTestCase; the only thing
that survives a rollback is the Webshop Settings row this class may add to
`filter_fields`, which tearDownClass removes again.
"""

import importlib.util
import re
from pathlib import Path
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
		cls.purge_items()
		restore_webshop_settings(cls.snapshot)
		if cls.added_filter_row:
			settings = frappe.get_single("Webshop Settings")
			settings.filter_fields = [r for r in settings.filter_fields if r.fieldname != "item_condition"]
			settings.flags.ignore_permissions = True
			settings.flags.ignore_mandatory = True
			settings.save()
			frappe.db.commit()
		super().tearDownClass()

	@classmethod
	def purge_items(cls):
		"""What a rollback should have taken away, in case something committed
		on the way (a stock entry, a website item)."""
		frappe.db.rollback()
		codes = [r[0] for r in frappe.db.sql("select name from tabItem where name like %s", (f"{PREFIX} %% {cls.suffix}%",))]
		for code in sorted(codes, key=lambda c: "-USED-" not in c):
			try:
				for name in frappe.get_all("Website Item", filters={"item_code": code}, pluck="name"):
					frappe.delete_doc("Website Item", name, force=True, ignore_permissions=True)
				frappe.db.delete("Item Price", {"item_code": code})
				for se in frappe.get_all("Stock Entry Detail", filters={"item_code": code}, pluck="parent", distinct=True):
					doc = frappe.get_doc("Stock Entry", se)
					if doc.docstatus == 1:
						doc.flags.ignore_permissions = True
						doc.cancel()
					frappe.delete_doc("Stock Entry", se, force=True, ignore_permissions=True)
				frappe.db.delete("Bin", {"item_code": code})
				frappe.delete_doc("Item", code, force=True, ignore_permissions=True)
				frappe.db.commit()
			except Exception:
				frappe.db.rollback()

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

	# --- sold means gone (2026-09-14) -------------------------------------------

	def publish_with_route(self, source):
		"""The new model's page, with a route: a fresh site's item group may give it none, and a
		page without a route can neither be linked nor redirected to."""
		name, _title = make_website_item(source)
		if not frappe.db.get_value("Website Item", name, "route"):
			frappe.db.set_value("Website Item", name, "route", "products/" + frappe.scrub(source.name).replace("_", "-"))
		return name

	def _issue(self, item_code, qty=1):
		"""The unit leaves the shop's warehouse: a sale, seen from the stock ledger."""
		from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry

		return make_stock_entry(item_code=item_code, source=self.warehouse, qty=qty, do_not_save=False)

	def _receive(self, item_code, qty=1, rate=10):
		from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry

		return make_stock_entry(item_code=item_code, target=self.warehouse, qty=qty, basic_rate=rate, do_not_save=False)

	def test_a_sold_unit_leaves_the_catalogue_and_comes_back_with_its_stock(self):
		if not self.warehouse:
			self.fail("no leaf warehouse on this site")
		source = self.make_source("Speaker", is_stock_item=1)
		self.publish_with_route(source)
		result = used_items.create_used_unit(
			source.name, price=50, qty=1, cost=10, warehouse=self.warehouse, publish=1, price_list=self.price_list
		)
		page = result["website_item"]
		self.assertEqual(frappe.db.get_value("Website Item", page, "sold"), 0)
		self.assertIn(result["item_code"], [u.item_code for u in used_items.get_used_units(source.name)])

		# the unit is sold: the stock ledger withdraws it
		self._issue(result["item_code"])
		self.assertEqual(frappe.db.get_value("Website Item", page, "sold"), 1)
		self.assertNotIn(result["item_code"], [u.item_code for u in used_items.get_used_units(source.name)])
		from webshop.webshop.product_data_engine.listing_context import count_second_hand
		from webshop.webshop.product_data_engine.query import ProductQuery

		self.assertIn(["sold", "=", 0], ProductQuery().filters)
		self.assertNotIn(page, frappe.get_all("Website Item", filters={"published": 1, "sold": 0, "item_code": result["item_code"]}, pluck="name"))
		self.assertGreaterEqual(count_second_hand(), 0)

		# its page sends the visitor to the new model — the published page with a route, the one
		# get_new_model links (a fresh site may hold a second, route-less page for the same item)
		new_model_route = frappe.db.get_value(
			"Website Item", {"item_code": source.name, "published": 1, "route": ("is", "set")}, "route"
		)
		self.assertTrue(new_model_route, "the new model has a published page with a route")
		doc = frappe.get_doc("Website Item", page)
		with self.assertRaises(frappe.Redirect):
			doc.get_context(frappe._dict(route=doc.route))
		self.assertEqual(frappe.local.flags.redirect_location, "/" + new_model_route)
		frappe.local.flags.redirect_location = None

		# a return puts it back on sale
		self._receive(result["item_code"])
		self.assertEqual(frappe.db.get_value("Website Item", page, "sold"), 0)

	def test_a_new_item_is_never_sold(self):
		source = self.make_source("Kettle", is_stock_item=1)
		name, _title = make_website_item(source)
		self.assertEqual(frappe.db.get_value("Website Item", name, "sold"), 0)
		# no stock at all, still listed: "sold" is a used unit's word
		self.assertEqual(used_items.sold_flag(frappe.get_doc("Website Item", name)), 0)

	def test_a_unit_on_hand_where_the_shop_does_not_look_is_not_sold(self):
		"""On hand but not where the shop's stock rule looks (no website warehouse, or a
		warehouse it does not expose) is out of stock on the page, not sold: the first version
		hid such a unit and redirected its page (osiris, 2026-09-14)."""
		if not self.warehouse:
			self.fail("no leaf warehouse on this site")
		source = self.make_source("Radio", is_stock_item=1)
		self.publish_with_route(source)
		result = used_items.create_used_unit(
			source.name, price=50, qty=1, cost=10, warehouse=self.warehouse, publish=1, price_list=self.price_list
		)
		page = result["website_item"]
		frappe.db.set_value("Website Item", page, "website_warehouse", None)
		self.assertEqual(used_items.refresh_sold_flag(page), 0)
		self.assertEqual(frappe.db.get_value("Website Item", page, "sold"), 0)

	def test_an_order_holding_the_unit_sells_it_and_its_cancellation_brings_it_back(self):
		"""A unit an order reserves is sold when the order is placed, not when it ships."""
		if not self.warehouse:
			self.fail("no leaf warehouse on this site")
		source = self.make_source("Amplifier", is_stock_item=1)
		self.publish_with_route(source)
		result = used_items.create_used_unit(
			source.name, price=50, qty=1, cost=10, warehouse=self.warehouse, publish=1, price_list=self.price_list
		)
		page, unit = result["website_item"], result["item_code"]
		order = frappe._dict(doctype="Sales Order", items=[frappe._dict(item_code=unit)])
		bin_name = frappe.db.get_value("Bin", {"item_code": unit, "warehouse": self.warehouse})
		self.assertTrue(bin_name, "the unit's receipt made a bin")
		# what Sales Order.on_submit leaves behind before its hooks run: the unit reserved
		frappe.db.set_value("Bin", bin_name, "reserved_qty", 1)
		used_items.on_sales_order_change(order, "on_submit")
		self.assertEqual(frappe.db.get_value("Website Item", page, "sold"), 1)
		# and what on_cancel leaves: the reservation released
		frappe.db.set_value("Bin", bin_name, "reserved_qty", 0)
		used_items.on_sales_order_change(order, "on_cancel")
		self.assertEqual(frappe.db.get_value("Website Item", page, "sold"), 0)

	def test_a_sold_unit_is_left_out_of_every_surface_that_offers_products(self):
		"""The listing left sold units out from the start; the search, the quick order, the
		carousels and the category cards did not (2026-09-14)."""
		if not self.warehouse:
			self.fail("no leaf warehouse on this site")
		source = self.make_source("Turntable", is_stock_item=1)
		self.publish_with_route(source)
		result = used_items.create_used_unit(
			source.name, price=50, qty=1, cost=10, warehouse=self.warehouse, publish=1, price_list=self.price_list
		)
		page, unit = result["website_item"], result["item_code"]
		self._issue(unit)
		self.assertEqual(frappe.db.get_value("Website Item", page, "sold"), 1)

		from webshop.templates.pages.product_search import get_product_data
		from webshop.webshop.quick_order.api import sellable_website_item
		from webshop.webshop.utils.product_carousel_helper import get_carousel_items

		self.assertIsNone(sellable_website_item(unit))
		self.assertNotIn(unit, [row.item_code for row in get_product_data(unit, 0, 50)])
		group = frappe.db.get_value("Website Item", page, "item_group")
		carousel = get_carousel_items(item_group=group, limit=100, use_cache=False) or []
		self.assertNotIn(unit, [row.get("item_code") for row in carousel])

		path = Path(__file__).resolve().parents[2] / "www" / "shop-by-category" / "index.py"
		spec = importlib.util.spec_from_file_location("webshop_shop_by_category_sold", path)
		module = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(module)
		self.assertEqual(module._visible_item_filters().get("sold"), 0)

	def test_the_new_model_and_the_siblings_are_seen_from_a_used_unit(self):
		if not self.warehouse:
			self.fail("no leaf warehouse on this site")
		source = self.make_source("Camera", is_stock_item=1)
		self.publish_with_route(source)
		first = used_items.create_used_unit(
			source.name, price=80, qty=1, cost=10, warehouse=self.warehouse, publish=1, price_list=self.price_list
		)
		second = used_items.create_used_unit(
			source.name, price=70, qty=1, cost=10, warehouse=self.warehouse, publish=1, price_list=self.price_list
		)
		page = frappe.get_doc("Website Item", first["website_item"])

		model = used_items.get_new_model(page)
		self.assertEqual(model.item_code, source.name)
		self.assertEqual(model.price, 100)
		self.assertTrue(model.formatted_price)
		self.assertEqual(model.route, frappe.db.get_value("Website Item", {"item_code": source.name}, "route"))
		self.assertEqual(used_items.condition_info(page).reference.name, model.name)

		siblings = used_items.get_sibling_units(page)
		self.assertEqual([u.item_code for u in siblings], [second["item_code"]])
		# the second unit sees the first one, and not itself
		other = frappe.get_doc("Website Item", second["website_item"])
		self.assertEqual([u.item_code for u in used_items.get_sibling_units(other)], [first["item_code"]])

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


class TestEveryOfferReadsSold(FrappeTestCase):
	"""Every query that offers Website Items to a shopper reads `sold` next to `published`. A
	sold unit left the listing from the start and stayed in the search, the quick order, the
	carousels, the recommendations, the facets' counts and the category cards (2026-09-14)."""

	SOURCES = (
		"webshop/product_data_engine/filters.py",
		"templates/pages/product_search.py",
		"webshop/legacy_search.py",
		"webshop/quick_order/api.py",
		"www/shop-by-category/index.py",
		"webshop/utils/brand_carousel_helper.py",
		"webshop/utils/product_carousel_helper.py",
		"webshop/utils/frequently_bought_together.py",
		"webshop/utils/discount_query.py",
		"webshop/doctype/website_item/website_item.py",
		"www/sitemap_products.py",
	)
	# queries on published that offer nothing to a shopper
	NOT_OFFERS = (
		# narrows a query whose own WHERE reads sold
		'exact_match = frappe.db.exists("Website Item", {"item_code": cstr(search), "published": 1})',
		# the pairs "bought together" computes; the query that shows them reads sold
		"AND wi1.published = 1",
		"AND wi2.published = 1",
		# the parts of a bundle, listed on the bundle's own page
		'_wi_filters = {"item_code": bundle_item.item_code, "published": 1}',
	)

	def test_every_query_offering_products_reads_sold(self):
		app = Path(__file__).resolve().parents[2]
		published = re.compile(r'published\s*(?:=|==)\s*1|"published":\s*1')
		missing = []
		for rel in self.SOURCES:
			lines = (app / rel).read_text().splitlines()
			# a comment saying "sold" is not a query reading it
			code = [re.split(r"\s#\s|\s--\s", line)[0] if not line.strip().startswith(("#", "--")) else "" for line in lines]
			for i, line in enumerate(lines):
				if not published.search(code[i]) or line.strip() in self.NOT_OFFERS:
					continue
				if not any("sold" in near for near in code[max(0, i - 2) : i + 3]):
					missing.append(f"{rel}:{i + 1}: {line.strip()}")
		self.assertEqual(missing, [], "\n" + "\n".join(missing))
