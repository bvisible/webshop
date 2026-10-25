# //// Neoffice — added file (no upstream equivalent).
"""The customer's account carries one menu on every page of it (2026-10-25).

Measured on osiris with a portal customer: the three links of /me led to pages with no sidebar,
the address form and the legacy issue list showed a column holding « My account » alone, and an
account whose roles were cached stale saw a menu that the database did not give it.
"""

import types
import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.shopping_cart import utils
from webshop.webshop.utils import account_menu

CUSTOMER = "_wstest_menu_customer@yopmail.com"
PLAIN = "_wstest_menu_plain@yopmail.com"

PORTAL = frappe._dict(
	menu=[
		frappe._dict(title="Orders", route="/orders", enabled=1, role="Customer"),
		frappe._dict(title="Support", route="/sav", enabled=1, role=None),
		frappe._dict(title="Issues", route="/issues", enabled=0, role="Customer"),
	],
	custom_menu=[],
	hide_standard_menu=0,
)

_real_get_cached_doc = frappe.get_cached_doc
_real_get_doc = frappe.get_doc


def _cached_doc(doctype, *args, **kwargs):
	return PORTAL if doctype == "Portal Settings" else _real_get_cached_doc(doctype, *args, **kwargs)


def _doc(*args, **kwargs):
	if args and args[0] == "Portal Settings":
		return PORTAL
	return _real_get_doc(*args, **kwargs)


def portal():
	"""Portal Settings from the fixture above; every other document is the real one."""
	return _Both(
		patch.object(utils.frappe, "get_cached_doc", side_effect=_cached_doc),
		patch.object(frappe, "get_doc", side_effect=_doc),
	)


class _Both:
	def __init__(self, *patches):
		self.patches = patches

	def __enter__(self):
		for p in self.patches:
			p.start()

	def __exit__(self, *exc):
		for p in reversed(self.patches):
			p.stop()


def routes(context):
	return [row.route for row in context.get("sidebar_items") or []]


def row(route, title="x", role=None):
	return frappe._dict(title=title, route=route, enabled=1, role=role)


class TestWhatTheMenuSays(unittest.TestCase):
	"""The rows of Portal Settings keep the title and the address they were made with: the menu says what a customer reads."""

	def test_an_old_address_is_drawn_as_the_new_one_and_a_double_once(self):
		rows = [row("/sav"), row("/mes-reservations"), row("/gift_cards"), row("/my-requests"), row("/addresses")]
		with patch.object(account_menu, "support_is_offered", return_value=True), patch.object(
			account_menu, "shop_is_on", return_value=True
		), patch.object(frappe.db, "get_single_value", return_value=1):
			routes = [r.route for r in account_menu.adapt_menu(rows)]
		self.assertEqual(routes, ["/my-requests", "/my-bookings", "/gift-cards", "/my-addresses"])

	def test_every_title_is_short_enough_for_one_line(self):
		# A column of the account's menu holds about twenty characters at the size it is drawn.
		with patch.object(account_menu, "shop_is_on", return_value=True):
			titles = [t() if callable(t) else t for t, _ in account_menu.ENTRIES.values()]
		for title in titles:
			self.assertLessEqual(len(title), 14, title)
			self.assertFalse(title.lower().startswith("my "), title)

	def test_the_support_is_after_sales_in_a_shop_and_tickets_elsewhere(self):
		with patch.object(account_menu, "shop_is_on", return_value=True):
			self.assertEqual(account_menu.support_title(), "After-sales")
		with patch.object(account_menu, "shop_is_on", return_value=False):
			self.assertEqual(account_menu.support_title(), "Tickets")

	def test_an_entry_the_site_does_not_offer_is_left_out(self):
		rows = [row("/my-requests"), row("/lms/courses"), row("/gift-cards"), row("/loyalty-points"), row("/orders")]
		with patch.object(account_menu, "support_is_offered", return_value=False), patch.object(
			account_menu, "courses_are_offered", return_value=False
		), patch.dict(
			account_menu.ENTRIES,
			{
				"/gift-cards": ("Gift cards", lambda: False),
				"/loyalty-points": ("Loyalty", lambda: False),
				"/my-requests": ("Tickets", lambda: False),
				"/lms/courses": ("Trainings", lambda: False),
			},
		):
			self.assertEqual([r.route for r in account_menu.adapt_menu(rows)], ["/orders"])

	def test_courses_are_offered_when_the_site_shows_them_and_one_is_published(self):
		def offered(doctype_exists, switch, published, has_field=True):
			meta = types.SimpleNamespace(has_field=lambda field: has_field)
			with patch.object(frappe.db, "exists", side_effect=lambda dt, *a, **k: doctype_exists if dt == "DocType" else published), patch.object(
				frappe, "get_meta", return_value=meta
			), patch.object(frappe.db, "get_single_value", return_value=switch):
				return account_menu.courses_are_offered()

		self.assertTrue(offered(True, 1, True))
		self.assertFalse(offered(True, 0, True))
		self.assertFalse(offered(True, 1, False))
		self.assertFalse(offered(False, 1, True))
		# A site whose LMS has no such switch (stock LMS) follows the published courses alone.
		self.assertTrue(offered(True, 0, True, has_field=False))

	def test_the_rows_of_the_cache_are_not_touched(self):
		original = row("/sav", "Support")
		account_menu.adapt_menu([original])
		self.assertEqual((original.route, original.title), ("/sav", "Support"))


