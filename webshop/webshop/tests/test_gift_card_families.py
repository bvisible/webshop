# //// Neoffice — added file (no upstream equivalent).
"""Two families of gift card live on one instance, and both must be spendable once.

  issued by the till -> coupon_type "Promotional", pos_next_gift_card = 1
  issued by the shop -> coupon_type "Gift Card"

The shop only knew the second. A card bought at the counter and spent here was
read as an ordinary promotional coupon: its discount came from its Pricing Rule,
its BALANCE was never read and never decremented, and those cards carry
`maximum_use = 0` — no cap. Measured end to end on 2026-09-22: a 15.- card
granted its 15.- on a completed order, came back untouched, and was accepted
again on the very next cart. The till had the mirror defect on our cards (#646).
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.shopping_cart.cart import (
	is_gift_card_coupon,
	issued_by_the_till,
	settle_till_card,
)


class TestGiftCardFamilies(FrappeTestCase):
	def test_both_families_are_gift_cards(self):
		shop_card = frappe._dict({"coupon_type": "Gift Card"})
		till_card = frappe._dict({"coupon_type": "Promotional", "pos_next_gift_card": 1})
		plain_coupon = frappe._dict({"coupon_type": "Promotional"})

		self.assertTrue(is_gift_card_coupon(shop_card))
		self.assertTrue(is_gift_card_coupon(till_card), "a till card is a gift card")
		self.assertFalse(is_gift_card_coupon(plain_coupon), "a promotional coupon is not")
		self.assertFalse(is_gift_card_coupon(None))

	def test_only_the_till_card_is_settled_in_place(self):
		"""A shop card is split; a till card keeps the code its holder carries."""
		self.assertTrue(issued_by_the_till(frappe._dict({"pos_next_gift_card": 1})))
		self.assertFalse(issued_by_the_till(frappe._dict({"coupon_type": "Gift Card"})))

	def test_the_settlement_takes_what_was_spent_and_nothing_more(self):
		card = frappe._dict({"name": "_Test Gift Card Family", "gift_card_amount": 15})
		written = {}
		original = frappe.db.set_value

		def capture(doctype, name, values, *args, **kwargs):
			written.update(values if isinstance(values, dict) else {values: args[0]})

		frappe.db.set_value = capture
		try:
			self.assertEqual(settle_till_card(card, 10), 5)
			self.assertEqual(written.get("gift_card_amount"), 5)
			self.assertNotIn("used", written, "a card with a balance left is not used up")

			written.clear()
			card.gift_card_amount = 5
			self.assertEqual(settle_till_card(card, 5), 0)
			self.assertEqual(written.get("gift_card_amount"), 0)
			self.assertEqual(written.get("used"), 1, "an emptied card is marked used")

			# Spending more than the card holds never makes it negative.
			written.clear()
			card.gift_card_amount = 5
			self.assertEqual(settle_till_card(card, 50), 0)
		finally:
			frappe.db.set_value = original
