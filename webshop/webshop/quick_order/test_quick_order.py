# //// Neoffice — added file (the quick order, no upstream equivalent).
# //// Neoffice — reworded (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): who may be here now follows the cart's own rule (any signed-in customer, plus a visitor where the shop sells to visitors), not the reseller-only gate the module's docstring used to describe.
"""The quick order, from the gate to the cart.

A model with two attributes and six variants is built once, published, priced
on the shop's list and on a reseller list. Who may be here follows the cart's
own rule — any signed-in customer, and a visitor where the shop sells to
visitors — checked through an in-memory copy of Webshop Settings and a fake
Website Profile on frappe.local, so nothing is written to the Single. The cart
is exercised for real: the batch endpoint saves the customer's quotation once
and reports what it kept.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
# //// Neoffice — added flt import, used by the new price-list and order-export tests (6696be727a "feat(quick-order): le prix du client, et la commande en Excel")
from frappe.utils import flt

from webshop.webshop.doctype.website_item.website_item import make_website_item
from webshop.webshop.quick_order import api
from webshop.webshop.tests.utils import (
	PREFIX,
	default_company,
	ensure_shop_settings,
	make_test_item,
	portal_customer,
	selling_price_list,
)

TEMPLATE = f"{PREFIX} QO Shirt"
COLOUR = f"{PREFIX} Colour"
SIZE = f"{PREFIX} Size"
BARCODE = "WSTESTQO0001"
RESELLER_LIST = f"{PREFIX} QO Reseller"
USER = "wstest-quick-order@example.com"
CUSTOMER = f"{PREFIX} Quick Order Shop"
PLAIN_USER = "wstest-quick-order-plain@example.com"
PLAIN_CUSTOMER = f"{PREFIX} Quick Order Plain"
# //// Neoffice — added (27e93f3c "fix(quick-order): la CI sur ERPNext standard — tarification au
# nom du client et deux tests mal posés"): the reseller now gets its own Customer Group and
# LOOSE_ITEM is created once in setUpClass instead of from the customer's own session.
RESELLER_GROUP = f"{PREFIX} QO Resellers"
LOOSE_ITEM = f"{PREFIX} QO Loose"


def _attribute(name, values):
	if frappe.db.exists("Item Attribute", name):
		return
	frappe.get_doc(
		{
			"doctype": "Item Attribute",
			"attribute_name": name,
			"item_attribute_values": [{"attribute_value": v, "abbr": v[:3].upper()} for v in values],
		}
	).insert(ignore_permissions=True)


class TestQuickOrder(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.settings_written = ensure_shop_settings()
		cls.purge()
		_attribute(COLOUR, ["Noir", "Blanc"])
		_attribute(SIZE, ["S", "M", "L"])
		template = make_test_item(
			TEMPLATE,
			item_name="Chemise de test",
			has_variants=1,
			is_stock_item=0,
			attributes=[{"attribute": COLOUR}, {"attribute": SIZE}],
		)
		from erpnext.controllers.item_variant import create_variant

		cls.variants = {}
		for colour in ("Noir", "Blanc"):
			for size in ("S", "M", "L"):
				variant = create_variant(template.name, {COLOUR: colour, SIZE: size})
				variant.is_stock_item = 0
				variant.insert(ignore_permissions=True)
				cls.variants[(colour, size)] = variant.name
		# a barcode on one variant, an EAN-free code so ERPNext does not check a checksum
		noir_m = frappe.get_doc("Item", cls.variants[("Noir", "M")])
		noir_m.append("barcodes", {"barcode": BARCODE})
		noir_m.save(ignore_permissions=True)

		make_website_item(template)
		website_item = frappe.get_doc("Website Item", {"item_code": template.name})
		website_item.published = 1
		website_item.save(ignore_permissions=True)
		cls.website_item = website_item.name

		price_list = selling_price_list()
		if not frappe.db.exists("Price List", RESELLER_LIST):
			frappe.get_doc(
				{
					"doctype": "Price List",
					"price_list_name": RESELLER_LIST,
					"selling": 1,
					"enabled": 1,
					"currency": frappe.db.get_value("Price List", price_list, "currency"),
				}
			).insert(ignore_permissions=True)
		for code in cls.variants.values():
			if not frappe.db.exists("Item Price", {"item_code": code, "price_list": price_list}):
				frappe.get_doc(
					{"doctype": "Item Price", "item_code": code, "price_list": price_list, "price_list_rate": 100}
				).insert(ignore_permissions=True)
		if not frappe.db.exists("Item Price", {"item_code": cls.variants[("Noir", "S")], "price_list": RESELLER_LIST}):
			frappe.get_doc(
				{
					"doctype": "Item Price",
					"item_code": cls.variants[("Noir", "S")],
					"price_list": RESELLER_LIST,
					"price_list_rate": 80,
				}
			).insert(ignore_permissions=True)

		portal_customer(USER, CUSTOMER)
		portal_customer(PLAIN_USER, PLAIN_CUSTOMER)
		# //// Neoffice — added (27e93f3c "fix(quick-order): la CI sur ERPNext standard —
		# tarification au nom du client et deux tests mal posés"): the reseller previously shared
		# the site's default customer group with the plain customer, so "listed group" and "any
		# group" could not be told apart.
		# the reseller sits in a group of its own: the plain customer keeps the site's
		# default leaf group, so "listed group" and "any group" cannot be confused
		if not frappe.db.exists("Customer Group", RESELLER_GROUP):
			frappe.get_doc(
				{
					"doctype": "Customer Group",
					"customer_group_name": RESELLER_GROUP,
					"parent_customer_group": frappe.db.get_value("Customer Group", {"lft": 1}, "name"),
					"is_group": 0,
				}
			).insert(ignore_permissions=True)
		frappe.db.set_value("Customer", CUSTOMER, "customer_group", RESELLER_GROUP)
		# //// Neoffice — added (27e93f3c "fix(quick-order): la CI sur ERPNext standard —
		# tarification au nom du client et deux tests mal posés"): created here, not from the
		# customer's own session further down, since a portal customer has no permission to
		# create an Item.
		# an item the shop never published, for the "unknown here" cases
		make_test_item(LOOSE_ITEM, is_stock_item=0)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		cls.purge()
		for field, value in cls.settings_written.items():
			frappe.db.set_single_value("Webshop Settings", field, value)
		if cls.settings_written:
			frappe.db.commit()
			frappe.local.shopping_cart_settings = None
			frappe.clear_cache()
		super().tearDownClass()

	@classmethod
	def purge(cls):
		frappe.set_user("Administrator")
		for customer in (CUSTOMER, PLAIN_CUSTOMER):
			for name in frappe.get_all("Quotation", filters={"party_name": customer, "docstatus": 0}, pluck="name"):
				frappe.delete_doc("Quotation", name, force=True, ignore_permissions=True)
		# //// Neoffice — added LOOSE_ITEM (27e93f3c "fix(quick-order): la CI sur ERPNext standard —
		# tarification au nom du client et deux tests mal posés"): LOOSE_ITEM is now a class fixture,
		# so it must be purged here too.
		for so in frappe.get_all("Sales Order", filters={"customer": CUSTOMER}, pluck="name"):
			doc = frappe.get_doc("Sales Order", so)
			if doc.docstatus == 1:
				doc.flags.ignore_permissions = True
				doc.cancel()
			frappe.delete_doc("Sales Order", so, force=True, ignore_permissions=True)
		for rule in frappe.get_all("Pricing Rule", filters={"title": ["like", f"{PREFIX} QO%"]}, pluck="name"):
			frappe.delete_doc("Pricing Rule", rule, force=True, ignore_permissions=True)
		codes = frappe.get_all("Item", filters={"variant_of": TEMPLATE}, pluck="name") + [TEMPLATE, LOOSE_ITEM]
		frappe.db.delete("Item Price", {"item_code": ["in", codes]})
		for name in frappe.get_all("Website Item", filters={"item_code": ["in", codes]}, pluck="name"):
			frappe.delete_doc("Website Item", name, force=True, ignore_permissions=True)
		for code in codes:
			if frappe.db.exists("Item", code):
				frappe.delete_doc("Item", code, force=True, ignore_permissions=True)
		frappe.db.commit()

	def setUp(self):
		frappe.set_user("Administrator")
		for customer in (CUSTOMER, PLAIN_CUSTOMER):
			for name in frappe.get_all("Quotation", filters={"party_name": customer, "docstatus": 0}, pluck="name"):
				frappe.delete_doc("Quotation", name, force=True, ignore_permissions=True)
		# this commit persists whatever the previous test left: a pricing rule made
		# there would discount every later test, so it goes first
		for rule in frappe.get_all("Pricing Rule", filters={"title": ["like", f"{PREFIX} QO%"]}, pluck="name"):
			frappe.delete_doc("Pricing Rule", rule, force=True, ignore_permissions=True)
		frappe.db.commit()
		self.real_settings = api.cart_settings
		self.settings = frappe.get_doc("Webshop Settings")
		self.settings.activate_b2b_checkout = 0
		self.settings.allow_items_not_in_stock = 0
		api.cart_settings = lambda: self.settings
		self.real_excluded = api.excluded_item_names
		self.real_available = api.available_cart_qty
		# //// Neoffice — added (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): as_guest() below stubs api.get_party too, so it needs restoring in tearDown()
		self.real_party = api.get_party
		frappe.local.website_profile_doc = None

	def tearDown(self):
		api.cart_settings = self.real_settings
		api.excluded_item_names = self.real_excluded
		api.available_cart_qty = self.real_available
		# //// Neoffice — restores api.get_party (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): see self.real_party in setUp()
		api.get_party = self.real_party
		frappe.local.website_profile_doc = None
		frappe.set_user("Administrator")

	# --- helpers -----------------------------------------------------------------

	def business_site(self, price_list=None):
		"""Browse as if on a site reserved for professionals, at its own tariff."""
		frappe.local.website_profile_doc = frappe._dict(
			{"b2b_only": 1, "price_list": price_list, "primary_domain": "wstest-b2b.example.com"}
		)

	# //// Neoffice — as_guest() replaces b2b_group_of() (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): the gate is no longer about reseller groups, it is about who may fill a cart on this site, including an anonymous visitor.
	def as_guest(self, with_cart=True):
		"""Browse anonymously; the shop's guest customer stands in when it sells to visitors."""
		frappe.set_user("Guest")
		self.settings.enable_guest_cart = 1 if with_cart else 0
		# //// Neoffice — fix (b2d4db3527 "test(quick-order): l'impersonation du visiteur ne recapture plus get_party"): as_guest() used to resave api.get_party on every call; called twice in one test, it kept the first impersonation as the "real" function, which tearDown then restored — eight later tests saw a customer-less account.
		# setUp holds the real get_party; saving it again here would capture the
		# previous impersonation and hand every later test a customer-less session
		api.get_party = lambda *args, **kwargs: (
			frappe._dict(name=PLAIN_CUSTOMER, customer_name="Visiteur", customer_group="") if with_cart else None
		)

	# --- the gate: whoever may fill a cart here -----------------------------------

	# //// Neoffice — replaces test_a_guest_and_a_plain_customer_are_refused() (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): a plain customer is now served regardless of group, so this asserts access instead of a PermissionError.
	def test_a_signed_in_customer_of_any_group_is_served(self):
		frappe.set_user(PLAIN_USER)
		self.assertTrue(api.search_references("chemise"))
		context = api.page_context(frappe._dict())
		self.assertTrue(context.allowed)
		self.assertEqual(context.config["user"], PLAIN_USER)
		self.assertIn("labels", context.config)
		self.assertIn("add_model", context.config["labels"])
		self.assertTrue(api.may_use_quick_order())

	def test_a_visitor_is_served_only_where_the_shop_sells_to_visitors(self):
		self.as_guest(with_cart=False)
		with self.assertRaises(frappe.PermissionError):
			api.search_references("chemise")
		# //// Neoffice — added (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): a visitor with no guest cart is refused, one with a guest cart is served, both through the same guest_allowed() rule as the cart.
		self.assertFalse(api.may_use_quick_order())
		self.as_guest(with_cart=True)
		self.assertTrue(api.search_references("chemise"))
		self.assertTrue(api.page_context(frappe._dict()).allowed)
		# a site reserved for professionals never serves a visitor, cart or not
		self.business_site()
		with self.assertRaises(frappe.PermissionError):
			api.get_matrix(TEMPLATE)
		# //// Neoffice — added (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): guest_allowed() itself must say no on a business-only site too.
		self.assertFalse(api.guest_allowed(self.settings))

	# //// Neoffice — replaces the removed reseller/business-site tests and folds test_the_page_context_refuses_and_admits() into this one (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): there is no more reseller group to test, only "no customer at all".
	def test_a_signed_in_user_without_a_customer_is_refused_with_a_reason(self):
		frappe.set_user(USER)
		api.get_party = lambda *args, **kwargs: None
		with self.assertRaises(frappe.PermissionError):
			api.add_lines([{"item_code": self.variants[("Noir", "S")], "qty": 1}])
		context = api.page_context(frappe._dict())
		self.assertFalse(context.allowed)
		# //// Neoffice — reworded (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): the refusal reason is now "no customer account", not "reserved for professional accounts".
		self.assertIn("compte client", context.reason)

	# --- search and resolution ------------------------------------------------------

	def test_search_finds_the_model_by_code_name_and_barcode(self):
		self.business_site()
		frappe.set_user(USER)
		by_name = api.search_references("Chemise de test")
		self.assertEqual([r["kind"] for r in by_name if r["item_code"] == TEMPLATE], ["template"])
		self.assertEqual(next(r for r in by_name if r["item_code"] == TEMPLATE)["variant_count"], 6)
		by_barcode = api.search_references(BARCODE)
		self.assertEqual(by_barcode[0]["kind"], "variant")
		self.assertEqual(by_barcode[0]["item_code"], self.variants[("Noir", "M")])
		self.assertEqual(by_barcode[0]["template"], TEMPLATE)
		self.assertEqual(by_barcode[0]["attrs"][SIZE], "M")
		by_variant_code = api.resolve_code(self.variants[("Blanc", "L")])
		self.assertEqual(by_variant_code["template"], TEMPLATE)
		self.assertEqual(api.resolve_code("does-not-exist")["unknown"], True)

	def test_an_item_restricted_to_another_site_does_not_exist_here(self):
		self.business_site()
		frappe.set_user(USER)
		api.excluded_item_names = lambda: [self.website_item]
		self.assertEqual([r for r in api.search_references("Chemise de test") if r["item_code"] == TEMPLATE], [])
		self.assertTrue(api.resolve_code(BARCODE)["unknown"])
		with self.assertRaises(frappe.DoesNotExistError):
			api.get_matrix(TEMPLATE)
		out = api.add_lines([{"item_code": self.variants[("Noir", "S")], "qty": 2}])
		self.assertEqual(out["added"], [])
		self.assertEqual(len(out["refused"]), 1)

	def test_an_unpublished_item_is_unknown(self):
		self.business_site()
		frappe.set_user(USER)
		# //// Neoffice — modified (27e93f3c "fix(quick-order): la CI sur ERPNext standard —
		# tarification au nom du client et deux tests mal posés"): no longer creates the Item from
		# the customer's own session (no permission to do so); uses the LOOSE_ITEM fixture from
		# setUpClass instead, and also exercises add_lines() on it.
		self.assertTrue(api.resolve_code(LOOSE_ITEM)["unknown"])
		out = api.add_lines([{"item_code": LOOSE_ITEM, "qty": 1}])
		self.assertEqual(out["added"], [])
		self.assertEqual(out["refused"][0]["item_code"], LOOSE_ITEM)

	# --- the matrix -----------------------------------------------------------------

	def test_the_matrix_is_ordered_priced_and_names_no_purchase_field(self):
		self.business_site()
		frappe.set_user(USER)
		matrix = api.get_matrix(TEMPLATE)
		self.assertEqual([a["attribute"] for a in matrix["attributes"]], [COLOUR, SIZE])
		self.assertEqual(matrix["attributes"][1]["values"], ["S", "M", "L"])
		self.assertEqual(len(matrix["variants"]), 6)
		noir_s = next(v for v in matrix["variants"] if v["item_code"] == self.variants[("Noir", "S")])
		self.assertEqual(noir_s["price"], 100)
		self.assertIn("100", noir_s["formatted_price"])
		self.assertIsNone(noir_s["stock"])  # not a stock item: nothing limits it
		self.assertEqual(
			set(noir_s), {"item_code", "item_name", "attrs", "price", "formatted_price", "stock", "uom"}
		)
		self.assertEqual(matrix["template"]["item_code"], TEMPLATE)

	def test_the_matrix_prices_at_the_site_tariff_not_the_shop_default(self):
		self.business_site(price_list=RESELLER_LIST)
		frappe.set_user(USER)
		matrix = api.get_matrix(TEMPLATE)
		by_code = {v["item_code"]: v for v in matrix["variants"]}
		self.assertEqual(by_code[self.variants[("Noir", "S")]]["price"], 80)
		# no reseller price for this one: the grid says so instead of borrowing the public one
		self.assertIsNone(by_code[self.variants[("Blanc", "L")]]["price"])
		self.assertIsNone(by_code[self.variants[("Blanc", "L")]]["formatted_price"])

	# //// Neoffice ▼▼▼ — new tests for the customer's own price-list resolution and the order xlsx export (6696be727a "feat(quick-order): le prix du client, et la commande en Excel")
	def test_the_matrix_prices_at_the_customer_s_own_list_when_the_site_has_none(self):
		"""No site tariff: the cart takes the customer's default list, so does the grid."""
		frappe.db.set_value("Customer", CUSTOMER, "default_price_list", RESELLER_LIST)
		frappe.set_user(USER)
		self.assertEqual(api.customer_price_list(self.settings, api.get_party()), RESELLER_LIST)
		matrix = api.get_matrix(TEMPLATE)
		by_code = {v["item_code"]: v for v in matrix["variants"]}
		self.assertEqual(by_code[self.variants[("Noir", "S")]]["price"], 80)
		self.assertIsNone(by_code[self.variants[("Blanc", "L")]]["price"])
		# the plain customer, on the same shop, keeps the shop's list
		frappe.set_user(PLAIN_USER)
		self.assertEqual(api.customer_price_list(self.settings, api.get_party()), selling_price_list())
		self.assertEqual({v["price"] for v in api.get_matrix(TEMPLATE)["variants"]}, {100})

	def test_the_matrix_applies_the_shop_s_pricing_rules_like_the_product_page(self):
		noir_s = self.variants[("Noir", "S")]
		rule = frappe.get_doc(
			{
				"doctype": "Pricing Rule",
				"title": f"{PREFIX} QO ten percent",
				"apply_on": "Item Code",
				"items": [{"item_code": noir_s}],
				"selling": 1,
				"price_or_product_discount": "Price",
				"rate_or_discount": "Discount Percentage",
				"discount_percentage": 10,
				"company": default_company(),
				"currency": frappe.db.get_value("Price List", selling_price_list(), "currency"),
			}
		)
		rule.insert(ignore_permissions=True)
		try:
			frappe.set_user(USER)
			by_code = {v["item_code"]: v for v in api.get_matrix(TEMPLATE)["variants"]}
			self.assertEqual(by_code[noir_s]["price"], 90)
			self.assertEqual(by_code[noir_s]["list_price"], 100)
			self.assertIn("90", by_code[noir_s]["formatted_price"])
			self.assertEqual(by_code[self.variants[("Noir", "M")]]["price"], 100)
			self.assertIsNone(by_code[self.variants[("Noir", "M")]]["list_price"])
		finally:
			frappe.set_user("Administrator")
			frappe.delete_doc("Pricing Rule", rule.name, force=True, ignore_permissions=True)

	# --- the order as a spreadsheet ---------------------------------------------------

	def test_the_order_downloads_as_a_spreadsheet_for_its_customer_only(self):
		from webshop.webshop.utils.order_export import download_order_xlsx, order_rows

		frappe.set_user("Administrator")
		order = frappe.get_doc(
			{
				"doctype": "Sales Order",
				"customer": CUSTOMER,
				"company": default_company(),
				"transaction_date": frappe.utils.nowdate(),
				"delivery_date": frappe.utils.add_days(frappe.utils.nowdate(), 5),
				"selling_price_list": selling_price_list(),
				"items": [
					{"item_code": self.variants[("Noir", "M")], "qty": 3, "rate": 100, "delivery_date": frappe.utils.add_days(frappe.utils.nowdate(), 5)}
				],
			}
		)
		order.flags.ignore_permissions = True
		order.insert()
		order.submit()
		rows = order_rows(order)
		self.assertEqual(rows[0][0], "Item Code")
		self.assertIn(SIZE, rows[0])
		line = rows[1]
		self.assertEqual(line[0], self.variants[("Noir", "M")])
		self.assertIn("M", line)
		self.assertIn(BARCODE, line)
		self.assertEqual(line[-4:-1], [3.0, line[-3], 100.0])
		self.assertEqual(line[-1], 300.0)
		self.assertIn(["Grand Total", flt(order.grand_total)] + [""] * (len(rows[0]) - 2), rows)
		frappe.set_user(USER)
		download_order_xlsx("Sales Order", order.name)
		# "download" on the fleet's Frappe, "binary" on a newer one: both are a file
		self.assertIn(frappe.response.get("type"), ("download", "binary"))
		self.assertEqual(frappe.response.get("filename"), f"{order.name}.xlsx")
		self.assertTrue(frappe.response.get("filecontent", b"").startswith(b"PK"))
		# somebody else's order is nobody's business
		frappe.set_user(PLAIN_USER)
		with self.assertRaises(frappe.PermissionError):
			download_order_xlsx("Sales Order", order.name)
	# //// Neoffice ▲▲▲

	# --- the batch into the cart ----------------------------------------------------

	def cart_lines(self):
		name = frappe.db.get_value(
			"Quotation", {"party_name": CUSTOMER, "order_type": "Shopping Cart", "docstatus": 0}, "name"
		)
		if not name:
			return {}
		return {row.item_code: row.qty for row in frappe.get_doc("Quotation", name).items}

	def test_add_lines_merges_into_one_cart_and_reports_what_it_refused(self):
		self.business_site()
		frappe.set_user(USER)
		noir_s, noir_m = self.variants[("Noir", "S")], self.variants[("Noir", "M")]
		out = api.add_lines(
			[
				{"item_code": noir_s, "qty": 2},
				{"item_code": noir_m, "qty": 3},
				{"item_code": noir_s, "qty": 1},
				{"item_code": "no-such-item", "qty": 1},
				{"item_code": noir_m, "qty": 0},
			]
		)
		self.assertEqual({l["item_code"]: l["qty"] for l in out["added"]}, {noir_s: 3, noir_m: 3})
		self.assertEqual([r["item_code"] for r in out["refused"]], ["no-such-item"])
		self.assertEqual(out["cart"]["qty"], 6)
		self.assertEqual(self.cart_lines(), {noir_s: 3, noir_m: 3})
		# a second batch adds to the same lines, it never replaces them
		out = api.add_lines([{"item_code": noir_s, "qty": 1}])
		self.assertEqual(self.cart_lines(), {noir_s: 4, noir_m: 3})
		self.assertEqual(out["cart"]["qty"], 7)

	def test_add_lines_caps_to_what_the_shop_can_serve(self):
		self.business_site()
		frappe.set_user(USER)
		noir_s = self.variants[("Noir", "S")]
		# the shop's rule says three, whatever the stock tables hold
		api.available_cart_qty = lambda *args, **kwargs: frappe._dict(available=3, in_stock=1, source_label=None)
		out = api.add_lines([{"item_code": noir_s, "qty": 5}])
		self.assertEqual(out["added"], [{"item_code": noir_s, "qty": 3}])
		self.assertEqual(out["capped"][0]["asked"], 5)
		self.assertEqual(out["capped"][0]["kept"], 3)
		self.assertEqual(self.cart_lines(), {noir_s: 3})
		# nothing left: refused, and the cart untouched
		out = api.add_lines([{"item_code": noir_s, "qty": 1}])
		self.assertEqual(out["added"], [])
		self.assertIn("Épuisé", out["refused"][0]["reason"])
		self.assertEqual(self.cart_lines(), {noir_s: 3})

	def test_too_many_lines_are_refused_before_anything_is_written(self):
		self.business_site()
		frappe.set_user(USER)
		with self.assertRaises(frappe.ValidationError):
			api.add_lines([{"item_code": self.variants[("Noir", "S")], "qty": 1}] * (api.MAX_LINES + 1))
		self.assertEqual(self.cart_lines(), {})