class TestTheSwitchesOfTheMenu(unittest.TestCase):
	"""Webshop Settings' gift card and loyalty switches add, rename or remove the entry, never double it."""

	def run_switch(self, rows, enabled):
		from webshop.webshop.doctype.webshop_settings.webshop_settings import WebshopSettings

		portal = types.SimpleNamespace(append=MagicMock(), save=MagicMock())
		with patch.object(frappe, "get_all", return_value=rows), patch.object(frappe.db, "delete") as delete, patch.object(
			frappe.db, "set_value"
		) as set_value, patch.object(frappe.db, "commit"), patch.object(frappe.db, "sql", return_value=[[4]]), patch.object(
			frappe, "get_doc", return_value=portal
		), patch.object(frappe.cache, "delete_key"):
			WebshopSettings.update_account_menu_entry("/gift-cards", ("/gift_cards",), "Gift cards", enabled)
		return portal, delete, set_value

	def test_an_entry_that_is_missing_is_added_with_the_english_address(self):
		portal, delete, set_value = self.run_switch([], 1)
		row = portal.append.call_args.args[1]
		self.assertEqual((row["route"], row["title"], row["idx"]), ("/gift-cards", "Gift cards", 5))
		portal.save.assert_called_once()
		delete.assert_not_called()
		set_value.assert_not_called()

	def test_the_row_of_the_old_address_is_renamed_and_not_doubled(self):
		portal, delete, set_value = self.run_switch([frappe._dict(name="r1", route="/gift_cards")], 1)
		set_value.assert_called_once_with("Portal Menu Item", "r1", {"route": "/gift-cards", "title": "Gift cards"})
		portal.append.assert_not_called()

	def test_an_entry_already_there_is_left_alone(self):
		portal, delete, set_value = self.run_switch([frappe._dict(name="r1", route="/gift-cards")], 1)
		portal.append.assert_not_called()
		set_value.assert_not_called()
		delete.assert_not_called()

	def test_switching_off_removes_every_address_of_the_entry(self):
		rows = [frappe._dict(name="r1", route="/gift_cards"), frappe._dict(name="r2", route="/gift-cards")]
		portal, delete, set_value = self.run_switch(rows, 0)
		delete.assert_called_once_with("Portal Menu Item", {"name": ("in", ["r1", "r2"])})


