# //// Neoffice — added file (no upstream equivalent). A desk account (a System User: staff, the demo's own account) is
# //// never made a shop Customer by the cart, as Administrator already was not (neoffice-maintenance#1763): the demo
# //// grew a Customer "admin" that sat first in every customer list and in the films of the guided tours
# //// (neoffice-maintenance#2450).
# //// Neoffice — and a contact linked to a record that is no buyer (the Helpdesk mirror's HD Customer, a Company) does
# //// not make that record the cart's party (neoffice-maintenance#2562).

import frappe
from frappe.tests.roles import as_role, make_persona
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.shopping_cart import cart

STAFF = "staff-2450@yopmail.com"
STAFF_BUYER = "staff-buyer-2450@yopmail.com"
BUYER_CUSTOMER = "_Test Staff Buyer 2450"
# neoffice-maintenance#2562: accounts whose contact is linked to a record that is no buyer
STAFF_LINKED = "staff-linked-2562@yopmail.com"
SHOPPER_LINKED = "shopper-linked-2562@yopmail.com"
SHOPPER_CUSTOMER = "_Test Shopper 2562"
# neoffice-maintenance#2450: a staff account whose e-mail is on the contact of a real customer
STAFF_NAMED = "staff-named-2450@yopmail.com"
NAMING_CUSTOMER = "_Test Customer Naming Staff 2450"


def _a_leaf_customer_group():
	"""A customer group that is not a folder: a fresh site defaults to the root, a folder."""
	leaf = frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
	if leaf:
		return leaf
	root = frappe.db.get_value(
		"Customer Group", {"is_group": 1, "parent_customer_group": ("is", "not set")}, "name"
	)
	group = frappe.get_doc(
		{
			"doctype": "Customer Group",
			"customer_group_name": "_Test Leaf 2450",
			"is_group": 0,
			"parent_customer_group": root,
		}
	)
	return group.insert(ignore_permissions=True).name


class TestAStaffAccountIsNotAShopCustomer(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")
		for email in (STAFF_LINKED, SHOPPER_LINKED, STAFF_NAMED):
			for contact in frappe.get_all(
				"Contact Email", {"email_id": email, "parenttype": "Contact"}, pluck="parent"
			):
				frappe.delete_doc("Contact", contact, force=True, ignore_permissions=True)
		for user in (STAFF, STAFF_BUYER, STAFF_LINKED, SHOPPER_LINKED, STAFF_NAMED):
			for row in frappe.get_all("Portal User", {"user": user, "parenttype": "Customer"}, pluck="parent"):
				frappe.delete_doc("Customer", row, force=True, ignore_permissions=True)
			for contact in frappe.get_all("Contact", {"user": user}, pluck="name"):
				frappe.delete_doc("Contact", contact, force=True, ignore_permissions=True)
		for name in (BUYER_CUSTOMER, SHOPPER_CUSTOMER, NAMING_CUSTOMER):
			if frappe.db.exists("Customer", name):
				frappe.delete_doc("Customer", name, force=True, ignore_permissions=True)

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
		customer.update(
			{
				"customer_name": BUYER_CUSTOMER,
				"customer_type": "Individual",
				"customer_group": _a_leaf_customer_group(),
			}
		)
		customer.append("portal_users", {"user": STAFF_BUYER})
		customer.flags.ignore_mandatory = True
		customer.insert(ignore_permissions=True)
		with as_role("sales_user", email=STAFF_BUYER):
			party = cart.get_party()
			self.assertIsNotNone(party)
			self.assertEqual(party.name, customer.name)

	# ---------------------------------------------------------------- neoffice-maintenance#2562
	def _link_contact(self, email, links):
		"""The account's contact, linked to `links` in that order (Administrator prepares the scenery)."""
		names = frappe.get_all("Contact Email", {"email_id": email, "parenttype": "Contact"}, pluck="parent")
		contact = frappe.get_doc("Contact", names[0]) if names else frappe.new_doc("Contact")
		if not names:
			contact.first_name = email.split("@")[0]
			contact.append("email_ids", {"email_id": email, "is_primary": 1})
		contact.set("links", [{"link_doctype": doctype, "link_name": name} for doctype, name in links])
		contact.save(ignore_permissions=True)
		return contact.name

	def _a_record_that_is_no_buyer(self):
		# The demo's case is the Helpdesk mirror's HD Customer; a Company is a record every site has.
		company = frappe.db.get_value("Company", {}, "name")
		if not company:
			self.skipTest("a company is needed")
		return ("Company", company)

	def test_a_staff_account_linked_to_no_buyer_has_no_cart(self):
		make_persona("sales_user", STAFF_LINKED)
		self._link_contact(STAFF_LINKED, [self._a_record_that_is_no_buyer()])
		with as_role("sales_user", email=STAFF_LINKED):
			before = frappe.db.count("Customer")
			self.assertIsNone(cart.get_party())
			with self.assertRaises(frappe.ValidationError) as refused:
				cart.update_cart("NO-SUCH-ITEM-2562", 1)
			self.assertIn("staff account", str(refused.exception))
			self.assertEqual(before, frappe.db.count("Customer"))

	def test_a_shopper_s_customer_is_found_behind_a_link_that_is_no_buyer(self):
		customer = frappe.new_doc("Customer")
		customer.update(
			{
				"customer_name": SHOPPER_CUSTOMER,
				"customer_type": "Individual",
				"customer_group": _a_leaf_customer_group(),
			}
		)
		customer.flags.ignore_mandatory = True
		customer.insert(ignore_permissions=True)
		make_persona("portal_customer", SHOPPER_LINKED)
		# the record that is no buyer comes FIRST on the contact, the Customer after it; no Portal User row yet
		self._link_contact(SHOPPER_LINKED, [self._a_record_that_is_no_buyer(), ("Customer", customer.name)])
		with as_role("portal_customer", email=SHOPPER_LINKED):
			party = cart.get_party()
			self.assertIsNotNone(party)
			self.assertEqual((party.doctype, party.name), ("Customer", customer.name))

	# ---------------------------------------------------------------- neoffice-maintenance#2450, the portal rows
	def test_a_staff_account_is_not_attached_to_the_customer_its_e_mail_names(self):
		# A desk account's e-mail on a contact of a real customer (the company's generic address typed in the
		# customer's record) made get_party() add the account to that customer's Portal Users, and the account's
		# cart then ran in the customer's name. Administrator prepares the scenery: the customer and its contact.
		customer = frappe.new_doc("Customer")
		customer.update(
			{
				"customer_name": NAMING_CUSTOMER,
				"customer_type": "Company",
				"customer_group": _a_leaf_customer_group(),
			}
		)
		customer.flags.ignore_mandatory = True
		customer.insert(ignore_permissions=True)
		make_persona("sales_user", STAFF_NAMED)
		self._link_contact(STAFF_NAMED, [("Customer", customer.name)])
		with as_role("sales_user", email=STAFF_NAMED):
			before = frappe.db.count("Customer")
			self.assertIsNone(cart.get_party())
			with self.assertRaises(frappe.ValidationError) as refused:
				cart.update_cart("NO-SUCH-ITEM-2450", 1)
			self.assertIn("staff account", str(refused.exception))
			self.assertEqual(before, frappe.db.count("Customer"))
		self.assertFalse(frappe.db.exists("Portal User", {"user": STAFF_NAMED}))
