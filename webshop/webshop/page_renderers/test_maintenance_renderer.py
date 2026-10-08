# //// Neoffice — added file (no upstream equivalent): who passes the maintenance veil
# //// (page_renderers/maintenance_renderer.py). neoffice-maintenance#1325, 2026-10-08.
"""Who the maintenance veil lets through while the public website is closed.

Frappe hands a page renderer the ENDPOINT of the route rule that matched, not the address that was
asked for: /drive reaches it as "suite", /builder as "_builder", /lms as "_lms". The veil's fixed list
of desk paths never matched those names, so a signed-in member of staff was shown the maintenance page
on every app but the desk. Apps are now named by their route rule, read from the hooks.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from werkzeug.routing import Rule
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from webshop.webshop.page_renderers.maintenance_renderer import MaintenancePageRenderer

# The rules of an instance of the fleet (2026-10-08), reduced to the shapes that matter: a single-page
# app is `/<name>/<path:app_path>` (its root, when it has one, shares the endpoint), the shop's own pages
# carry other variables.
RULES = [
	{"from_route": "/app/<path:app_path>", "to_route": "app"},
	{"from_route": "/hrms/<path:app_path>", "to_route": "hrms"},
	{"from_route": "/hr/<path:app_path>", "to_route": "roster"},
	{"from_route": "/builder/<path:app_path>", "to_route": "_builder"},
	{"from_route": "/builder", "to_route": "_builder"},
	{"from_route": "/lms/<path:app_path>", "to_route": "_lms"},
	{"from_route": "/lms", "to_route": "_lms"},
	{"from_route": "/helpdesk/<path:app_path>", "to_route": "helpdesk"},
	{"from_route": "/drive", "to_route": "suite"},
	{"from_route": "/drive/<path:app_path>", "to_route": "suite"},
	{"from_route": "/writer", "to_route": "suite"},
	{"from_route": "/writer/<path:app_path>", "to_route": "suite"},
	{"from_route": "/orders/<path:name>", "to_route": "order", "defaults": {"doctype": "Sales Order"}},
	{"from_route": "/jobs/<path:job_route>", "to_route": "careers/opening"},
	{"from_route": "/brands/<brand_slug>", "to_route": "brand"},
	{"from_route": "/wopi/files/<file_id>", "to_route": "wopi_handler"},
]
APPS = ("app", "hrms", "roster", "_builder", "_lms", "helpdesk", "suite")
SHOP_PAGES = ("order", "careers/opening", "brand", "all-products", "products/some-item")
STAFF = "staff@example.com"


class VeilCase(FrappeTestCase):
	def blocked(self, endpoint, user, rules=None, roles=("Employee",), **switches):
		"""Whether the veil blocks a request whose resolved endpoint is `endpoint`, made by `user`."""
		values = {
			"maintenance_website": 1,
			"maintenance_webshop": 0,
			"allow_system_users_during_maintenance": 0,
			"redirect_to_login": 0,
			**switches,
		}
		read_single_value, read_hooks = frappe.db.get_single_value, frappe.get_hooks

		def single_value(doctype, field=None, *args, **kwargs):
			if doctype == "Webshop Settings" and field in values:
				return values[field]
			return read_single_value(doctype, field, *args, **kwargs)

		def hooks(name=None, *args, **kwargs):
			if name == "website_route_rules":
				return list(RULES if rules is None else rules)
			return read_hooks(name, *args, **kwargs)

		self.addCleanup(frappe.set_user, frappe.session.user)
		frappe.set_user(user)
		with (
			patch("frappe.db.get_single_value", side_effect=single_value),
			patch("frappe.get_hooks", side_effect=hooks),
			patch("frappe.get_roles", return_value=list(roles)),
		):
			return MaintenancePageRenderer(path=endpoint).can_render()


class TestWhoPassesTheVeil(VeilCase):
	def test_signed_in_staff_reach_every_app_mounted_through_a_route_rule(self):
		for endpoint in APPS:
			with self.subTest(endpoint=endpoint):
				self.assertFalse(self.blocked(endpoint, STAFF), f"{endpoint} is behind the veil for signed-in staff")

	def test_a_visitor_stays_behind_the_veil_everywhere(self):
		for endpoint in (*APPS, *SHOP_PAGES):
			with self.subTest(endpoint=endpoint):
				self.assertTrue(self.blocked(endpoint, "Guest"))

	def test_the_shops_own_pages_stay_behind_the_veil_for_a_signed_in_customer(self):
		# a route rule that names another variable than app_path is a page of the shop, not an app
		for endpoint in SHOP_PAGES:
			with self.subTest(endpoint=endpoint):
				self.assertTrue(self.blocked(endpoint, STAFF))

	def test_an_app_installed_tomorrow_passes_without_touching_the_renderer(self):
		tomorrow = [*RULES, {"from_route": "/newapp/<path:app_path>", "to_route": "newapp"}]
		self.assertTrue(self.blocked("newapp", STAFF), "unknown to the rules: still behind the veil")
		self.assertFalse(self.blocked("newapp", STAFF, rules=tomorrow))
		self.assertTrue(self.blocked("newapp", "Guest", rules=tomorrow))

	def test_a_rule_that_is_not_a_well_formed_dict_is_ignored(self):
		odd = [None, "/x", {"from_route": None, "to_route": "suite"}, {"from_route": "/x/<path:app_path>"}]
		self.assertTrue(self.blocked("suite", STAFF, rules=odd))

	def test_the_managers_bypass_is_unchanged(self):
		# with the staff switch on, a manager reaches the website too; another member of staff does not
		self.assertFalse(
			self.blocked("brand", "boss@example.com", roles=("System Manager",), allow_system_users_during_maintenance=1)
		)
		self.assertTrue(
			self.blocked("brand", STAFF, roles=("Employee",), allow_system_users_during_maintenance=1)
		)

	def test_nothing_is_blocked_when_the_shop_is_open(self):
		for endpoint in ("brand", "suite", "all-products"):
			self.assertFalse(self.blocked(endpoint, "Guest", maintenance_website=0, maintenance_webshop=0))

	def test_closing_only_the_webshop_still_leaves_the_apps_and_the_site_alone(self):
		only_shop = {"maintenance_website": 0, "maintenance_webshop": 1}
		self.assertFalse(self.blocked("suite", "Guest", **only_shop))
		self.assertTrue(self.blocked("all-products", "Guest", **only_shop))

	def test_login_assets_and_the_desk_API_are_still_let_through(self):
		for endpoint in ("login", "assets/frappe/js/x.js", "files/a.png", "printview"):
			self.assertFalse(self.blocked(endpoint, "Guest"), endpoint)
		self.assertFalse(self.blocked("api/method/ping", STAFF))


class TestFrappeHandsTheRendererTheEndpoint(VeilCase):
	"""The premise of the fix: the address asked for is turned into the rule's endpoint BEFORE any page
	renderer sees it (frappe.website.path_resolver builds each renderer from the endpoint)."""

	def endpoint_of(self, address):
		rules = [Rule(r["from_route"], endpoint=r["to_route"]) for r in RULES]
		from frappe.website.router import evaluate_dynamic_routes

		request = Request(EnvironBuilder(path="/" + address).get_environ())
		# the rule's variables are written to form_dict: keep the test's request apart
		with (
			patch.object(frappe.local, "request", request, create=True),
			patch.object(frappe.local, "form_dict", frappe._dict()),
			patch.object(frappe.local, "no_cache", 0, create=True),
		):
			return evaluate_dynamic_routes(rules, address)

	def test_the_address_becomes_the_endpoint_of_its_rule(self):
		self.assertEqual(self.endpoint_of("drive"), "suite")
		self.assertEqual(self.endpoint_of("drive/f/abc123"), "suite")
		self.assertEqual(self.endpoint_of("writer/doc"), "suite")
		self.assertEqual(self.endpoint_of("builder"), "_builder")
		self.assertEqual(self.endpoint_of("lms/courses"), "_lms")
		self.assertEqual(self.endpoint_of("hr/roster"), "roster")

	def test_the_veil_lets_a_signed_in_user_through_for_those_addresses(self):
		for address in ("drive", "drive/f/abc123", "builder", "lms/courses", "hr/roster"):
			with self.subTest(address=address):
				endpoint = self.endpoint_of(address)
				self.assertFalse(self.blocked(endpoint, STAFF))
