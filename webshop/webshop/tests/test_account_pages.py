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


_real_get_cached_doc = frappe.get_cached_doc


def portal_settings(doctype, *args, **kwargs):
	"""Portal Settings from the fixture above; every other document is the real one (the hook
	also reads Webshop Settings)."""
	return PORTAL if doctype == "Portal Settings" else _real_get_cached_doc(doctype, *args, **kwargs)


class TestAccountPages(FrappeTestCase):
	def is_account(self, path):
		with patch.object(utils.frappe, "get_cached_doc", side_effect=portal_settings):
			return utils.is_account_page(frappe._dict(path=path))

	def test_the_portal_menu_and_frappe_s_own_account_pages(self):
		for path in ("orders", "orders/SAL-ORD-0001", "/addresses", "addresses/new", "gift_cards", "me", "update-password"):
			self.assertTrue(self.is_account(path), path)

	def test_the_address_asked_for_counts_not_only_the_page_that_answers(self):
		# //// Neoffice — /orders is answered by Frappe's list page: the context says "list", the request "orders"
		with patch.object(utils.frappe, "get_cached_doc", side_effect=portal_settings), patch.object(
			utils.frappe.local, "path", "orders", create=True
		):
			self.assertTrue(utils.is_account_page(frappe._dict(path="list")))

	def test_the_address_form_is_an_account_page_even_off_the_menu(self):
		# //// Neoffice — the shop's address page and the checkout lead to it; a portal menu may not list it
		bare = frappe._dict(menu=[], custom_menu=[])
		with patch.object(utils.frappe, "get_cached_doc", side_effect=lambda d, *a, **k: bare if d == "Portal Settings" else _real_get_cached_doc(d, *a, **k)):
			self.assertTrue(utils.is_account_page(frappe._dict(path="addresses/new")))

	def test_other_pages_are_not_account_pages(self):
		for path in ("", "all-products", "ordersx", "issues", "login", "contact"):
			self.assertFalse(self.is_account(path), path)

	def test_the_class_is_added_once_and_never_replaces_the_page_s_own(self):
		context = frappe._dict(path="orders", body_class="web-list")
		with patch.object(utils.frappe, "get_cached_doc", side_effect=portal_settings):
			utils.update_website_context(context)
			utils.update_website_context(context)
		self.assertEqual(context.body_class.split(), ["web-list", "product-page", "wsp-account"])
		other = frappe._dict(path="all-products", body_class="product-page")
		with patch.object(utils.frappe, "get_cached_doc", side_effect=portal_settings):
			utils.update_website_context(other)
		self.assertEqual(other.body_class, "product-page")

	def test_the_account_s_pages_have_english_hyphenated_addresses_and_the_old_ones_lead_to_them(self):
		# //// Neoffice — 2026-10-25: /my_addresses, /gift_cards and /loyalty_points had underscores
		redirects = frappe.get_hooks("website_redirects", app_name="webshop")
		rules = frappe.get_hooks("website_route_rules", app_name="webshop")
		moved = {
			"/my_addresses": ("/my-addresses", "my_addresses"),
			"/gift_cards": ("/gift-cards", "gift_cards"),
			"/loyalty_points": ("/loyalty-points", "loyalty_points"),
		}
		for old, (new, endpoint) in moved.items():
			redirect = [r for r in redirects if r["source"] == old]
			self.assertEqual([(r["target"], r.get("redirect_http_status")) for r in redirect], [(new, 301)], old)
			self.assertIn({"from_route": new, "to_route": endpoint}, rules, new)
		# no chain: an address a redirect leads to is never itself redirected
		sources = {r["source"] for r in redirects}
		for rule in redirects:
			self.assertNotIn(rule["target"], sources, rule)

	def test_the_renamed_pages_stay_private(self):
		from webshop.webshop.seo import meta, robots

		for path in ("/my-addresses", "/gift-cards", "/loyalty-points", "/my-requests", "/my-bookings"):
			self.assertTrue(
				any(
					pattern[:-1] == path if pattern.endswith("$") else path.startswith(pattern.rstrip("?"))
					for pattern in robots.PRIVATE_PATHS
				),
				path,
			)
			context = frappe._dict(path=path.strip("/"))
			with patch.object(utils.frappe, "get_cached_doc", side_effect=portal_settings):
				self.assertTrue(meta.should_not_index(path.strip("/"), context), path)

	def test_the_account_has_its_own_scope_and_the_shop_s_pages_do_not(self):
		# //// Neoffice — webshop_account.scss hangs on it (2026-10-25): the cart, the checkout and the
		# //// catalogue carry `product-page` too, and must not take the account's titles and surfaces
		for path in ("orders", "my_addresses", "gift_cards", "update-profile/someone@example.com", "address/new"):
			context = frappe._dict(path=path)
			with patch.object(utils.frappe, "get_cached_doc", side_effect=portal_settings):
				utils.update_website_context(context)
			self.assertIn("wsp-account", context.body_class.split(), path)
		for path in ("cart", "checkout", "all-products", "wishlist"):
			context = frappe._dict(path=path, body_class="product-page")
			with patch.object(utils.frappe, "get_cached_doc", side_effect=portal_settings):
				utils.update_website_context(context)
			self.assertNotIn("wsp-account", context.body_class.split(), path)
