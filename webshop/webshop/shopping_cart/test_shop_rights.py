# //// Neoffice — added file (no upstream equivalent). The guard of #277, proven both ways.
"""A portal customer's cart survives ERPNext checking Item read on the session user.

Upstream ERPNext version-15 (41effcf754) runs `item.check_permission()` inside
get_item_details, and get_party_account checks the receivable Account -- both on the
SESSION user, both inside the quotation's validate. A portal customer (Website User,
role Customer) reads neither, and must not: Item read for Customer would expose the
purchase and valuation fields through frappe.client.get_list.

The CI runs on stock ERPNext, where the check is real. The fleet's fork does not carry
it yet, so this test puts the same line in place explicitly and runs the cart against
it. Both directions: guard on, the customer's cart saves and stays theirs; guard off,
the same call is refused -- which is what proves the check sits on the cart's path.
"""

import contextlib
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

import webshop.webshop.shopping_cart.cart as cart
from webshop.webshop.doctype.website_item.website_item import make_website_item
from webshop.webshop.shopping_cart import guest_cart
from webshop.webshop.tests.utils import (
	PREFIX,
	ensure_shop_settings,
	leaf_customer_group,
	make_test_item,
	portal_customer,
	restore_webshop_settings,
	selling_price_list,
	snapshot_webshop_settings,
)

USER = "wstest-shop-rights@example.com"
CUSTOMER = f"{PREFIX} Shop Rights"
ITEM = f"{PREFIX} SR Item"
VISITOR = f"{PREFIX} SR Visitor"


def _customer(name):
	"""A bare Customer, the way portal_customer builds one, without a user."""
	if not frappe.db.exists("Customer", name):
		frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": name,
				"customer_group": leaf_customer_group(),
				"territory": frappe.db.get_value("Territory", {"lft": 1}, "name"),
				"default_currency": frappe.db.get_single_value("Global Defaults", "default_currency")
				or frappe.db.get_value("Company", {}, "default_currency"),
			}
		).insert(ignore_permissions=True)
	return name


@contextlib.contextmanager
def upstream_check():
	"""get_item_details as upstream ERPNext version-15 has it: the Item is read by the
	session user before anything is priced. On stock ERPNext this doubles a check that
	is already there; on the fleet's fork it puts it in place."""
	import erpnext.controllers.accounts_controller as accounts_controller

	original = accounts_controller.get_item_details

	def checked(args, *a, **kw):
		code = (frappe.parse_json(args) if isinstance(args, str) else args or {}).get("item_code")
		if code:
			frappe.get_cached_doc("Item", code).check_permission()
		return original(args, *a, **kw)

	with patch.object(accounts_controller, "get_item_details", checked):
		yield


