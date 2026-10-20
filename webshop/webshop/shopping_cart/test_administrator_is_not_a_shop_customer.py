# //// Neoffice — added file (no upstream equivalent). Administrator is the built-in superuser, never a
# //// shopper: get_party() must never create or return a Customer for it, or every instance grows a
# //// "Administrator" customer and a Portal User row to match (neoffice-maintenance#1763).

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.shopping_cart import cart


class TestAdministratorIsNotAShopCustomer(FrappeTestCase):
    def tearDown(self):
        frappe.set_user("Administrator")

    def test_get_party_returns_none_for_administrator(self):
        frappe.set_user("Administrator")
        before = frappe.db.count("Customer", {"name": "Administrator"})
        # the gate sits before every lookup and the create-customer branch
        self.assertIsNone(cart.get_party())
        after = frappe.db.count("Customer", {"name": "Administrator"})
        # no "Administrator" customer is minted by the call
        self.assertEqual(before, after)