class TestAccountMenu(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		for email, roles in ((CUSTOMER, [{"role": "Customer"}]), (PLAIN, [])):
			if not frappe.db.exists("User", email):
				user = frappe.get_doc(
					{
						"doctype": "User",
						"email": email,
						"first_name": email.split("@")[0],
						"user_type": "Website User",
						"send_welcome_email": 0,
						"roles": roles,
					}
				)
				user.flags.skip_drive_setup = True
				user.insert(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		for email in (CUSTOMER, PLAIN):
			frappe.delete_doc("User", email, force=1, ignore_permissions=True)
		frappe.db.commit()
		super().tearDownClass()

	def setUp(self):
		self.forget_caches()

	def tearDown(self):
		frappe.set_user("Administrator")
		self.forget_caches()

	def forget_caches(self):
		for user in (CUSTOMER, PLAIN):
			frappe.cache.hdel("roles", user)
			frappe.cache.hdel("portal_menu_items", user)

	def render(self, user, **context):
		frappe.set_user(user)
		context = frappe._dict(context)
		with portal():
			utils.update_website_context(context)
		return context

	def test_the_three_links_of_me_lead_to_pages_with_the_menu(self):
		for path in ("update-profile/_wstest_menu_customer@yopmail.com", "update-password", "third_party_apps"):
			context = self.render(CUSTOMER, path=path, show_sidebar=0)
			self.assertTrue(context.show_sidebar, path)
			self.assertEqual(routes(context), ["/orders", "/my-requests"], path)

	def test_a_web_form_without_a_sidebar_of_its_own_gets_the_menu(self):
		# //// Neoffice — frappe fills a web form's sidebar_items only when it names a Website Sidebar
		for path in ("address/new", "address/ADDR-0001/edit"):
			context = self.render(CUSTOMER, path=path, show_sidebar=1, sidebar_items=None)
			self.assertTrue(context.show_sidebar, path)
			self.assertEqual(routes(context), ["/orders", "/my-requests"], path)

	def test_a_page_that_already_carries_the_menu_keeps_it(self):
		own = [frappe._dict(title="Mine", route="/mine", enabled=1)]
		context = self.render(CUSTOMER, path="orders", show_sidebar=1, sidebar_items=own)
		self.assertEqual(routes(context), ["/mine"])

	def test_the_menu_follows_the_roles(self):
		self.assertEqual(routes(self.render(PLAIN, path="me", show_sidebar=1)), ["/my-requests"])

	def test_a_visitor_is_left_alone(self):
		context = self.render("Guest", path="update-password")
		self.assertNotIn("show_sidebar", context)
		self.assertFalse(context.get("sidebar_items"))

	def test_a_page_outside_the_account_is_left_alone(self):
		context = self.render(CUSTOMER, path="all-products")
		self.assertNotIn("show_sidebar", context)
		self.assertFalse(context.get("sidebar_items"))

	def test_stale_cached_roles_are_dropped_and_the_menu_follows_the_database(self):
		# The database gives PLAIN no role. A cache that outlived a role since removed says Customer, and
		# the menu cached from it lists the Customer's pages.
		frappe.cache.hset("roles", PLAIN, ["Customer", "All", "Guest"])
		frappe.set_user(PLAIN)
		with portal():
			from frappe.website.utils import get_portal_sidebar_items

			stale = get_portal_sidebar_items()
		self.assertEqual([row.route for row in stale], ["/orders", "/sav"])

		with patch.object(account_menu.frappe, "logger") as logger:
			context = self.render(PLAIN, path="me", show_sidebar=1, sidebar_items=stale)

		self.assertEqual(routes(context), ["/my-requests"])
		self.assertNotIn("Customer", frappe.cache.hget("roles", PLAIN) or [])
		# The heal leaves a trace at a level frappe's loggers keep (they start at ERROR).
		logged = [call.args[0] for call in logger.return_value.error.call_args_list]
		self.assertTrue(any("Stale roles cache" in line for line in logged), logged)

	def cache_the_stored_roles(self, user, *automatic):
		"""What `frappe.get_roles` caches for `user`: the rows of Has Role (apps add baseline roles at
		insert, so the test asks the database instead of naming them) and the automatic roles."""
		cached = [*sorted(account_menu.stored_roles(user)), "All", "Guest", *automatic]
		frappe.cache.hset("roles", user, cached)
		return cached

	def test_roles_that_agree_with_the_database_are_left_in_the_cache(self):
		cached = self.cache_the_stored_roles(CUSTOMER)
		self.assertIn("Customer", cached)
		self.assertFalse(account_menu.heal_stale_roles(CUSTOMER))
		self.assertEqual(frappe.cache.hget("roles", CUSTOMER), cached)

	def test_a_desk_user_s_automatic_role_is_not_a_difference(self):
		self.cache_the_stored_roles(CUSTOMER, "Desk User")
		self.assertFalse(account_menu.heal_stale_roles(CUSTOMER))

	def test_nothing_cached_nothing_to_heal(self):
		self.assertFalse(account_menu.heal_stale_roles(CUSTOMER))
		self.assertFalse(account_menu.heal_stale_roles("Guest"))
		self.assertFalse(account_menu.heal_stale_roles("Administrator"))
