# //// Neoffice — added file (no upstream equivalent).
# //// Coupon Code.coupon_code_residual: when a gift card is only partly spent we issue
# //// a second card for the balance, and this link says which card it came from
# //// (618eedfdb8, 2025-03-24 "Feat gift card split"). ERPNext coupons are all-or-
# //// nothing, so upstream needs no such link.
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

def execute():
    """
    Add a coupon_code_residual field to the Coupon Code doctype to track the origin of split gift cards
    """
    if not frappe.db.exists("Custom Field", {"dt": "Coupon Code", "fieldname": "coupon_code_residual"}):
        create_custom_field("Coupon Code", {
            "label": "Coupon Code Residual",
            "fieldname": "coupon_code_residual",
            "fieldtype": "Link",
            "options": "Coupon Code",
            "insert_after": "used",
            "print_hide": 1,
            "translatable": 0,
            "read_only": 1,
            "description": "Original coupon code from which this gift card was created during a split operation"
        })