# //// Neoffice — added file (no upstream equivalent).
"""A gift card the shop sold goes with the sale that created it (maintenance#2816, the till's rule of #2725).

A sale of two cards of 50 is written as rows (the sale, its line with the codes of its cards, the cards and the Pricing
Rule every shop card of 50 shares); the cancel and the credit note are played as the head accountant would, by the
invoice's own hooks. An unspent card is voided with its sale, a spent one stops it, a credit note takes one card of its
amount and gives it back when it is cancelled, and the shared rule is never touched.
"""

import json
from unittest import mock

import frappe
from frappe.tests.roles import as_role
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.shopping_cart import gift_card_sale

SALE = "_T2816-SINV"
RETURN = "_T2816-RET"
ITEM = "_T2816 gift card"
RULE = "_T2816 Gift Card 50.00"
CARDS = ("_T2816-CARD-A", "_T2816-CARD-B")


class TestAShopGiftCardGoesWithItsSale(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.db.savepoint("shop_card_sale")
		self.addCleanup(frappe.db.rollback, save_point="shop_card_sale")
		patch = mock.patch.object(gift_card_sale, "is_gift_card_item", side_effect=lambda code: code == ITEM)
		patch.start()
		self.addCleanup(patch.stop)
		frappe.get_doc(
			{
				"doctype": "Pricing Rule",
				"name": RULE,
				"title": RULE,
				"apply_on": "Transaction",
				"price_or_product_discount": "Price",
				"selling": 1,
				"coupon_code_based": 1,
				"rate_or_discount": "Discount Amount",
				"discount_amount": 50,
				"disable": 0,
			}
		).db_insert()
		self.sale = self.invoice(SALE, qty=2, codes=list(CARDS))
		for code in CARDS:
			frappe.get_doc(
				{
					"doctype": "Coupon Code",
					"name": code,
					"coupon_name": code,
					"coupon_code": code,
					"coupon_type": "Gift Card",
					"pricing_rule": RULE,
					"maximum_use": 9999,
					"used": 0,
					"sales_invoice": SALE,
					"gift_card_amount": 50,
				}
			).db_insert()

	def invoice(self, name, qty, codes=None, against=None):
		"""A submitted invoice of `qty` gift cards of 50, as a row; a credit note when `against` names its sale."""
		doc = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"name": name,
				"docstatus": 1,
				"currency": "CHF",
				"is_return": 1 if against else 0,
				"return_against": against,
				"items": [
					{
						"doctype": "Sales Invoice Item",
						"name": f"{name}-1",
						"item_code": ITEM,
						"qty": -qty if against else qty,
						"rate": 50,
						"gift_card_data": json.dumps({"codes": codes}) if codes else None,
					}
				],
			}
		)
		doc.db_insert()
		for row in doc.items:
			row.db_insert()
		return frappe.get_doc("Sales Invoice", name)

	def card(self, code):
		return frappe.db.get_value("Coupon Code", code, ["gift_card_amount", "used"], as_dict=True)

	def spend(self, code, left):
		frappe.db.set_value("Coupon Code", code, "gift_card_amount", left)

	def act(self, hook, doc):
		"""The invoice's hook of that event, as Frappe runs them, by the person who cancels or returns a sale."""
		# the shop's own hooks, read from its hooks.py (the site's cache of every app's hooks may be older)
		hooks = frappe.get_hooks("doc_events", app_name="webshop")["Sales Invoice"][hook]
		self.assertIn(f"webshop.webshop.shopping_cart.gift_card_sale.{hook}", hooks)
		with as_role("head_accountant"):
			frappe.get_attr(f"webshop.webshop.shopping_cart.gift_card_sale.{hook}")(doc)

	def assertTheRuleIsUntouched(self):
		rule = frappe.db.get_value("Pricing Rule", RULE, ["disable", "discount_amount"], as_dict=True)
		self.assertEqual((rule.disable, rule.discount_amount), (0, 50), "every shop card of 50 shares this rule")

	def test_a_cancelled_sale_voids_its_unspent_cards_and_leaves_the_shared_rule(self):
		self.act("on_cancel", self.sale)
		for code in CARDS:
			self.assertEqual((self.card(code).gift_card_amount, self.card(code).used), (0, 1), code)
		self.assertTheRuleIsUntouched()
		with self.assertRaises(frappe.ValidationError):
			# the desk, the till and the shop all ask ERPNext whether a card holds something
			from erpnext.accounts.doctype.pricing_rule.utils import validate_coupon_code

			validate_coupon_code(CARDS[0])

	def test_a_card_already_spent_stops_the_cancel_and_keeps_what_it_holds(self):
		self.spend(CARDS[1], 30)
		with self.assertRaises(frappe.ValidationError) as refused:
			self.act("on_cancel", self.sale)
		self.assertIn(CARDS[1], str(refused.exception))
		self.assertEqual(self.card(CARDS[0]).gift_card_amount, 50, "nothing is voided when one card refuses")
		self.assertEqual(self.card(CARDS[1]).gift_card_amount, 30)

	def test_a_credit_note_takes_one_unspent_card_and_gives_it_back_when_it_is_cancelled(self):
		self.spend(CARDS[0], 20)
		credit_note = self.invoice(RETURN, qty=1, against=SALE)
		self.act("on_submit", credit_note)
		self.assertEqual(self.card(CARDS[0]).gift_card_amount, 20, "the spent card is not the one taken")
		self.assertEqual((self.card(CARDS[1]).gift_card_amount, self.card(CARDS[1]).used), (0, 1))
		self.assertTheRuleIsUntouched()

		self.act("on_cancel", credit_note)
		self.assertEqual((self.card(CARDS[1]).gift_card_amount, self.card(CARDS[1]).used), (50, 0))
		self.assertEqual(self.card(CARDS[0]).gift_card_amount, 20)

	def test_a_credit_note_of_a_card_already_spent_is_refused(self):
		for code in CARDS:
			self.spend(code, 10)
		credit_note = self.invoice(RETURN, qty=1, against=SALE)
		with self.assertRaises(frappe.ValidationError):
			self.act("on_submit", credit_note)
		self.assertEqual([self.card(code).gift_card_amount for code in CARDS], [10, 10])

	def test_a_card_voided_by_a_credit_note_is_not_taken_twice(self):
		credit_note = self.invoice(RETURN, qty=1, against=SALE)
		self.act("on_submit", credit_note)
		# The other card is still whole: the cancel of what is left of the sale voids it alone
		self.act("on_cancel", self.sale)
		self.assertEqual([self.card(code).gift_card_amount for code in CARDS], [0, 0])
		voids = frappe.get_all(
			"Comment",
			filters={"reference_doctype": "Coupon Code", "content": ["like", "%(void _T2816-%"]},
			pluck="reference_name",
		)
		self.assertEqual(sorted(voids), sorted(CARDS), "each card voided once")