class TestShopRights(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.settings_written = ensure_shop_settings()
		cls.purge()
		make_website_item(make_test_item(ITEM, is_stock_item=0))
		website_item = frappe.get_doc("Website Item", {"item_code": ITEM})
		website_item.published = 1
		website_item.save(ignore_permissions=True)
		price_list = selling_price_list()
		if not frappe.db.exists("Item Price", {"item_code": ITEM, "price_list": price_list}):
			frappe.get_doc(
				{"doctype": "Item Price", "item_code": ITEM, "price_list": price_list, "price_list_rate": 25}
			).insert(ignore_permissions=True)
		portal_customer(USER, CUSTOMER)
		# the visitor's cart needs a guest customer; a fresh site (CI) has none
		cls.settings_before = snapshot_webshop_settings(["guest_customer"])
		cls.guest_customer = cls.settings_before["guest_customer"]
		if not cls.guest_customer:
			cls.guest_customer = _customer(VISITOR)
			frappe.db.set_single_value("Webshop Settings", "guest_customer", cls.guest_customer)
			frappe.local.shopping_cart_settings = None
			frappe.clear_cache()
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		cls.purge()
		if not cls.settings_before.get("guest_customer"):
			restore_webshop_settings(cls.settings_before)
			if frappe.db.exists("Customer", VISITOR):
				frappe.delete_doc("Customer", VISITOR, force=True, ignore_permissions=True)
		if cls.settings_written:
			restore_webshop_settings(cls.settings_written)
		frappe.db.commit()
		super().tearDownClass()

	@classmethod
	def purge(cls):
		"""Only what this class creates: the carts, the item, then the customer and its user."""
		frappe.set_user("Administrator")
		for name in frappe.get_all("Quotation", filters={"party_name": CUSTOMER, "docstatus": 0}, pluck="name"):
			frappe.delete_doc("Quotation", name, force=True, ignore_permissions=True)
		frappe.db.delete("Item Price", {"item_code": ITEM})
		for name in frappe.get_all("Website Item", filters={"item_code": ITEM}, pluck="name"):
			frappe.delete_doc("Website Item", name, force=True, ignore_permissions=True)
		if frappe.db.exists("Item", ITEM):
			frappe.delete_doc("Item", ITEM, force=True, ignore_permissions=True)
		# this customer never orders, so it can go -- Customer.on_trash takes its contact
		if frappe.db.exists("Customer", CUSTOMER):
			frappe.delete_doc("Customer", CUSTOMER, force=True, ignore_permissions=True)
		for name in frappe.get_all("Contact", filters={"email_id": USER}, pluck="name"):
			frappe.delete_doc("Contact", name, force=True, ignore_permissions=True)
		if frappe.db.exists("User", USER):
			frappe.delete_doc("User", USER, force=True, ignore_permissions=True)
		frappe.db.commit()

	def setUp(self):
		frappe.set_user("Administrator")
		for name in frappe.get_all("Quotation", filters={"party_name": CUSTOMER, "docstatus": 0}, pluck="name"):
			frappe.delete_doc("Quotation", name, force=True, ignore_permissions=True)
		frappe.db.commit()
		# set_cart_count writes a cookie; there is no request here
		self.had_cookie_manager = hasattr(frappe.local, "cookie_manager")
		if not self.had_cookie_manager:
			frappe.local.cookie_manager = MagicMock()
		frappe.local.website_profile_doc = None

	def tearDown(self):
		frappe.set_user("Administrator")
		if not self.had_cookie_manager:
			del frappe.local.cookie_manager
		if hasattr(frappe.local, "request") and getattr(frappe.local.request, "_shop_rights_test", False):
			del frappe.local.request
		frappe.local.website_profile_doc = None

	def customer_cart(self):
		return frappe.get_all(
			"Quotation",
			filters={"party_name": CUSTOMER, "docstatus": 0},
			fields=["name", "owner", "modified_by", "grand_total"],
		)

	# --- the guard -----------------------------------------------------------------

	def test_a_customer_saves_their_own_cart_when_erpnext_checks_item_read(self):
		frappe.set_user(USER)
		with upstream_check():
			cart.update_cart(ITEM, 1)
			cart._get_cart_quotation()  # every cart read prices the rows again
			cart.update_cart(ITEM, 2)  # and a second write, on a cart that now exists
		carts = self.customer_cart()
		self.assertEqual(len(carts), 1, carts)
		self.assertEqual(carts[0].owner, USER, "the cart must stay the customer's")
		self.assertEqual(carts[0].modified_by, USER, "the audit trail must keep saying who acted")
		self.assertGreater(carts[0].grand_total, 0, "the shop priced the line")
		self.assertEqual(frappe.session.user, USER, "the session must come back as the customer")

	def test_without_the_guard_the_same_call_is_refused(self):
		"""The witness: the check really sits on the cart's path. Take the guard away and
		the customer is refused -- otherwise the test above could pass for the wrong reason."""
		frappe.set_user(USER)
		plain_save = lambda doc, submit=False, **kw: doc.submit() if submit else doc.save(**kw)  # noqa: E731
		with (
			upstream_check(),
			patch.object(cart, "shop_rights", contextlib.nullcontext),
			patch.object(cart, "save_as_shop", plain_save),
		):
			with self.assertRaises(frappe.PermissionError):
				cart.update_cart(ITEM, 1)
		self.assertEqual(frappe.session.user, USER)

	def test_the_session_comes_back_even_when_pricing_fails(self):
		frappe.set_user(USER)

		def boom(*a, **kw):
			raise frappe.ValidationError("pricing failed on purpose")

		with patch("erpnext.controllers.accounts_controller.get_item_details", boom):
			with self.assertRaises(frappe.ValidationError):
				cart.update_cart(ITEM, 1)
		self.assertEqual(frappe.session.user, USER, "a failure inside the guard must not leave Administrator on")

	def test_a_visitor_s_cart_is_priced_the_same_way(self):
		"""guest_cart.create_guest_quotation runs as Guest, who reads no Item either."""
		frappe.set_user("Guest")
		frappe.local.request = frappe._dict(cookies={}, _shop_rights_test=True)
		with upstream_check():
			result = guest_cart.create_guest_quotation([{"item_code": ITEM, "qty": 1}])
		name = (result or {}).get("quotation_id") or (result or {}).get("name")
		self.assertTrue(name, result)
		self.addCleanup(lambda: frappe.delete_doc("Quotation", name, force=True, ignore_permissions=True))
		doc = frappe.db.get_value("Quotation", name, ["owner", "party_name", "grand_total"], as_dict=True)
		self.assertEqual(doc.owner, "Guest", "the visitor's cart is the visitor's, as upstream leaves it")
		self.assertEqual(doc.party_name, self.guest_customer)
		self.assertGreater(doc.grand_total, 0)
		self.assertEqual(frappe.session.user, "Guest")


class TestShopRightsKeepsTheSession(FrappeTestCase):
	"""The block runs as Administrator and hands back the SAME session, not a rewritten one.

	set_user(user) on the way out rewrote local.session in place — sid became the
	e-mail, data became {} — and, since set_cart_count runs this block on login,
	the sid cookie the browser received named no session: customers were signed
	out by signing in (2026-09-09).
	"""

	def test_sid_data_and_form_dict_survive_the_block(self):
		from webshop.webshop.shopping_cart.shop_rights import shop_rights

		saved = frappe.local.session
		saved_form = frappe.local.form_dict
		try:
			data = frappe._dict(csrf_token="tok", device="mobile", session_expiry="720:00:00")
			frappe.local.session = frappe._dict(user="portal-customer@yopmail.com", sid="a1b2c3d4e5f6", data=data)
			frappe.local.form_dict = frappe._dict(cmd="login", device="mobile")
			with shop_rights():
				self.assertEqual(frappe.session.user, "Administrator")
			self.assertEqual(frappe.session.user, "portal-customer@yopmail.com")
			self.assertEqual(frappe.session.sid, "a1b2c3d4e5f6")
			self.assertIs(frappe.session.data, data)
			self.assertEqual(frappe.session.data.device, "mobile")
			self.assertEqual(frappe.local.form_dict.cmd, "login")
		finally:
			frappe.local.session = saved
			frappe.local.form_dict = saved_form

	def test_administrator_passes_through_untouched(self):
		from webshop.webshop.shopping_cart.shop_rights import shop_rights

		saved = frappe.local.session
		try:
			frappe.local.session = frappe._dict(user="Administrator", sid="adminsid", data=frappe._dict(x=1))
			with shop_rights():
				pass
			self.assertEqual((frappe.session.sid, frappe.session.data.x), ("adminsid", 1))
		finally:
			frappe.local.session = saved
