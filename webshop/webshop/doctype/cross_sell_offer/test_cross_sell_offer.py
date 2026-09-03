# //// Neoffice — added file (cross-sell offers, no upstream equivalent).
"""The offer, the pricing rule it generates, and the cart that applies it.

Fixtures are committed in setUpClass (FrappeTestCase rolls back between
tests) and removed in tearDownClass. Webshop Settings is a Single: what a
test writes there survives a rollback, hence snapshot / restore.
"""

import frappe
from erpnext.utilities.product import get_price
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, nowdate

from webshop.webshop.doctype.website_item.website_item import make_website_item
from webshop.webshop.shopping_cart.cart import _get_cart_quotation, update_cart
from webshop.webshop.tests.utils import (
	PREFIX,
	default_company,
	make_test_item,
	restore_webshop_settings,
	leaf_customer_group,
	selling_price_list,
	snapshot_webshop_settings,
)
from webshop.webshop.utils import cross_sell

USER = "_wstest_xsell@example.com"
CUSTOMER = "_WSTEST Cross-sell Customer"
SETTINGS = ("enabled", "show_price", "price_list", "enable_checkout", "company")


class TestCrossSellOffer(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.snapshot = snapshot_webshop_settings(SETTINGS)
		settings = frappe.get_single("Webshop Settings")
		settings.enabled = 1
		settings.show_price = 1
		settings.enable_checkout = 1
		if not settings.price_list:
			settings.price_list = selling_price_list()
		if not settings.company:
			settings.company = default_company()
		settings.flags.ignore_permissions = True
		settings.flags.ignore_mandatory = True
		settings.save()
		cls.price_list = settings.price_list

		cls.suffix = frappe.generate_hash(length=5).upper()
		cls.trigger = cls.priced_item(f"{PREFIX} Printer {cls.suffix}", 200)
		cls.offered = cls.priced_item(f"{PREFIX} Ink {cls.suffix}", 50)
		cls.make_customer_with_user()
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		cls.purge()
		restore_webshop_settings(cls.snapshot)
		frappe.db.commit()
		super().tearDownClass()

	@classmethod
	def priced_item(cls, code, rate):
		item = make_test_item(code, is_stock_item=0)
		frappe.get_doc(
			{
				"doctype": "Item Price",
				"item_code": item.name,
				"price_list": cls.price_list,
				"price_list_rate": rate,
				"selling": 1,
			}
		).insert(ignore_permissions=True)
		make_website_item(frappe.get_doc("Item", item.name))
		return item.name

	@classmethod
	def make_customer_with_user(cls):
		if not frappe.db.exists("Customer", CUSTOMER):
			frappe.get_doc(
				{
					"doctype": "Customer",
					"customer_name": CUSTOMER,
					"customer_group": leaf_customer_group(),
					"territory": frappe.db.get_value("Territory", {"lft": 1}, "name"),
				}
			).insert(ignore_permissions=True)
		if not frappe.db.exists("User", USER):
			frappe.flags.mute_emails = True
			frappe.get_doc(
				{
					"doctype": "User",
					"email": USER,
					"first_name": "Cross-sell",
					"user_type": "Website User",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
		if not frappe.db.exists("Contact", {"email_id": USER}):
			frappe.get_doc(
				{
					"doctype": "Contact",
					"first_name": "Cross-sell",
					"email_ids": [{"email_id": USER, "is_primary": 1}],
					"links": [{"link_doctype": "Customer", "link_name": CUSTOMER}],
				}
			).insert(ignore_permissions=True)

	@classmethod
	def purge(cls):
		for name in frappe.get_all("Quotation", filters={"party_name": CUSTOMER}, pluck="name"):
			frappe.delete_doc("Quotation", name, force=True, ignore_permissions=True)
		cls.clean_offers()
		for code in (cls.trigger, cls.offered, *frappe.get_all("Item", filters={"name": ("like", f"{PREFIX} Hidden%")}, pluck="name")):
			for name in frappe.get_all("Website Item", filters={"item_code": code}, pluck="name"):
				frappe.delete_doc("Website Item", name, force=True, ignore_permissions=True)
			frappe.db.delete("Item Price", {"item_code": code})
			frappe.delete_doc("Item", code, force=True, ignore_permissions=True)
		for name in frappe.get_all("Contact", filters={"email_id": USER}, pluck="name"):
			frappe.delete_doc("Contact", name, force=True, ignore_permissions=True)
		if frappe.db.exists("User", USER):
			frappe.delete_doc("User", USER, force=True, ignore_permissions=True)
		if frappe.db.exists("Customer", CUSTOMER):
			frappe.delete_doc("Customer", CUSTOMER, force=True, ignore_permissions=True)

	def setUp(self):
		frappe.set_user("Administrator")
		self.clean_offers()

	def tearDown(self):
		frappe.set_user("Administrator")
		self.clean_offers()

	@classmethod
	def clean_offers(cls):
		"""The cart commits (update_cart): an offer made in a test outlives the rollback."""
		for name in frappe.get_all("Cross Sell Offer", filters={"title": ("like", f"{PREFIX}%")}, pluck="name"):
			frappe.delete_doc("Cross Sell Offer", name, force=True, ignore_permissions=True)
		for name in frappe.get_all("Pricing Rule", filters={"title": ("like", f"Cross-sell: {PREFIX}%")}, pluck="name"):
			frappe.delete_doc("Pricing Rule", name, force=True, ignore_permissions=True)
		frappe.db.commit()

	def make_offer(self, **values):
		data = {
			"doctype": "Cross Sell Offer",
			"title": f"{PREFIX} Ink with printer {self.suffix}",
			"trigger_type": "Item",
			"trigger_item": self.trigger,
			"offer_item": self.offered,
			"relation": "Consumable",
			"discount_type": "Percentage",
			"discount_percentage": 15,
		}
		data.update(values)
		return frappe.get_doc(data).insert(ignore_permissions=True)

	def cart_rows(self):
		quotation = _get_cart_quotation()
		return {d.item_code: d for d in quotation.items}

	def empty_cart(self):
		for code in list(self.cart_rows()):
			update_cart(code, 0)

	# --- the rule behind the offer -------------------------------------

	def test_offer_generates_and_maintains_its_pricing_rule(self):
		offer = self.make_offer()
		self.assertTrue(offer.pricing_rule)

		rule = frappe.get_doc("Pricing Rule", offer.pricing_rule)
		self.assertEqual(rule.apply_on, "Item Code")
		self.assertEqual([d.item_code for d in rule.items], [self.trigger])
		self.assertEqual(rule.apply_rule_on_other, "Item Code")
		self.assertEqual(rule.other_item_code, self.offered)
		self.assertEqual(rule.price_or_product_discount, "Price")
		self.assertEqual(rule.rate_or_discount, "Discount Percentage")
		self.assertEqual(flt(rule.discount_percentage), 15)
		self.assertEqual(rule.selling, 1)
		self.assertEqual(rule.disable, 0)

		offer.enabled = 0
		offer.discount_percentage = 20
		offer.save()
		rule.reload()
		self.assertEqual(rule.disable, 1)
		self.assertEqual(flt(rule.discount_percentage), 20)

		offer.discount_type = "None"
		offer.save()
		self.assertFalse(frappe.db.exists("Pricing Rule", rule.name))
		self.assertFalse(offer.pricing_rule)

		offer.discount_type = "Amount"
		offer.discount_amount = 5
		offer.save()
		rule_name = offer.pricing_rule
		self.assertEqual(frappe.db.get_value("Pricing Rule", rule_name, "rate_or_discount"), "Discount Amount")
		offer.delete()
		self.assertFalse(frappe.db.exists("Pricing Rule", rule_name))

	def test_a_free_offer_is_a_product_rule(self):
		offer = self.make_offer(discount_type="Free", offer_qty=2)
		rule = frappe.get_doc("Pricing Rule", offer.pricing_rule)
		self.assertEqual(rule.price_or_product_discount, "Product")
		self.assertEqual(rule.free_item, self.offered)
		self.assertEqual(flt(rule.free_qty), 2)
		self.assertFalse(rule.apply_rule_on_other)

	def test_the_offer_needs_a_published_item_and_a_sane_advantage(self):
		self.assertRaises(frappe.ValidationError, self.make_offer, offer_item=self.trigger)
		self.assertRaises(frappe.ValidationError, self.make_offer, discount_percentage=150)
		self.assertRaises(frappe.ValidationError, self.make_offer, discount_type="Amount", discount_amount=0)
		unpublished = make_test_item(f"{PREFIX} Hidden {self.suffix}", is_stock_item=0)
		self.assertRaises(frappe.ValidationError, self.make_offer, offer_item=unpublished.name)

	# --- what the shop shows --------------------------------------------

	def test_matching_respects_trigger_cart_and_validity(self):
		offer = self.make_offer()
		found = cross_sell.matching_offers([self.trigger], cart_codes=[self.trigger], placement="cart")
		self.assertEqual([o.name for o in found], [offer.name])
		self.assertEqual(found[0].trigger_item_code, self.trigger)

		self.assertEqual(cross_sell.matching_offers([self.offered], placement="cart"), [])
		self.assertEqual(
			cross_sell.matching_offers([self.trigger], cart_codes=[self.trigger, self.offered], placement="cart"), []
		)
		self.assertEqual([o.name for o in cross_sell.matching_offers([self.trigger], placement="product")], [offer.name])

		offer.show_at_checkout = 0
		offer.save()
		self.assertEqual(cross_sell.matching_offers([self.trigger], placement="checkout"), [])

		offer.valid_upto = add_days(nowdate(), -1)
		offer.save()
		self.assertEqual(cross_sell.matching_offers([self.trigger], placement="cart"), [])

	def test_a_group_trigger_matches_any_item_of_the_group(self):
		group = frappe.db.get_value("Item", self.trigger, "item_group")
		offer = self.make_offer(trigger_type="Item Group", trigger_item_group=group, trigger_item=None)
		found = cross_sell.matching_offers([self.trigger], placement="cart")
		self.assertEqual([o.name for o in found], [offer.name])

	def test_the_shop_computes_the_advantage_like_the_rule_will(self):
		offer = self.make_offer()
		shown = cross_sell.describe(cross_sell.matching_offers([self.trigger], placement="product")[0])
		self.assertEqual(shown["item_code"], self.offered)
		self.assertEqual(shown["price"], 50)
		self.assertEqual(shown["offer_price"], 42.5)
		self.assertEqual(shown["advantage"], "-15 %")
		self.assertIn(frappe.db.get_value("Item", self.trigger, "item_name"), shown["headline"])
		self.assertTrue(shown["route"])

	def test_the_catalogue_price_ignores_the_offer_rule(self):
		"""The rule is conditional on the trigger: neither item is discounted on its own."""
		self.make_offer()
		settings = frappe.get_cached_doc("Webshop Settings")
		for code, rate in ((self.trigger, 200), (self.offered, 50)):
			price = get_price(code, self.price_list, settings.default_customer_group, settings.company)
			self.assertEqual(flt(price.get("price_list_rate")), rate, code)
			self.assertFalse(price.get("formatted_mrp"), code)

	# --- the cart -----------------------------------------------------------

	def test_the_cart_prices_the_offer_and_not_the_trigger(self):
		offer = self.make_offer()
		frappe.set_user(USER)
		self.empty_cart()

		update_cart(self.trigger, 1)
		offers = cross_sell.get_offers("cart")
		self.assertEqual([o["name"] for o in offers], [offer.name])
		self.assertEqual(offers[0]["offer_price"], 42.5)

		result = cross_sell.accept_offer(offer.name)
		self.assertEqual(flt(result["rate"]), 42.5)
		rows = self.cart_rows()
		self.assertEqual(flt(rows[self.offered].rate), 42.5)
		self.assertEqual(flt(rows[self.offered].discount_percentage), 15)
		self.assertEqual(flt(rows[self.trigger].rate), 200)
		self.assertEqual(flt(rows[self.trigger].discount_percentage), 0)

		# once in the cart, the offer is not shown again
		self.assertEqual(cross_sell.get_offers("cart"), [])
		self.assertEqual(frappe.db.get_value("Cross Sell Offer", offer.name, "acceptances"), 1)

		# the trigger leaves: the advantage goes with it
		update_cart(self.trigger, 0)
		rows = self.cart_rows()
		self.assertEqual(flt(rows[self.offered].rate), 50)
		self.assertEqual(flt(rows[self.offered].discount_percentage), 0)

		# and the checkout box can be unticked
		update_cart(self.trigger, 1)
		cross_sell.accept_offer(offer.name, remove=1)
		self.assertNotIn(self.offered, self.cart_rows())

	def test_two_offers_on_one_trigger_both_apply(self):
		"""Ink AND paper with the printer: two rules on the trigger line, no conflict."""
		paper = self.priced_item(f"{PREFIX} Paper {self.suffix}", 20)
		try:
			ink = self.make_offer()
			self.make_offer(title=f"{PREFIX} Paper with printer {self.suffix}", offer_item=paper, discount_percentage=10)
			frappe.set_user(USER)
			self.empty_cart()

			update_cart(self.trigger, 1)
			names = [o["item_code"] for o in cross_sell.get_offers("cart", limit=5)]
			self.assertEqual(sorted(names), sorted([self.offered, paper]))

			cross_sell.accept_offer(ink.name)
			update_cart(paper, 1)
			rows = self.cart_rows()
			self.assertEqual(flt(rows[self.trigger].rate), 200)
			self.assertEqual(flt(rows[self.offered].rate), 42.5)
			self.assertEqual(flt(rows[paper].rate), 18)
		finally:
			frappe.set_user("Administrator")
			self.empty_cart_of(USER)
			self.clean_offers()
			for name in frappe.get_all("Website Item", filters={"item_code": paper}, pluck="name"):
				frappe.delete_doc("Website Item", name, force=True, ignore_permissions=True)
			frappe.db.delete("Item Price", {"item_code": paper})
			frappe.delete_doc("Item", paper, force=True, ignore_permissions=True)
			frappe.db.commit()

	def empty_cart_of(self, user):
		frappe.set_user(user)
		self.empty_cart()
		frappe.set_user("Administrator")

	def test_the_product_page_adds_both(self):
		offer = self.make_offer()
		frappe.set_user(USER)
		self.empty_cart()

		cross_sell.accept_offer(offer.name, with_trigger=1)
		rows = self.cart_rows()
		self.assertEqual(flt(rows[self.trigger].qty), 1)
		self.assertEqual(flt(rows[self.offered].rate), 42.5)
