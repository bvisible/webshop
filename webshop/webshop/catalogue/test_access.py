# //// Neoffice — added file (no upstream equivalent).
"""Who the reseller catalogue is offered to: a customer of an allowed group, and nobody else.

Webshop Settings is replaced by an in-memory copy (a Single survives the rollback, so a test must
never write to it) and the customers are real, in a small tree of customer groups of their own.
"""

from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.catalogue import access
from webshop.webshop.tests.utils import PREFIX, portal_customer, root_customer_group

PARENT = f"{PREFIX} Cat Resellers"
CHILD = f"{PREFIX} Cat Resellers Gold"
OTHER = f"{PREFIX} Cat Consumers"

PARENT_USER, PARENT_CUSTOMER = "wstest-cat-parent@example.com", f"{PREFIX} Cat Parent Shop"
CHILD_USER, CHILD_CUSTOMER = "wstest-cat-child@example.com", f"{PREFIX} Cat Child Shop"
OTHER_USER, OTHER_CUSTOMER = "wstest-cat-other@example.com", f"{PREFIX} Cat Other Shop"
# a Website User with no Customer behind it
NOBODY = "wstest-cat-nobody@example.com"


def settings(*groups, enabled=1):
	"""An in-memory Webshop Settings: the switch, and the groups it allows."""
	return frappe._dict(
		enable_reseller_catalogue=enabled,
		reseller_catalogue_groups=[frappe._dict(allowed_customer_group=group) for group in groups],
	)


def _group(name, parent, is_group=0):
	if not frappe.db.exists("Customer Group", name):
		frappe.get_doc(
			{
				"doctype": "Customer Group",
				"customer_group_name": name,
				"is_group": is_group,
				"parent_customer_group": parent,
			}
		).insert(ignore_permissions=True)


class TestWhoIsOffered(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		_group(PARENT, root_customer_group(), is_group=1)
		_group(CHILD, PARENT)
		_group(OTHER, root_customer_group())
		for user, customer, group in (
			(PARENT_USER, PARENT_CUSTOMER, PARENT),
			(CHILD_USER, CHILD_CUSTOMER, CHILD),
			(OTHER_USER, OTHER_CUSTOMER, OTHER),
		):
			portal_customer(user, customer)
			# these customers are kept between runs: put each one back where the test expects it
			frappe.db.set_value("Customer", customer, {"customer_group": group, "disabled": 0})
		if not frappe.db.exists("User", NOBODY):
			frappe.flags.mute_emails = True
			frappe.get_doc(
				{
					"doctype": "User",
					"email": NOBODY,
					"first_name": "Nobody",
					"user_type": "Website User",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
		# the rollback at the end of the class would take uncommitted fixtures with it
		frappe.db.commit()

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_a_customer_of_an_allowed_group_is_offered_the_catalogue(self):
		self.assertTrue(access.is_offered(PARENT_USER, settings(PARENT)))

	def test_a_customer_of_a_sub_group_is_offered_it_too(self):
		# customer groups are a tree: a group allowed at the top reaches the groups under it
		self.assertTrue(access.is_offered(CHILD_USER, settings(PARENT)))

	def test_a_group_allowed_below_does_not_reach_the_group_above(self):
		self.assertFalse(access.is_offered(PARENT_USER, settings(CHILD)))

	def test_a_customer_of_another_group_is_not_offered_it(self):
		self.assertFalse(access.is_offered(OTHER_USER, settings(PARENT)))

	def test_the_switch_off_offers_it_to_nobody(self):
		self.assertFalse(access.is_offered(PARENT_USER, settings(PARENT, enabled=0)))

	def test_an_empty_list_of_groups_offers_it_to_nobody(self):
		self.assertFalse(access.is_offered(PARENT_USER, settings()))

	def test_a_disabled_customer_is_not_offered_it(self):
		frappe.db.set_value("Customer", PARENT_CUSTOMER, "disabled", 1)
		try:
			self.assertFalse(access.is_offered(PARENT_USER, settings(PARENT)))
		finally:
			frappe.db.set_value("Customer", PARENT_CUSTOMER, "disabled", 0)

	def test_a_visitor_the_administrator_and_a_user_without_customer_are_not_offered_it(self):
		for user in ("Guest", "Administrator", NOBODY, None):
			with self.subTest(user=user):
				self.assertFalse(access.is_offered(user, settings(PARENT)))

	def test_looking_for_the_customer_never_creates_one(self):
		# get_party() mints a Customer for an account that has none; a page view must never do that
		before = frappe.db.count("Customer")
		self.assertIsNone(access.customer_of(NOBODY))
		self.assertEqual(frappe.db.count("Customer"), before)

	def test_the_customer_comes_from_the_portal_link(self):
		self.assertEqual(access.customer_of(PARENT_USER), PARENT_CUSTOMER)

	def test_require_reseller_answers_the_customer_of_the_session(self):
		frappe.set_user(CHILD_USER)
		with mock.patch.object(access, "shop_settings", return_value=settings(PARENT)):
			self.assertEqual(access.require_reseller(), CHILD_CUSTOMER)

	def test_require_reseller_refuses_a_customer_who_is_not_offered_it(self):
		frappe.set_user(OTHER_USER)
		with mock.patch.object(access, "shop_settings", return_value=settings(PARENT)):
			with self.assertRaises(frappe.PermissionError):
				access.require_reseller()
