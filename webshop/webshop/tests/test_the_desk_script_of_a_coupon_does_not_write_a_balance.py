# //// Neoffice — added file (no upstream equivalent).
"""Opening a gift card in the desk does not write its balance (maintenance#3239).

The desk script of Coupon Code (public/js/coupon_code.js) used to read the discount of the card's Pricing Rule, put it into
the balance and save the card, every time the form was opened. The shop's cards of one amount share one rule, so opening a
card gave it back what a sister had spent, or took away what it still held. The balance is the card's own: the script shows
the field, read-only, and writes nothing into it but the zero of a coupon that stops being a gift card.
"""

import re

import frappe
from frappe.tests.utils import FrappeTestCase

# the value the script gives the balance: `set_value('gift_card_amount', <value>)`
WRITES = re.compile(r"set_value\(\s*['\"]gift_card_amount['\"]\s*,\s*([^)]+?)\s*\)")
# a read of the rule: get_value('Pricing Rule', ...)
RULE_READ = re.compile(r"get_value\(\s*['\"]Pricing Rule['\"]")


def _script():
	with open(frappe.get_app_path("webshop", "public", "js", "coupon_code.js"), encoding="utf-8") as handle:
		return handle.read()


class TestTheDeskScriptOfACouponDoesNotWriteABalance(FrappeTestCase):
	def test_the_script_does_not_read_the_pricing_rule(self):
		self.assertIsNone(RULE_READ.search(_script()), "the balance of a card is not read from its rule")

	def test_the_only_balance_the_script_writes_is_zero(self):
		written = WRITES.findall(_script())
		self.assertTrue(written, "the script clears the balance of a coupon that is no gift card")
		self.assertEqual({value for value in written}, {"0"}, "a balance written from anywhere else is the defect")
