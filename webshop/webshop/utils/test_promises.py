# //// Neoffice — added file (no upstream equivalent).
"""The shop's promises: from the settings, from a site profile, or nothing at all."""

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.doctype.webshop_settings.webshop_settings import get_shopping_cart_settings
from webshop.webshop.utils.promises import shopping_promises


class TestShoppingPromises(FrappeTestCase):
	def test_nothing_set_promises_nothing(self):
		self.assertEqual(shopping_promises(frappe._dict()), [])
		self.assertEqual(shopping_promises(frappe._dict(free_shipping_from=0, delivery_delay="  ", return_days=0)), [])

	def test_each_line_in_reading_order(self):
		lines = shopping_promises(
			frappe._dict(free_shipping_from=100, delivery_delay="2-4 working days", return_days=30, promise_note="Pick-up in store")
		)
		self.assertEqual([line["key"] for line in lines], ["shipping", "delay", "returns", "note"])
		self.assertIn("100", lines[0]["text"])
		self.assertIn("2-4 working days", lines[1]["text"])
		self.assertIn("30", lines[2]["text"])
		self.assertEqual(lines[3]["text"], "Pick-up in store")
		self.assertEqual([line["icon"] for line in lines], ["truck", "clock", "return", "check"])

	def test_the_threshold_is_formatted_in_the_price_lists_currency(self):
		price_list = frappe.db.get_value("Price List", {"selling": 1, "enabled": 1}, "name")
		if not price_list:
			self.skipTest("no selling price list on this site")
		currency = frappe.db.get_value("Price List", price_list, "currency")
		lines = shopping_promises(frappe._dict(free_shipping_from=49.5, price_list=price_list))
		self.assertEqual(len(lines), 1)
		self.assertIn("49.5", lines[0]["text"])
		if currency:
			self.assertIn(currency, lines[0]["text"])

	def test_a_site_profile_overrides_only_what_it_sets(self):
		before = getattr(frappe.local, "website_profile_doc", None)
		frappe.local.website_profile_doc = {"name": "_Test Site", "return_days": 14, "delivery_delay": ""}
		try:
			settings = get_shopping_cart_settings()
			self.assertEqual(settings.get("return_days"), 14)
			shop_delay = frappe.get_cached_doc("Webshop Settings").get("delivery_delay")
			self.assertEqual(settings.get("delivery_delay"), shop_delay)
		finally:
			frappe.local.website_profile_doc = before
