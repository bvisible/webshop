# //// Neoffice — added file (no upstream equivalent).
"""The customer's account pages are the shop's pages (2026-09-14): Frappe renders them, and
update_website_context gives them the shop's scope class so they sit on the chrome's ground
with the chrome's ink, like the cart and the checkout."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.shopping_cart import utils

PORTAL = frappe._dict(
	menu=[
		frappe._dict(route="/orders", enabled=1),
		frappe._dict(route="/addresses", enabled=1),
		frappe._dict(route="/issues", enabled=0),
	],
	custom_menu=[frappe._dict(route="/gift_cards", enabled=1)],
)


class TestAccountPages(FrappeTestCase):
	def is_account(self, path):
		with patch.object(utils.frappe, "get_cached_doc", return_value=PORTAL):
			return utils.is_account_page(frappe._dict(path=path))

	def test_the_portal_menu_and_frappe_s_own_account_pages(self):
		for path in ("orders", "orders/SAL-ORD-0001", "/addresses", "addresses/new", "gift_cards", "me", "update-password"):
			self.assertTrue(self.is_account(path), path)

	def test_the_address_asked_for_counts_not_only_the_page_that_answers(self):
		# //// Neoffice — /orders is answered by Frappe's list page: the context says "list", the request "orders"
		with patch.object(utils.frappe, "get_cached_doc", return_value=PORTAL), patch.object(
			utils.frappe.local, "path", "orders", create=True
		):
			self.assertTrue(utils.is_account_page(frappe._dict(path="list")))

	def test_other_pages_are_not_account_pages(self):
		for path in ("", "all-products", "ordersx", "issues", "login", "contact"):
			self.assertFalse(self.is_account(path), path)

	def test_the_class_is_added_once_and_never_replaces_the_page_s_own(self):
		context = frappe._dict(path="orders", body_class="web-list")
		with patch.object(utils.frappe, "get_cached_doc", return_value=PORTAL):
			utils.update_website_context(context)
			utils.update_website_context(context)
		self.assertEqual(context.body_class.split(), ["web-list", "product-page"])
		other = frappe._dict(path="all-products", body_class="product-page")
		with patch.object(utils.frappe, "get_cached_doc", return_value=PORTAL):
			utils.update_website_context(other)
		self.assertEqual(other.body_class, "product-page")
