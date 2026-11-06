# //// Neoffice — added file (no upstream equivalent). The money path of the audit of the shop (#2296).
"""The cart and the checkout, called as the HTTP handler calls them.

Each guard is proven both ways: the request that must be refused, and the real journey that must still pass
(the checkout restoring a coupon by its document name, a customer picking their own address, a visitor filling
a cart, the search pricing ten results, a reminder's coupon applied from the mail).

The gift cards are played end to end, through the shop's own handler and under upstream's checks
(test_loyalty_rights): a card pays once, for what it really paid, from what the database holds when the order
is made. The cart only notes the balance when the code is applied, so the tests that matter are those of a
balance that moved in between.
"""

import ast
import contextlib
import inspect
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import frappe
from erpnext.utilities.product import get_price
from frappe.handler import is_valid_http_method
from frappe.utils import flt
from frappe.utils.redis_wrapper import RedisWrapper

import webshop.webshop.api as shop_api
import webshop.webshop.shopping_cart.cart as cart
from webshop.controllers.payment_handler import PaymentHandler
from webshop.templates.pages import cart as cart_page
from webshop.templates.pages import checkout
from webshop.templates.pages.gift_cards import get_gift_cards_for_customer
from webshop.webshop.doctype.website_item.website_item import make_website_item
from webshop.webshop.doctype.webshop_settings.webshop_settings import PUBLIC_SETTINGS
from webshop.webshop.quick_order.api import MAX_LINES as QUICK_ORDER_LINES
from webshop.webshop.shopping_cart import guest_cart
from webshop.webshop.shopping_cart.test_loyalty_rights import (
	CUSTOMER,
	GATEWAY,
	ITEM,
	PREFIX,
	PRICE,
	STRANGER,
	STRANGER_CUSTOMER,
	USER,
	ShopFixture,
	_account,
	no_gateway,
	upstream_checks,
)
from webshop.webshop.tests.utils import (
	make_test_item,
	restore_webshop_settings,
	root_customer_group,
	selling_price_list,
	snapshot_webshop_settings,
)
from webshop.webshop.utils import cart_helpers

# Gift cards and warehouse prices are our fork's: this CI runs upstream's erpnext on purpose.
needs_our_erpnext = unittest.skipUnless(
	"warehouse" in inspect.signature(get_price).parameters, "needs our erpnext fork, absent from this CI"
)

CART = "webshop.webshop.shopping_cart.cart"
API = "webshop.webshop.api"
GIFT_ITEM = f"{PREFIX} Audit Gift Card Item"
HIDDEN_ITEM = f"{PREFIX} Audit Hidden Item"
CARD_PREFIX = f"{PREFIX} audit card"
RULE_PREFIX = f"{PREFIX} audit rule"
ADDRESS_PREFIX = f"{PREFIX} audit address"
TARIFF = f"{PREFIX} Audit Reseller Tariff"
RESELLERS = f"{PREFIX} Audit Resellers"
SHIPPING_ON = f"{PREFIX} Audit Shipping On"
SHIPPING_OFF = f"{PREFIX} Audit Shipping Off"
OFFERED = 50
LISTING = '{"field_filters": {}, "attribute_filters": {}, "start": 0}'  # what views.js sends for a first page


def over_http(path, **kwargs):
	"""What the HTTP handler does: the method is whitelisted or refused, then called with the arguments."""
	method = frappe.get_attr(path)
	saved = frappe.local.form_dict
	frappe.local.form_dict = frappe._dict(saved or {}, cmd=path)
	try:
		frappe.is_whitelisted(method)
		return frappe.call(method, **kwargs)
	finally:
		frappe.local.form_dict = saved


@contextlib.contextmanager
def a_request(method="POST", cmd=None, cookies=None, ip=None, form=None):
	"""frappe.local.request and form_dict for one call."""
	saved = getattr(frappe.local, "request", None), frappe.local.form_dict
	saved_ip = getattr(frappe.local, "request_ip", None)
	frappe.local.request = frappe._dict(method=method, path="/", cookies=cookies or {}, headers={})
	frappe.local.form_dict = frappe._dict(form or {})
	if cmd:
		frappe.local.form_dict.cmd = cmd
	# the rate limiter refuses a request with no address; each request here has its own count
	frappe.local.request_ip = ip or frappe.generate_hash(length=10)
	try:
		yield
	finally:
		frappe.local.request, frappe.local.form_dict = saved
		frappe.local.request_ip = saved_ip


@contextlib.contextmanager
def as_visitor(cookie=None):
	"""A visitor with a cart cookie, the way the shop sees one."""
	user = frappe.session.user
	with a_request(cookies={"guest_session_id": cookie or frappe.generate_hash(length=12)}):
		frappe.set_user("Guest")
		try:
			yield
		finally:
			frappe.set_user(user)


