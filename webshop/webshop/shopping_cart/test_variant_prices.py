# //// Neoffice — added file (no upstream equivalent): a template's variant prices, kept a few minutes.
# //// neoffice-maintenance#691 lot 5, 2026-09-25.
"""get_template_price_from_variants priced every variant through ERPNext's pricing rules on every
render. product_info._variant_prices keeps the numbers per template, list, group, company,
customer, warehouse and day, and the price and pricing rule hooks drop them."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.shopping_cart import product_info

VARIANTS = [
	frappe._dict(item_code="TEE-S", price_list_rate=40.0, currency="CHF"),
	frappe._dict(item_code="TEE-M", price_list_rate=40.0, currency="CHF"),
	frappe._dict(item_code="TEE-L", price_list_rate=45.0, currency="CHF"),
]


def fake_price(item_code, price_list, customer_group, company, qty=1, party=None, warehouse=None):
	"""TEE-S is on sale at 30, the others sell at their list price."""
	base = {row.item_code: row.price_list_rate for row in VARIANTS}[item_code]
	if item_code == "TEE-S":
		return frappe._dict(price_list_rate=30.0, formatted_mrp="CHF 40.00")
	return frappe._dict(price_list_rate=base)


class TestVariantPrices(FrappeTestCase):
	def setUp(self):
		product_info.clear_variant_prices()

	def tearDown(self):
		product_info.clear_variant_prices()

	def price(self, party=None, price_list="Retail"):
		with (
			patch.object(product_info, "get_price", side_effect=fake_price) as get_price,
			patch.object(product_info, "_priced_variants", return_value=VARIANTS),
		):
			found = product_info.get_template_price_from_variants(
				"TEE", price_list, "Individual", "Atelier", party=party, warehouse="Store"
			)
		return found, get_price.call_count

	def test_the_second_render_prices_nothing(self):
		first, calls = self.price()
		self.assertEqual(calls, 3)
		second, calls = self.price()
		self.assertEqual(calls, 0, "the variants' prices came from the cache")
		self.assertEqual(first, second, "the same price object, built from the kept numbers")
		self.assertEqual((first.price_list_rate, first.max_price, first.mrp, first.is_range), (30.0, 45.0, 40.0, True))

	def test_each_customer_and_list_has_its_own_answer(self):
		self.price()
		customer = frappe._dict(doctype="Customer", name="Reseller")
		self.assertEqual(self.price(party=customer)[1], 3, "a customer's rules are not a visitor's")
		self.assertEqual(self.price(price_list="Wholesale")[1], 3, "another list, another answer")
		self.assertEqual(self.price(party=customer)[1], 0)

	def test_a_price_or_a_rule_change_drops_what_was_kept(self):
		from webshop.webshop.crud_events.item_price import invalidate_price_cache
		from webshop.webshop.crud_events.pricing_rule import invalidate_discount_cache

		for hook, doc in (
			(invalidate_price_cache, frappe._dict(selling=1, item_code="TEE-S", price_list="Retail")),
			# a Rate rule: neither a discount nor a coupon, the discount caches ignore it
			(invalidate_discount_cache, frappe._dict(selling=1, name="PRLE-1", coupon_code_based=0, discount_percentage=0, discount_amount=0)),
		):
			with self.subTest(hook=hook.__name__):
				self.price()
				hook.execute(doc)
				self.assertEqual(self.price()[1], 3, "recomputed after the change")

	def test_a_template_without_priced_variants_asks_once(self):
		with patch.object(product_info, "get_price") as get_price, patch.object(product_info, "_priced_variants", return_value=[]) as sql:
			self.assertEqual(product_info.get_template_price_from_variants("TEE", "Retail", "Individual", "Atelier"), {})
			self.assertEqual(product_info.get_template_price_from_variants("TEE", "Retail", "Individual", "Atelier"), {})
		self.assertEqual(sql.call_count, 1)
		get_price.assert_not_called()
