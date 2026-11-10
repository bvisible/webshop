# //// Neoffice — added file (no upstream equivalent). A desk account (a System User: staff, the demo's own account) is
# //// never made a shop Customer by the cart, as Administrator already was not (neoffice-maintenance#1763): the demo
# //// grew a Customer "admin" that sat first in every customer list and in the films of the guided tours
# //// (neoffice-maintenance#2450).

import frappe
from frappe.tests.roles import as_role, make_persona
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.shopping_cart import cart

STAFF = "staff-2450@yopmail.com"
STAFF_BUYER = "staff-buyer-2450@yopmail.com"
BUYER_CUSTOMER = "_Test Staff Buyer 2450"


class TestAStaffAccountIsNotAShopCustomer(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")
		for user in (STAFF, STAFF_BUYER):
			for row in frappe.get_all("Portal User", {"user": user, "parenttype": "Customer"}, pluck="parent"):
				frappe.delete_doc("Customer", row, force=True, ignore_permissions=True)
			for contact in frappe.get_all("Contact", {"user": user}, pluck="name"):
				frappe.delete_doc("Contact", contact, force=True, ignore_permissions=True)
		if frappe.db.exists("Customer", BUYER_CUSTOMER):
			frappe.delete_doc("Customer", BUYER_CUSTOMER, force=True, ignore_permissions=True)

	def test_browsing_the_shop_makes_no_customer_for_a_staff_account(self):
		with as_role("sales_user", email=STAFF) as staff:
			self.assertEqual(frappe.db.get_value("User", staff, "user_type"), "System User")
			before = frappe.db.count("Customer")
			self.assertIsNone(cart.get_party())
			self.assertEqual(before, frappe.db.count("Customer"))
			self.assertFalse(frappe.db.exists("Portal User", {"user": staff}))
			self.assertNotIn("Customer", frappe.get_roles(staff))

	def test_a_staff_account_adding_to_the_cart_is_refused_with_a_reason(self):
		with as_role("sales_user", email=STAFF):
			before = frappe.db.count("Customer")
			# refused before any item is looked up: the item code does not need to exist
			with self.assertRaises(frappe.ValidationError) as refused:
				cart.update_cart("NO-SUCH-ITEM-2450", 1)
			self.assertIn("staff account", str(refused.exception))
			self.assertEqual(before, frappe.db.count("Customer"))

	def test_a_staff_account_linked_to_a_customer_by_hand_still_shops_as_it(self):
		# Administrator prepares the scenery: a staff member who also buys, linked to their Customer by hand
		make_persona("sales_user", STAFF_BUYER)
		customer = frappe.new_doc("Customer")
		customer.update({"customer_name": BUYER_CUSTOMER, "customer_type": "Individual"})
		customer.append("portal_users", {"user": STAFF_BUYER})
		customer.flags.ignore_mandatory = True
		customer.insert(ignore_permissions=True)
		with as_role("sales_user", email=STAFF_BUYER):
			party = cart.get_party()
			self.assertIsNotNone(party)
			self.assertEqual(party.name, customer.name)
