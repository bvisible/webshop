# //// Neoffice — added file (no upstream equivalent): erpnext 15.124 refuses a Payment Entry whose Mode of Payment is
# //// disabled; the shop took the first mode wired to the gateway's account, disabled or not.
import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.controllers.payment_handler import enabled_mode_of_payment

DISABLED = "_Test WS Mode Disabled"
ENABLED = "_Test WS Mode Enabled"


def make_mode(name, enabled, account, company):
    if frappe.db.exists("Mode of Payment", name):
        frappe.delete_doc("Mode of Payment", name, force=True, ignore_permissions=True)
    frappe.get_doc(
        {
            "doctype": "Mode of Payment",
            "mode_of_payment": name,
            "enabled": enabled,
            "type": "Bank",
            "accounts": [{"company": company, "default_account": account}],
        }
    ).insert(ignore_permissions=True)
    # an app of the bench may switch a new mode off on insert: the state asked for is written as it is
    frappe.db.set_value("Mode of Payment", name, "enabled", enabled)


class TestTheShopBooksOnAnEnabledMode(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # an account and a company a Mode of Payment of this site already uses: the pair is valid whatever the chart
        pair = frappe.db.sql(
            "select default_account, company from `tabMode of Payment Account` where ifnull(default_account, '') != '' limit 1"
        )
        if not pair:
            cls.skipTest(cls, "no Mode of Payment account on this site")
        cls.account, cls.company = pair[0]
        cls.addClassCleanup(cls.clean)

    @classmethod
    def clean(cls):
        for name in (DISABLED, ENABLED):
            if frappe.db.exists("Mode of Payment", name):
                frappe.delete_doc("Mode of Payment", name, force=True, ignore_permissions=True)

    def test_a_disabled_mode_wired_to_the_account_is_not_taken(self):
        make_mode(DISABLED, 0, self.account, self.company)
        make_mode(ENABLED, 1, self.account, self.company)
        taken = enabled_mode_of_payment(self.account, self.company)
        self.assertNotEqual(taken, DISABLED)
        self.assertEqual(frappe.db.get_value("Mode of Payment", taken, "enabled"), 1)

    def test_with_only_disabled_modes_none_is_chosen(self):
        make_mode(DISABLED, 0, self.account, self.company)
        taken = enabled_mode_of_payment(self.account, self.company)
        self.assertNotEqual(taken, DISABLED)
        if taken:  # another, enabled mode of the site is wired to the same account
            self.assertEqual(frappe.db.get_value("Mode of Payment", taken, "enabled"), 1)