def make_card(amount, till=False, customer=CUSTOMER):
	"""A gift card of either family, with its own Pricing Rule, as the shop and the till issue them."""
	if till and not frappe.get_meta("Coupon Code").has_field("pos_next_gift_card"):
		#: A till card is the Coupon Code POS Next marks with its own field. Without POS Next (the
		#: nightly CI of this fork installs erpnext and payments only) it would be an ordinary coupon
		#: with no use left, refused for that reason and not for the one under test.
		raise unittest.SkipTest("needs POS Next, whose field marks a till card")
	code = f"WS{frappe.generate_hash(length=10).upper()}"
	rule = frappe.get_doc(
		{
			"doctype": "Pricing Rule",
			"title": f"{RULE_PREFIX} {code}",
			"apply_on": "Transaction",
			"price_or_product_discount": "Price",
			"is_cumulative": 1,
			"valid_upto": "2999-12-31",
			"selling": 1,
			"buying": 0,
			"coupon_code_based": 1,
			"disable": 0,
			"margin_type": "Amount",
			"rate_or_discount": "Discount Amount",
			"discount_amount": amount,
		}
	).insert(ignore_permissions=True)
	name = (
		frappe.get_doc(
			{
				"doctype": "Coupon Code",
				"coupon_name": f"{CARD_PREFIX} {code}",
				"coupon_type": "Promotional" if till else "Gift Card",
				"pos_next_gift_card": 1 if till else 0,
				"coupon_code": code,
				"pricing_rule": rule.name,
				"maximum_use": 0,
				"used": 0,
				"customer": customer,
				"gift_card_amount": amount,
				"original_gift_card_amount": amount,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)
	frappe.db.commit()
	return frappe._dict(name=name, code=code)


def make_coupon(percentage=10, customer=None):
	"""An ordinary coupon: a reminder's, personal when it names a customer."""
	code = f"WS{frappe.generate_hash(length=10).upper()}"
	rule = frappe.get_doc(
		{
			"doctype": "Pricing Rule",
			"title": f"{RULE_PREFIX} {code}",
			"apply_on": "Transaction",
			"price_or_product_discount": "Price",
			"rate_or_discount": "Discount Percentage",
			"discount_percentage": percentage,
			"apply_discount_on": "Grand Total",
			"selling": 1,
			"coupon_code_based": 1,
			"currency": frappe.db.get_value("Price List", selling_price_list(), "currency"),
		}
	).insert(ignore_permissions=True)
	coupon = frappe.get_doc(
		{
			"doctype": "Coupon Code",
			"coupon_name": f"{CARD_PREFIX} {code}",
			"coupon_type": "Promotional",
			"coupon_code": code,
			"pricing_rule": rule.name,
			"customer": customer,
			"maximum_use": 5,
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()
	return frappe._dict(name=coupon.name, code=code)


def card_row(name):
	return frappe.db.get_value(
		"Coupon Code", name, ["gift_card_amount", "used", "pricing_rule", "coupon_code"], as_dict=True
	)


def _spend_in_a_thread(site, sites_path, card, amount, order, held, release, answers):
	"""One buyer's transaction on its own connection: spends, and commits only when told to."""
	frappe.init(site=site, sites_path=sites_path)
	frappe.connect()
	try:
		frappe.set_user("Administrator")
		cart.spend_gift_card(card, amount, order)
		held.set()
		release.wait(30)
		frappe.db.commit()
		answers[order] = "spent"
	except frappe.ValidationError:
		frappe.db.rollback()
		frappe.clear_messages()
		answers[order] = "refused"
	finally:
		held.set()
		frappe.db.close()
		frappe.destroy()


class TestAuditGuards(ShopFixture):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# The amounts below are before tax, whatever VAT a migrate left on the item, its group or the company.
		cls.no_taxes = [
			mock.patch.object(cart, "set_taxes"),
			mock.patch("erpnext.stock.get_item_details.get_item_tax_template"),
		]
		for patcher in cls.no_taxes:
			patcher.start()
		frappe.set_user("Administrator")
		cls.rules_before = set(frappe.get_all("Pricing Rule", pluck="name"))
		cls.saved_settings = snapshot_webshop_settings(
			[
				"enable_guest_cart",
				"guest_customer",
				"enable_custom_amount",
				"hide_price_for_guest",
				"show_price",
				"enable_checkout",
				"enable_checkout_page",
				"activate_b2b_checkout",
				"login_required_to_view_products",
			]
		)
		cls.customer_group = frappe.db.get_value("Customer", CUSTOMER, "customer_group")
		frappe.get_doc(
			{
				"doctype": "Customer Group",
				"customer_group_name": RESELLERS,
				"parent_customer_group": root_customer_group(),
				"is_group": 0,
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "B2B Customer Group",
				"parent": "Webshop Settings",
				"parenttype": "Webshop Settings",
				"parentfield": "b2b_customer_group",
				"customer_group": RESELLERS,
			}
		).insert(ignore_permissions=True)
		uom = frappe.db.get_single_value("Stock Settings", "stock_uom") or frappe.db.get_value("UOM", {}, "name")
		make_website_item(make_test_item(GIFT_ITEM, is_stock_item=0, stock_uom=uom))
		web_item = frappe.get_doc("Website Item", {"item_code": GIFT_ITEM})
		web_item.published = 1
		web_item.is_gift_card = 1
		web_item.save(ignore_permissions=True)
		make_website_item(make_test_item(HIDDEN_ITEM, is_stock_item=0, stock_uom=uom))
		frappe.db.set_value("Website Item", {"item_code": HIDDEN_ITEM}, "published", 0)
		frappe.get_doc(
			{
				"doctype": "Item Price",
				"item_code": HIDDEN_ITEM,
				"price_list": selling_price_list(),
				"price_list_rate": 321,
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Price List",
				"price_list_name": TARIFF,
				"currency": frappe.db.get_value("Price List", selling_price_list(), "currency"),
				"selling": 1,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{"doctype": "Item Price", "item_code": ITEM, "price_list": TARIFF, "price_list_rate": 7.77, "selling": 1}
		).insert(ignore_permissions=True)
		settings = frappe.get_doc("Webshop Settings")
		cls.amounts_added = not frappe.db.exists("Gift Card Amount", {"amount": OFFERED})
		if cls.amounts_added:
			frappe.get_doc(
				{
					"doctype": "Gift Card Amount",
					"parent": settings.name,
					"parenttype": "Webshop Settings",
					"parentfield": "gift_card_amounts",
					"amount": OFFERED,
				}
			).insert(ignore_permissions=True)
		for label, disabled in ((SHIPPING_ON, 0), (SHIPPING_OFF, 1)):
			frappe.get_doc(
				{
					"doctype": "Shipping Rule",
					"label": label,
					"shipping_rule_type": "Selling",
					"calculate_based_on": "Fixed",
					"shipping_amount": 5,
					"company": cls.company,
					"account": _account(cls.company, root_type="Expense"),
					"cost_center": frappe.get_cached_value("Company", cls.company, "cost_center")
					or frappe.db.get_value("Cost Center", {"company": cls.company, "is_group": 0}, "name"),
					"countries": [{"country": "Switzerland"}],
					"disabled": disabled,
				}
			).insert(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		for patcher in cls.no_taxes:
			patcher.stop()
		restore_webshop_settings(cls.saved_settings)
		frappe.db.delete("B2B Customer Group", {"customer_group": RESELLERS})
		frappe.db.set_value("Customer", CUSTOMER, "customer_group", cls.customer_group)
		frappe.delete_doc("Customer Group", RESELLERS, force=True, ignore_permissions=True)
		cards = frappe.get_all("Coupon Code", filters={"coupon_name": ["like", f"{CARD_PREFIX}%"]}, pluck="name")
		for name in cards:
			frappe.db.delete("Comment", {"reference_doctype": "Coupon Code", "reference_name": name})
			frappe.delete_doc("Coupon Code", name, force=True, ignore_permissions=True)
		used = set(frappe.get_all("Coupon Code", pluck="pricing_rule"))
		for name in set(frappe.get_all("Pricing Rule", pluck="name")) - cls.rules_before - used:
			frappe.delete_doc("Pricing Rule", name, force=True, ignore_permissions=True)
		for label in (SHIPPING_ON, SHIPPING_OFF):
			for name in frappe.get_all("Shipping Rule", filters={"label": label}, pluck="name"):
				frappe.delete_doc("Shipping Rule", name, force=True, ignore_permissions=True)
		if cls.amounts_added:
			frappe.db.delete("Gift Card Amount", {"amount": OFFERED, "parenttype": "Webshop Settings"})
		frappe.db.delete("Item Price", {"item_code": ["in", (ITEM, GIFT_ITEM)], "price_list": TARIFF})
		frappe.delete_doc("Price List", TARIFF, force=True, ignore_permissions=True)
		for customer in (CUSTOMER, STRANGER_CUSTOMER):
			for name in frappe.get_all("Quotation", filters={"party_name": customer}, pluck="name"):
				frappe.delete_doc("Quotation", name, force=True, ignore_permissions=True)
		for name in frappe.get_all(
			"Quotation Item", filters={"item_code": ["in", (GIFT_ITEM, HIDDEN_ITEM, ITEM)]}, pluck="parent"
		):
			if frappe.db.get_value("Quotation", name, "guest_session_id"):
				frappe.delete_doc("Quotation", name, force=True, ignore_permissions=True)
		frappe.db.delete("Item Price", {"item_code": HIDDEN_ITEM})
		for item in (GIFT_ITEM, HIDDEN_ITEM):
			for name in frappe.get_all("Website Item", filters={"item_code": item}, pluck="name"):
				frappe.delete_doc("Website Item", name, force=True, ignore_permissions=True)
			if frappe.db.exists("Item", item):
				frappe.delete_doc("Item", item, force=True, ignore_permissions=True)
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		super().setUp()
		frappe.db.delete("Quotation Item", {"item_code": GIFT_ITEM})
		frappe.db.commit()

	def tearDown(self):
		super().tearDown()
		frappe.db.rollback()

	# --- helpers ------------------------------------------------------------------

	def fill(self, qty=1, user=USER):
		frappe.set_user(user)
		with upstream_checks():
			cart.update_cart(ITEM, qty)
			cart.get_cart_quotation()  # sets the customer's address on the cart, as the cart page does
		frappe.set_user("Administrator")

	def apply(self, code, user=USER):
		frappe.set_user(user)
		with upstream_checks():
			quotation = over_http(f"{CART}.apply_coupon_code", applied_code=code, applied_referral_sales_partner="")
		frappe.set_user("Administrator")
		frappe.db.commit()
		return quotation

	def order_on_account(self, user=USER):
		"""The checkout's "no gateway" door: the order and its invoice, in the buyer's session."""
		frappe.set_user(user)
		with upstream_checks():
			out = PaymentHandler().handle_direct_order()
		frappe.set_user("Administrator")
		frappe.db.commit()
		frappe.clear_messages()
		return out

	def place(self, user=USER):
		"""An order with an amount left to pay, made where such an order is made (place_order)."""
		frappe.set_user(user)
		with upstream_checks():
			name = cart.place_order()
		frappe.set_user("Administrator")
		frappe.db.commit()
		return name

	def invoice(self, order):
		from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice

		invoice = make_sales_invoice(order, ignore_permissions=True)
		invoice.allocate_advances_automatically = True
		invoice.insert(ignore_permissions=True)
		invoice.submit()
		frappe.db.commit()

	def order_at_a_gateway(self, quotation, user=USER):
		frappe.set_user(user)
		with upstream_checks():
			raised = PaymentHandler().create_payment_request(
				quotation_id=quotation.name,
				payment_gateway=GATEWAY,
				idempotency_token=f"{PREFIX}-{frappe.generate_hash(length=10)}",
			)
		frappe.set_user("Administrator")
		frappe.db.commit()
		self.assertEqual("success", raised.get("status"), raised)
		self.stripe_has_charged(raised["payment_request_id"])
		frappe.set_user(user)
		with upstream_checks(), no_gateway():
			out = PaymentHandler().handle_payment_success(payment_request_id=raised["payment_request_id"])
		frappe.set_user("Administrator")
		frappe.db.commit()
		return out

	def orders(self, customer=CUSTOMER):
		return frappe.get_all("Sales Order", filters={"customer": customer, "docstatus": 1}, pluck="name")

	def own_address(self, customer=CUSTOMER):
		return frappe.get_all(
			"Dynamic Link", filters={"parenttype": "Address", "link_name": customer}, pluck="parent"
		)[0]

	def shared_address(self):
		"""One address of both customers: a property manager's, say."""
		address = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": f"{ADDRESS_PREFIX} shared",
				"address_type": "Billing",
				"address_line1": "Rue Commune 1",
				"city": "Lausanne",
				"country": "Switzerland",
				"links": [
					{"link_doctype": "Customer", "link_name": CUSTOMER},
					{"link_doctype": "Customer", "link_name": STRANGER_CUSTOMER},
				],
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(frappe.delete_doc, "Address", address.name, force=True, ignore_permissions=True)
		return address.name

	def guest_cart_shop(self, guest_customer=STRANGER_CUSTOMER):
		frappe.db.set_single_value("Webshop Settings", "enable_guest_cart", 1)
		frappe.db.set_single_value("Webshop Settings", "guest_customer", guest_customer)
		frappe.db.commit()
		frappe.local.shopping_cart_settings = None
		frappe.clear_cache()
		self.addCleanup(restore_webshop_settings, self.saved_settings)

	# --- finding 4: a gift card pays once, for what it really paid ----------------

	@needs_our_erpnext
	def test_a_card_spent_in_full_on_a_paid_order_is_empty_afterwards(self):
		card = make_card(30)
		self.fill()
		quotation = self.apply(card.code)
		self.assertEqual(30, flt(quotation.discount_amount))

		out = self.order_at_a_gateway(quotation)

		self.assertEqual("success", out.get("status"), out)
		self.assertEqual(0, flt(card_row(card.name).gift_card_amount), "the till would still accept this balance")

	@needs_our_erpnext
	def test_a_card_spent_in_full_on_an_order_on_account_is_empty_afterwards(self):
		card = make_card(30)
		self.fill()
		self.apply(card.code)

		order = self.place()
		self.invoice(order)

		row = card_row(card.name)
		self.assertEqual(0, flt(row.gift_card_amount))
		self.assertGreaterEqual(row.used, 1)
		self.assertEqual(1, len(self.spends(card.name)), "the order and its invoice settle the card once")

	def spends(self, card_name):
		return frappe.get_all(
			"Comment", filters={"reference_doctype": "Coupon Code", "reference_name": card_name}, pluck="content"
		)

	@needs_our_erpnext
	def test_a_card_worth_more_than_the_order_keeps_its_code_and_the_rest(self):
		card = make_card(120)
		self.fill()
		self.apply(card.code)

		out = self.order_on_account()

		self.assertEqual("success", out.get("status"), out)
		order = self.orders()[0]
		self.assertEqual(50, flt(frappe.db.get_value("Sales Order", order, "discount_amount")))
		self.assertEqual(70, flt(card_row(card.name).gift_card_amount))
		self.assertEqual(1, len(self.spends(card.name)), "the order and its invoice settle the card once")
		self.assertEqual(card.code, card_row(card.name).coupon_code)
		self.assertFalse(
			frappe.get_all("Coupon Code", filters={"coupon_code_residual": card.name}),
			"no second card: the amount used must not stay spendable",
		)
		shown = next(c for c in get_gift_cards_for_customer(CUSTOMER) if c.name == card.name)
		self.assertEqual(("active", 70), (shown.status, flt(shown.remaining_amount)))

	@needs_our_erpnext
	def test_the_rest_of_a_card_pays_the_next_order(self):
		card = make_card(70)
		self.fill()
		self.apply(card.code)
		self.assertEqual("success", self.order_on_account().get("status"))
		self.assertEqual(20, flt(card_row(card.name).gift_card_amount))

		self.fill()
		quotation = self.apply(card.code)
		self.assertEqual(20, flt(quotation.discount_amount))
		out = self.order_at_a_gateway(quotation)

		self.assertEqual("success", out.get("status"), out)
		self.assertEqual(0, flt(card_row(card.name).gift_card_amount))
		self.assertEqual(20, flt(frappe.db.get_value("Sales Order", self.orders()[0], "discount_amount")))

	@needs_our_erpnext
	def test_an_order_that_fails_costs_the_card_nothing(self):
		"""handle_direct_order swallows the failure and the POST commits: what was written before it stays."""
		for till in (False, True):
			with self.subTest(till=till):
				card = make_card(120, till=till)
				self.fill()
				self.apply(card.code)
				with mock.patch.object(cart, "_check_the_buyer_s_standing", side_effect=frappe.ValidationError("no")):
					out = self.order_on_account()
				self.assertEqual("error", out.get("status"), out)
				self.assertEqual(120, flt(card_row(card.name).gift_card_amount))
				self.assertFalse(frappe.get_all("Coupon Code", filters={"coupon_code_residual": card.name}))
				frappe.db.rollback()

	@needs_our_erpnext
	def test_a_till_card_pays_at_the_shop_and_keeps_its_code(self):
		card = make_card(120, till=True)
		self.fill()
		self.apply(card.code)

		out = self.order_on_account()

		self.assertEqual("success", out.get("status"), out)
		row = card_row(card.name)
		self.assertEqual(70, flt(row.gift_card_amount))
		self.assertEqual(card.code, row.coupon_code)
		self.assertEqual(
			70, flt(frappe.db.get_value("Pricing Rule", row.pricing_rule, "discount_amount")),
			"the till's own rule follows the balance, as POS Next writes it",
		)

	@needs_our_erpnext
	def test_a_till_card_spent_in_full_pays_at_the_shop(self):
		card = make_card(30, till=True)
		self.fill()
		self.apply(card.code)

		self.place()

		self.assertEqual(0, flt(card_row(card.name).gift_card_amount))
		self.assertEqual(1, len(self.orders()))

	@needs_our_erpnext
	def test_a_card_applied_on_two_carts_pays_one(self):
		card = make_card(30)
		for user in (USER, STRANGER):
			self.fill(user=user)
			self.apply(card.code, user=user)

		self.place(USER)
		frappe.set_user(STRANGER)
		with upstream_checks(), self.assertRaises(frappe.ValidationError):
			cart.place_order()
		frappe.set_user("Administrator")
		frappe.db.rollback()

		self.assertEqual([], self.orders(STRANGER_CUSTOMER), "the second order was paid with a spent balance")
		self.assertEqual(0, flt(card_row(card.name).gift_card_amount))

	@needs_our_erpnext
	def test_a_cancelled_order_gives_its_card_back(self):
		card = make_card(120)
		self.fill()
		self.apply(card.code)
		self.assertEqual("success", self.order_on_account().get("status"))
		self.assertEqual(70, flt(card_row(card.name).gift_card_amount))

		cart.give_gift_card_back(frappe.get_doc("Sales Order", self.orders()[0]))

		self.assertEqual(120, flt(card_row(card.name).gift_card_amount))
		self.fill()
		self.assertEqual(50, flt(self.apply(card.code).discount_amount), "the card pays again")

	@needs_our_erpnext
	def test_a_card_spent_in_full_is_whole_again_when_its_order_is_cancelled(self):
		card = make_card(30)
		self.fill()
		self.apply(card.code)
		self.place()

		cart.give_gift_card_back(frappe.get_doc("Sales Order", self.orders()[0]))

		self.assertEqual((30, 0), (flt(card_row(card.name).gift_card_amount), card_row(card.name).used))

	def test_two_connections_cannot_spend_one_balance(self):
		"""The row is read FOR UPDATE: the second buyer waits for the first, then reads what the first left."""
		card = make_card(100)
		site, sites_path = frappe.local.site, frappe.local.sites_path
		answers, release = {}, threading.Event()
		held_a, held_b = threading.Event(), threading.Event()
		first = threading.Thread(
			target=_spend_in_a_thread,
			args=(site, sites_path, card.name, 60, f"{PREFIX}-ORDER-A", held_a, release, answers),
		)
		second = threading.Thread(
			target=_spend_in_a_thread,
			args=(site, sites_path, card.name, 60, f"{PREFIX}-ORDER-B", held_b, release, answers),
		)
		first.start()
		self.assertTrue(held_a.wait(20), "the first buyer never got through")
		second.start()
		time.sleep(1.5)
		self.assertNotIn(f"{PREFIX}-ORDER-B", answers, "the second buyer did not wait for the lock")
		release.set()
		first.join(30)
		second.join(30)

		self.assertEqual("spent", answers.get(f"{PREFIX}-ORDER-A"), answers)
		self.assertEqual("refused", answers.get(f"{PREFIX}-ORDER-B"), answers)
		frappe.db.rollback()
		self.assertEqual(40, flt(card_row(card.name).gift_card_amount))

	def test_the_same_order_is_settled_once(self):
		card = make_card(100)
		cart.spend_gift_card(card.name, 40, f"{PREFIX}-ORDER-ONCE")
		cart.spend_gift_card(card.name, 40, f"{PREFIX}-ORDER-ONCE", strict=False)
		self.assertEqual(60, flt(card_row(card.name).gift_card_amount))

	def test_money_already_taken_takes_what_is_left_and_tells_someone(self):
		"""A gateway has confirmed: the order stands, the card gives what it has, and the shortfall is logged."""
		card = make_card(10)
		with mock.patch.object(frappe, "log_error") as logged:
			cart.spend_gift_card(card.name, 30, f"{PREFIX}-ORDER-SHORT", strict=False)
		self.assertEqual(0, flt(card_row(card.name).gift_card_amount))
		self.assertTrue(logged.called)

	# --- finding 37: the web door of place_order --------------------------------------

	def shop_terms(self, checkout=1, page=1, b2b=0):
		for field, value in (
			("enable_checkout", checkout),
			("enable_checkout_page", page),
			("activate_b2b_checkout", b2b),
		):
			frappe.db.set_single_value("Webshop Settings", field, value)
		frappe.db.commit()
		frappe.local.shopping_cart_settings = None
		frappe.clear_cache()
		self.addCleanup(restore_webshop_settings, self.saved_settings)

	def reseller(self):
		"""USER's customer, in a group the B2B checkout names."""
		frappe.db.set_value("Customer", CUSTOMER, "customer_group", RESELLERS)
		frappe.db.commit()
		self.addCleanup(frappe.db.commit)
		self.addCleanup(frappe.db.set_value, "Customer", CUSTOMER, "customer_group", self.customer_group)

	def order_by_the_web_door(self, user=USER):
		frappe.set_user(user)
		with upstream_checks():
			name = over_http(f"{CART}.place_order")
		frappe.set_user("Administrator")
		frappe.db.commit()
		return name

	def refused_at_the_web_door(self, user=USER):
		frappe.set_user(user)
		with upstream_checks(), self.assertRaises(frappe.ValidationError):
			over_http(f"{CART}.place_order")
		frappe.set_user("Administrator")
		frappe.db.rollback()
		frappe.clear_messages()
		self.assertEqual([], self.orders(frappe.db.get_value("Portal User", {"user": user}, "parent")))

	def test_a_reseller_on_invoice_terms_keeps_ordering(self):
		"""The journey of /checkout-b2b: an unpaid submitted order, on the terms the shop gave that group."""
		self.reseller()
		self.shop_terms(b2b=1)
		self.fill()

		name = self.order_by_the_web_door()

		order = frappe.db.get_value("Sales Order", name, ["docstatus", "customer", "grand_total"], as_dict=True)
		self.assertEqual((1, CUSTOMER), (order.docstatus, order.customer))
		self.assertGreater(flt(order.grand_total), 0)

	def test_a_customer_outside_the_b2b_groups_goes_through_the_checkout(self):
		self.shop_terms(b2b=1)
		self.fill(user=STRANGER)
		self.refused_at_the_web_door(STRANGER)

	def test_with_the_checkout_page_an_amount_to_pay_has_no_web_door_here(self):
		self.shop_terms()
		self.fill()
		self.refused_at_the_web_door()

	def test_a_shop_without_checkout_takes_no_order(self):
		self.shop_terms(checkout=0, page=0)
		self.fill()
		self.refused_at_the_web_door()

	def test_the_classic_cart_keeps_its_button(self):
		"""Upstream's flow, on a shop with no checkout page: the cart's "Place Order"."""
		self.shop_terms(page=0)
		self.fill()
		self.assertTrue(self.order_by_the_web_door())

	@needs_our_erpnext
	def test_a_card_that_pays_everything_passes(self):
		card = make_card(120)
		self.shop_terms()
		self.fill()
		self.apply(card.code)
		self.assertTrue(self.order_by_the_web_door())
		self.assertEqual(70, flt(card_row(card.name).gift_card_amount))

	def test_a_python_caller_settles_the_terms_itself(self):
		"""place_offline_order, the gateway's return and Webshopsi call the same function, unpaid."""
		self.shop_terms()
		self.fill()
		self.assertTrue(self.place())

	# --- finding 5: a code is a text, and the exact code ---------------------------

	def test_a_filter_is_not_a_code(self):
		card = make_card(30)
		self.fill()
		for user in (USER, "Guest"):
			frappe.set_user(user)
			with self.subTest(user=user), a_request(), self.assertRaises(frappe.FrappeTypeError):
				over_http(f"{CART}.apply_coupon_code", applied_code=["like", "WS%"], applied_referral_sales_partner="")
		frappe.set_user(USER)
		with self.assertRaises(frappe.FrappeTypeError):
			over_http(
				f"{CART}.apply_coupon_code",
				applied_code=card.code,
				applied_referral_sales_partner=["like", "%"],
			)
		with self.assertRaises(frappe.FrappeTypeError):
			over_http(f"{CART}.check_gift_cards", code=["like", "WS%"])
		frappe.set_user("Administrator")
		self.assertEqual(30, flt(card_row(card.name).gift_card_amount))

	@needs_our_erpnext
	def test_the_exact_code_and_the_name_the_checkout_restores_are_accepted(self):
		card = make_card(30)
		self.fill()
		self.assertEqual(30, flt(self.apply(card.code).discount_amount))
		frappe.set_user(USER)
		quotation = cart.remove_coupon_code()
		restored = cart.apply_coupon_code(quotation.get("gift_card_coupon") or card.name, "")
		self.assertEqual(30, flt(restored.discount_amount))
		self.assertTrue(over_http(f"{CART}.check_gift_cards", code=card.code))

	def test_an_unknown_code_is_refused(self):
		self.fill()
		frappe.set_user(USER)
		with self.assertRaises(frappe.ValidationError):
			over_http(f"{CART}.apply_coupon_code", applied_code="WS-NO-SUCH-CODE", applied_referral_sales_partner="")

	def test_a_card_spent_before_this_fix_stays_refused_at_the_shop(self):
		"""A card spent in full kept its balance and `used`: it must not come back to life."""
		card = make_card(30)
		frappe.db.set_value("Coupon Code", card.name, "used", 1)
		frappe.db.set_value("Coupon Code", card.name, "maximum_use", 1)
		frappe.db.commit()
		self.fill()
		frappe.set_user(USER)
		with self.assertRaises(frappe.ValidationError):
			over_http(f"{CART}.apply_coupon_code", applied_code=card.code, applied_referral_sales_partner="")

	# --- finding 36: a rate comes from the server ----------------------------------

	def gift_line(self):
		return frappe.db.get_value(
			"Quotation Item",
			{"item_code": GIFT_ITEM, "docstatus": 0},
			["rate", "price_list_rate", "gift_card_data"],
			as_dict=True,
		)

	def test_a_gift_card_at_a_negative_rate_is_refused(self):
		frappe.db.set_single_value("Webshop Settings", "enable_custom_amount", 1)
		self.addCleanup(restore_webshop_settings, self.saved_settings)
		frappe.db.commit()
		frappe.set_user(USER)
		with self.assertRaises(frappe.ValidationError):
			over_http(f"{CART}.update_cart", item_code=GIFT_ITEM, qty=1, price_list_rate=-500)
		frappe.db.rollback()
		frappe.set_user("Administrator")
		self.assertFalse(self.gift_line())

	def test_the_data_of_a_line_cannot_change_its_rate(self):
		frappe.set_user(USER)
		over_http(
			f"{CART}.update_cart",
			item_code=GIFT_ITEM,
			qty=1,
			price_list_rate=OFFERED,
			gift_card_data={"code": "WS-OWN-CODE", "rate": -500, "price_list_rate": -500},
		)
		# the next save of the cart is where the rate of the data came back
		over_http(f"{CART}.update_cart", item_code=ITEM, qty=1)
		frappe.set_user("Administrator")
		line = self.gift_line()
		self.assertEqual((OFFERED, OFFERED), (flt(line.rate), flt(line.price_list_rate)))

	def test_a_shop_with_fixed_amounts_refuses_any_other(self):
		frappe.db.set_single_value("Webshop Settings", "enable_custom_amount", 0)
		self.addCleanup(restore_webshop_settings, self.saved_settings)
		frappe.db.commit()
		frappe.set_user(USER)
		with self.assertRaises(frappe.ValidationError):
			over_http(f"{CART}.update_cart", item_code=GIFT_ITEM, qty=1, price_list_rate=1)
		over_http(f"{CART}.update_cart", item_code=GIFT_ITEM, qty=1, price_list_rate=OFFERED)
		frappe.set_user("Administrator")
		self.assertEqual(OFFERED, flt(self.gift_line().rate))

	def test_a_custom_amount_passes_where_the_shop_offers_it(self):
		frappe.db.set_single_value("Webshop Settings", "enable_custom_amount", 1)
		self.addCleanup(restore_webshop_settings, self.saved_settings)
		frappe.db.commit()
		frappe.set_user(USER)
		over_http(
			f"{CART}.update_cart",
			item_code=GIFT_ITEM,
			qty=1,
			price_list_rate=33,
			gift_card_data={"code": "WS-OWN-CODE", "price_list_rate": 33, "rate": 33},
		)
		frappe.set_user("Administrator")
		self.assertEqual(33, flt(self.gift_line().rate))

	def test_a_visitor_cannot_choose_a_rate_either(self):
		self.guest_cart_shop()
		with as_visitor(), self.assertRaises(frappe.ValidationError):
			over_http(
				f"{CART}.update_cart",
				item_code=GIFT_ITEM,
				qty=1,
				price_list_rate=-500,
				gift_card_data={"rate": -500, "price_list_rate": -500},
			)
		frappe.db.rollback()

	# --- findings 6 and 9: an address belongs to the cart's party ------------------

	def test_a_customer_picks_their_own_address(self):
		self.fill()
		frappe.set_user(USER)
		out = over_http(f"{CART}.update_cart_address", address_type="shipping", address_name=self.own_address())
		self.assertIn("address", out)

	def test_an_address_of_another_party_is_refused_on_the_cart(self):
		self.fill()
		theirs = self.own_address(STRANGER_CUSTOMER)
		frappe.set_user(USER)
		with self.assertRaises(frappe.PermissionError):
			over_http(f"{CART}.update_cart_address", address_type="billing", address_name=theirs)

	def test_a_filter_is_not_an_address(self):
		self.fill()
		frappe.set_user(USER)
		with self.assertRaises(frappe.FrappeTypeError):
			over_http(
				f"{CART}.update_cart_address", address_type="other", address_name={"address_title": ["like", "a%"]}
			)

	def test_a_visitor_reads_no_address_of_the_shop_s_customers(self):
		theirs = self.own_address(STRANGER_CUSTOMER)
		mine = self.own_address()
		self.guest_cart_shop(guest_customer="")
		with as_visitor():
			over_http(f"{CART}.update_cart", item_code=ITEM, qty=1)
			with self.assertRaises(frappe.PermissionError):
				over_http(f"{CART}.update_cart_address", address_type="billing", address_name=theirs)
		self.guest_cart_shop(guest_customer=STRANGER_CUSTOMER)
		with as_visitor():
			over_http(f"{CART}.update_cart", item_code=ITEM, qty=1)
			with self.assertRaises(frappe.PermissionError):
				over_http(f"{CART}.update_cart_address", address_type="billing", address_name=mine)
		frappe.db.rollback()

	def test_a_visitor_takes_an_address_of_the_shop_s_guest_customer(self):
		"""What a visitor's cart may hold: the list get_address_docs offers it."""
		address = self.own_address(STRANGER_CUSTOMER)
		self.guest_cart_shop(guest_customer=STRANGER_CUSTOMER)
		with as_visitor():
			over_http(f"{CART}.update_cart", item_code=ITEM, qty=1)
			out = over_http(f"{CART}.update_cart_address", address_type="billing", address_name=address)
		self.assertIn("address", out)
		frappe.db.rollback()

	def test_an_address_another_party_shares_is_not_rewritten_from_the_checkout(self):
		shared = self.shared_address()
		frappe.set_user(USER)
		with self.assertRaises(frappe.ValidationError):
			over_http(
				"webshop.templates.pages.checkout.update_address_info",
				doctype="Address",
				docname=shared,
				fieldname_dict={"city": "Nowhere"},
			)
		frappe.set_user("Administrator")
		self.assertEqual("Lausanne", frappe.db.get_value("Address", shared, "city"))

	def test_a_filter_is_not_a_document_to_rewrite(self):
		theirs = self.own_address(STRANGER_CUSTOMER)
		frappe.set_user(USER)
		with self.assertRaises(frappe.FrappeTypeError):
			over_http(
				"webshop.templates.pages.checkout.update_address_info",
				doctype="Address",
				docname=["!=", theirs],
				fieldname_dict={"city": "Nowhere"},
			)

	def test_a_customer_still_rewrites_an_address_of_their_own(self):
		mine = self.own_address()
		frappe.set_user(USER)
		out = over_http(
			"webshop.templates.pages.checkout.update_address_info",
			doctype="Address",
			docname=mine,
			fieldname_dict={"city": "Genève"},
		)
		self.assertTrue(out["success"], out)

	# --- findings 19, 27, 51: the visitor's cart -----------------------------------

	def test_create_guest_quotation_is_no_longer_a_door(self):
		with as_visitor(), self.assertRaises(frappe.PermissionError):
			over_http(
				"webshop.webshop.shopping_cart.guest_cart.create_guest_quotation",
				items=[{"item_code": ITEM, "qty": 1}],
			)

	def visitor_s_lines(self, cookie):
		name = frappe.db.get_value("Quotation", {"guest_session_id": cookie}, "name")
		rows = frappe.get_all("Quotation Item", filters={"parent": name}, fields=["item_code", "qty", "rate"])
		return {row.item_code: (flt(row.qty), flt(row.rate)) for row in rows}

	def test_a_visitor_fills_a_cart_with_the_product_page_s_button(self):
		"""Each visitor's "Add to cart" ended in a 403 and an empty cart: the save passed, the pricing did not."""
		self.guest_cart_shop()
		cookie = frappe.generate_hash(length=12)
		with as_visitor(cookie), upstream_checks():
			out = over_http(f"{CART}.update_cart", item_code=ITEM, qty=2, add_qty=True, with_items=1)
		self.assertIn("items", out)
		self.assertEqual({ITEM: (2, PRICE)}, self.visitor_s_lines(cookie))
		frappe.db.rollback()

	def test_a_visitor_changes_a_line_with_the_cart_s_button(self):
		self.guest_cart_shop()
		cookie = frappe.generate_hash(length=12)
		with as_visitor(cookie), upstream_checks():
			over_http(f"{CART}.update_cart", item_code=ITEM, qty=1)
			out = over_http("webshop.webshop.utils.cart_helpers.update_cart", item_code=ITEM, qty=3, with_items=1)
		self.assertIsNot(False, out.get("success"), out)
		self.assertEqual({ITEM: (3, PRICE)}, self.visitor_s_lines(cookie))
		frappe.db.rollback()

	def test_a_visitor_adds_nothing_the_shop_does_not_sell(self):
		"""The shop's rights price the visitor's cart: an item that is not on sale must not get a price that way."""
		self.guest_cart_shop()
		cookie = frappe.generate_hash(length=12)
		with as_visitor(cookie):
			for code in (HIDDEN_ITEM, f"{PREFIX}-NO-SUCH-ITEM"):
				with self.subTest(code=code), self.assertRaises(frappe.PermissionError):
					over_http(f"{CART}.update_cart", item_code=code, qty=1)
			out = over_http("webshop.webshop.utils.cart_helpers.update_cart", item_code=HIDDEN_ITEM, qty=1)
		self.assertFalse(out.get("success"), out)
		self.assertNotIn("321", frappe.as_json(out))
		self.assertFalse(frappe.db.exists("Quotation", {"guest_session_id": cookie}))
		frappe.db.rollback()

	def test_a_visitor_books_an_article_with_no_published_page(self):
		"""The booking module's door: Python, not the shop's button (extras.ensure_sellable)."""
		self.guest_cart_shop()
		cookie = frappe.generate_hash(length=12)
		with as_visitor(cookie), upstream_checks():
			cart.update_cart(item_code=HIDDEN_ITEM, qty=1)
			# and the visitor can still change the line from the cart
			over_http("webshop.webshop.utils.cart_helpers.update_cart", item_code=HIDDEN_ITEM, qty=2)
		self.assertEqual({HIDDEN_ITEM: (2, 321)}, self.visitor_s_lines(cookie))
		frappe.db.rollback()

	def test_a_buyer_changes_their_phone_at_the_checkout(self):
		self.fill()
		frappe.set_user(USER)
		with upstream_checks():
			out = over_http(
				f"{CART}.update_contact_info",
				first_name="A",
				last_name="Buyer",
				email=USER,
				phone="+41 21 555 00 11",
			)
		self.assertTrue(out["success"], out)
		frappe.set_user("Administrator")
		self.assertEqual("+41 21 555 00 11", frappe.db.get_value("Contact", {"email_id": USER}, "mobile_no"))

	def test_an_unbounded_list_is_refused_before_it_is_priced(self):
		lines = [{"item_code": ITEM, "qty": 1}] * (QUICK_ORDER_LINES * 3)
		with (
			as_visitor(),
			mock.patch.object(guest_cart, "apply_cart_settings", side_effect=AssertionError("priced")),
			self.assertRaises(frappe.ValidationError),
		):
			guest_cart.create_guest_quotation(lines)

	def test_the_largest_real_cart_passes(self):
		"""A visitor may paste a full quick order on top of what the cart holds."""
		self.assertGreaterEqual(getattr(guest_cart, "MAX_CART_LINES", 0), QUICK_ORDER_LINES * 2)

	def test_a_professional_site_gives_a_visitor_no_cart(self):
		frappe.local.website_profile_doc = {"b2b_only": 1, "price_list": TARIFF}
		self.addCleanup(setattr, frappe.local, "website_profile_doc", None)
		with as_visitor(), self.assertRaises(frappe.PermissionError):
			guest_cart.create_guest_quotation([{"item_code": ITEM, "qty": 1}])

	def test_the_test_endpoint_is_gone(self):
		self.assertFalse(hasattr(guest_cart, "test_guest_quotation"))

	def test_filling_a_cart_is_limited(self):
		tree = ast.parse(Path(cart.__file__).read_text(encoding="utf-8"))
		function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "update_cart")
		names = [ast.unparse(d.func if isinstance(d, ast.Call) else d) for d in function.decorator_list]
		self.assertIn("rate_limit", names)

	# --- finding 20: the search's prices -------------------------------------------

	def test_a_repeated_item_is_priced_once(self):
		with mock.patch("erpnext.utilities.product.get_price", return_value=None) as priced:
			out = over_http(f"{API}.get_product_price_info", items=[ITEM] * 200)
		self.assertEqual(1, priced.call_count)
		self.assertEqual([ITEM], list(out))

	def test_a_long_list_is_cut(self):
		codes = [f"{PREFIX}-NO-SUCH-{index}" for index in range(5000)]
		out = over_http(f"{API}.get_product_price_info", items=codes)
		self.assertLessEqual(len(out), 50)

	@needs_our_erpnext
	def test_the_search_still_gets_its_prices(self):
		out = over_http(f"{API}.get_product_price_info", items=frappe.as_json([ITEM, f"{PREFIX}-NO-SUCH"]))
		self.assertEqual(PRICE, flt(out[ITEM]["price_list_rate"]))

	def test_something_else_than_a_list_of_codes_is_refused(self):
		with self.assertRaises(frappe.FrappeTypeError):
			over_http(f"{API}.get_product_price_info", items={"a": 1})
		self.assertEqual({}, over_http(f"{API}.get_product_price_info", items=[["like", "%"]]))

	def test_the_prices_are_limited(self):
		key = f"{API}.get_product_price_info"
		ip = f"203.0.113.{frappe.utils.cint(time.time()) % 250}"
		with a_request(cmd=key, ip=ip):
			self.addCleanup(frappe.cache.delete, frappe.cache.make_key(f"rl:{key}:{ip}"))
			with self.assertRaises(frappe.RateLimitExceededError):
				for _attempt in range(2000):
					over_http(key, items=[])

	# --- what the shop does not show, on the methods of api.py ------------------------

	def closed_catalogue(self):
		frappe.db.set_single_value("Webshop Settings", "login_required_to_view_products", 1)
		frappe.db.commit()
		frappe.local.shopping_cart_settings = None
		frappe.clear_cache()
		self.addCleanup(restore_webshop_settings, self.saved_settings)

	def test_a_closed_catalogue_lists_nothing_for_a_visitor(self):
		self.closed_catalogue()
		with as_visitor(), self.assertRaises(frappe.PermissionError):
			over_http(f"{API}.get_product_filter_data", query_args=LISTING)

	def test_a_closed_catalogue_prices_nothing_for_a_visitor(self):
		self.closed_catalogue()
		with as_visitor():
			self.assertEqual({}, over_http(f"{API}.get_product_price_info", items=[ITEM]))

	@needs_our_erpnext
	def test_a_closed_catalogue_stays_open_to_a_customer(self):
		self.closed_catalogue()
		frappe.set_user(USER)
		with a_request():
			out = over_http(f"{API}.get_product_filter_data", query_args=LISTING)
			prices = over_http(f"{API}.get_product_price_info", items=[ITEM])
		self.assertIn("items", out)
		self.assertEqual(PRICE, flt(prices[ITEM]["price_list_rate"]))

	@needs_our_erpnext
	def test_a_visitor_lists_the_shop_as_before(self):
		with as_visitor():
			self.assertIn("items", over_http(f"{API}.get_product_filter_data", query_args=LISTING))

	@needs_our_erpnext
	def test_a_visitor_reads_no_price_of_what_the_shop_does_not_show(self):
		with as_visitor():
			out = over_http(f"{API}.get_product_price_info", items=[ITEM, HIDDEN_ITEM])
		self.assertEqual([ITEM], list(out))

	@needs_our_erpnext
	def test_the_staff_read_the_rest(self):
		out = over_http(f"{API}.get_product_price_info", items=[HIDDEN_ITEM])
		self.assertEqual(321, flt(out[HIDDEN_ITEM]["price_list_rate"]))

	def test_the_search_dropdown_prints_no_raw_data(self):
		folder = Path(cart.__file__).resolve().parents[2] / "public" / "js" / "product_ui"
		for name in ("search.js", "search_no_jquery.js"):
			source = (folder / name).read_text(encoding="utf-8")
			with self.subTest(name=name):
				for raw in ("${res.web_item_name}", "${res.route}", '"by " + res.brand', "${category.route}"):
					self.assertNotIn(raw, source)
				self.assertNotIn("${ category.name }", source)
				self.assertIn("esc(res.web_item_name)", source)

	# --- finding 25: the product question ------------------------------------------

	def test_a_question_does_not_read_the_lead_back(self):
		email = f"wstest-{frappe.generate_hash(length=8)}@yopmail.com"
		lead = {"lead_name": "A visitor", "email_id": email, "company_name": "Somewhere"}
		with mock.patch.object(cart, "_theme_installed", return_value=False):
			first = cart.create_lead_for_item_inquiry(frappe.as_json(lead), message="Is it in stock?")
			name = first.name
			self.addCleanup(frappe.delete_doc, "Lead", name, force=True, ignore_permissions=True)
			frappe.db.set_value("Lead", name, "mobile_no", "+41 79 000 00 00")
			frappe.db.commit()
			with a_request():
				frappe.set_user("Guest")
				second = cart.create_lead_for_item_inquiry(
					frappe.as_json({**lead, "lead_name": "Someone else"}), message="And the price?"
				)
				frappe.set_user("Administrator")
		answer = frappe.parse_json(frappe.as_json(second))
		self.assertLessEqual(set(answer), {"name", "email_id"}, "the whole Lead went to a visitor")

	# --- finding 35: a write takes a POST ------------------------------------------

	def test_the_customer_s_records_are_not_written_by_a_get(self):
		for path in (
			f"{API}.update_address",
			f"{API}.delete_address",
			f"{CART}.update_customer_info",
			f"{CART}.remove_loyalty_points",
			f"{CART}.create_lead_for_item_inquiry",
		):
			method = frappe.get_attr(path)
			with self.subTest(path=path):
				with a_request("GET"), self.assertRaises(frappe.PermissionError):
					is_valid_http_method(method)
				with a_request("POST"):
					is_valid_http_method(method)

	# --- finding 39: the discounted preview ----------------------------------------

	def discounted_rule(self, **values):
		rule = frappe.get_doc(
			{
				"doctype": "Pricing Rule",
				"title": f"{RULE_PREFIX} preview {frappe.generate_hash(length=6)}",
				"apply_on": "Item Code",
				"items": [{"item_code": ITEM}],
				"price_or_product_discount": "Price",
				"rate_or_discount": "Discount Percentage",
				"selling": 1,
				"company": self.company,
				"currency": frappe.db.get_value("Price List", selling_price_list(), "currency"),
				**values,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(frappe.delete_doc, "Pricing Rule", rule.name, force=True, ignore_permissions=True)
		return rule

	def preview(self, **kwargs):
		get_value = RedisWrapper.get_value

		def no_old_preview(cache, key, *args, **kw):
			return None if str(key).startswith("discount_preview:") else get_value(cache, key, *args, **kw)

		with mock.patch.object(RedisWrapper, "get_value", no_old_preview):
			out = over_http(f"{API}.get_discount_items_preview", limit=50, **kwargs)
		return next((row for row in out if row.get("item_code") == ITEM), None)

	def test_the_preview_prices_from_the_shop_s_own_list(self):
		self.discounted_rule(discount_percentage=97)
		frappe.set_user(USER)
		shown = self.preview(price_list=TARIFF)
		self.assertTrue(shown)
		self.assertNotIn("7.77", shown.get("formatted_price") or "", "a list the caller named")
		self.assertIn("50", shown.get("formatted_price") or "")

	def test_a_shop_that_hides_its_prices_from_visitors_hides_them_here(self):
		self.discounted_rule(discount_percentage=96)
		frappe.db.set_single_value("Webshop Settings", "hide_price_for_guest", 1)
		self.addCleanup(restore_webshop_settings, self.saved_settings)
		frappe.db.commit()
		frappe.local.shopping_cart_settings = None
		frappe.clear_cache()
		with as_visitor():
			self.assertIsNone(self.preview())

	def test_a_rule_reserved_for_a_customer_is_not_shown_to_others(self):
		self.discounted_rule(
			discount_percentage=95,
			applicable_for="Customer",
			customer=STRANGER_CUSTOMER,
		)
		frappe.set_user(USER)
		shown = self.preview()
		self.assertFalse(shown and "95" in (shown.get("discount") or ""), shown)

	# --- finding 42: the settings the browser is told -------------------------------

	def test_the_browser_reads_the_public_settings_of_the_cart(self):
		self.fill()
		frappe.set_user(USER)
		with a_request(cmd=f"{CART}.get_cart_quotation"):
			out = over_http(f"{CART}.get_cart_quotation")
		self.assertLessEqual(set(out["cart_settings"]), set(PUBLIC_SETTINGS))

	def test_a_page_keeps_the_whole_settings(self):
		self.fill()
		frappe.set_user(USER)
		context = cart.get_cart_quotation()
		self.assertTrue(context["cart_settings"].get("company"))

	# --- finding 43: the settings of a gateway --------------------------------------

	def test_the_page_reads_what_its_gateway_needs_and_nothing_else(self):
		info = {
			"account": frappe._dict(currency="CHF"),
			"gateway": frappe._dict(),
			"settings": {
				"publishable_key": "pk_public",
				"secret_key": "***",
				"owner": "staff@example.com",
				"merchant_uuid": "private",
			},
			"type": "stripe",
			"config": {"required_settings": ["publishable_key"], "context_ids": {}},
		}
		template = mock.MagicMock()
		template.render.return_value = "<form></form>"
		quotation = frappe._dict(name="QTN", rounded_total=10, grand_total=10)
		with (
			mock.patch.object(checkout, "get_gateway_info", return_value=info),
			mock.patch.object(checkout, "_document_to_pay", return_value=quotation),
			mock.patch.object(frappe, "get_template", return_value=template),
		):
			out = checkout.get_payment_template(self.gateway_account)
		self.assertFalse(out["error"], out)
		self.assertEqual({"publishable_key": "pk_public"}, out["config"])

	# --- finding 47: a link changes nothing a stranger chose ------------------------

	def follow(self, **form):
		with a_request("GET", form=form), self.assertRaises(frappe.Redirect):
			cart_page.handle_email_links()
		return frappe.local.flags.redirect_location

	def qty_in_cart(self):
		return flt(
			frappe.db.get_value(
				"Quotation Item", {"item_code": ITEM, "docstatus": 0, "parenttype": "Quotation"}, "qty"
			)
		)

	def test_a_reorder_link_opens_the_product_and_leaves_the_cart_alone(self):
		self.fill(qty=2)
		route = frappe.db.get_value("Website Item", {"item_code": ITEM}, "route")
		frappe.db.commit()
		frappe.set_user(USER)
		target = self.follow(add=ITEM, qty="-5")
		frappe.set_user("Administrator")
		self.assertEqual("/" + route.lstrip("/"), target)
		self.assertEqual(2, self.qty_in_cart())

	def test_the_reminder_s_own_coupon_is_applied_from_the_mail(self):
		coupon = make_coupon(customer=CUSTOMER)
		self.fill()
		frappe.db.commit()
		frappe.set_user(USER)
		self.assertEqual("/cart", self.follow(coupon=coupon.code))
		self.assertEqual(coupon.name, cart._get_cart_quotation().coupon_code)

	def test_a_coupon_that_is_not_the_customer_s_is_not_applied_by_a_link(self):
		coupon = make_coupon()
		self.fill()
		frappe.db.commit()
		frappe.set_user(USER)
		self.assertEqual("/cart", self.follow(coupon=coupon.code))
		self.assertFalse(cart._get_cart_quotation().coupon_code)

	def test_a_visitor_still_signs_in_first(self):
		frappe.set_user("Guest")
		target = self.follow(add=ITEM, qty="1")
		frappe.set_user("Administrator")
		self.assertIn("/login?redirect-to=", target)

	def test_a_list_is_not_a_link(self):
		frappe.set_user(USER)
		with a_request("GET", form={"add": ["!=", ""], "coupon": ["like", "%"]}):
			cart_page.handle_email_links()

	# --- finding 49: a rule the shop withdrew ---------------------------------------

	def test_a_disabled_shipping_rule_is_refused(self):
		self.fill()
		frappe.set_user(USER)
		with upstream_checks(), self.assertRaises(frappe.ValidationError):
			over_http(f"{CART}.apply_shipping_rule", shipping_rule=SHIPPING_OFF)

	def test_a_rule_the_shop_offers_applies(self):
		self.fill()
		frappe.set_user(USER)
		with upstream_checks():
			out = over_http(f"{CART}.apply_shipping_rule", shipping_rule=SHIPPING_ON)
		self.assertEqual(SHIPPING_ON, out["doc"].shipping_rule)

	# --- finding 50: what an error tells ---------------------------------------------

	def test_a_technical_error_stays_in_the_log(self):
		with mock.patch.object(cart, "update_cart", side_effect=Exception("Unknown column 'secret_column'")):
			out = cart_helpers.update_cart("X", 1)
		self.assertNotIn("secret_column", out["error"])
		self.assertFalse(out["success"])

	def test_a_refusal_written_for_the_buyer_is_shown(self):
		with mock.patch.object(cart, "update_cart", side_effect=frappe.ValidationError("Only 2 in stock")):
			out = cart_helpers.update_cart("X", 1)
		self.assertEqual("Only 2 in stock", out["error"])

	def test_a_filter_is_not_an_item(self):
		frappe.set_user(USER)
		with self.assertRaises(frappe.FrappeTypeError):
			over_http(
				"webshop.webshop.utils.cart_helpers.update_cart", item_code=["descendants of", "x"], qty=1
			)


class TestAGiftCardAtAGateway(ShopFixture):
	"""What the gift card lot needed outside the cart: the hook of a cancellation, and the paid order."""

	def test_the_cancellation_hook_is_listed(self):
		from webshop import hooks

		listed = hooks.doc_events["Sales Order"]["on_cancel"]
		self.assertIn("webshop.webshop.shopping_cart.cart.give_gift_card_back", listed)

	@needs_our_erpnext
	def test_a_till_card_is_no_coupon_of_a_paid_order(self):
		from webshop.controllers.payment_handler import _coupon_of_the_order

		shop_card, till_card = make_card(30), make_card(30, till=True)
		self.assertEqual(_coupon_of_the_order(frappe._dict(gift_card_coupon=shop_card.name)), shop_card.name)
		self.assertIsNone(_coupon_of_the_order(frappe._dict(gift_card_coupon=till_card.name)))
		self.assertIsNone(_coupon_of_the_order(frappe._dict(gift_card_coupon=None)))

	def test_a_card_that_no_longer_covers_the_cart_stops_before_the_payment(self):
		from webshop.controllers import payment_handler

		cart_ = frappe._dict(gift_card_coupon="_some card", name="_a cart")
		refused = frappe.ValidationError("no longer covers")
		with (
			mock.patch.object(payment_handler, "_get_cart_quotation", return_value=cart_),
			mock.patch.object(payment_handler, "ensure_gift_card_covers", side_effect=refused) as checked,
		):
			answer = payment_handler.PaymentHandler().create_payment_request()
		checked.assert_called_once_with(cart_)
		self.assertNotEqual((answer or {}).get("status"), "success")
