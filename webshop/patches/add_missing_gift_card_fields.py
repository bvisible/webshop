import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field


def execute():
    """
    Create missing custom fields for gift card tracking on Quotation doctype.
    These fields are used in cart.py but were missing from the original patch.
    """

    # Custom field for storing temporary coupon code during cart checkout
    if not frappe.db.exists("Custom Field", {"dt": "Quotation", "fieldname": "temp_coupon_code"}):
        create_custom_field("Quotation", {
            "label": "Temp Coupon Code",
            "fieldname": "temp_coupon_code",
            "fieldtype": "Data",
            "insert_after": "gift_card_original_amount",
            "read_only": 1,
            "hidden": 1,
            "translatable": 0
        })
        frappe.db.commit()

    # Custom field for flagging if gift card needs to be split
    if not frappe.db.exists("Custom Field", {"dt": "Quotation", "fieldname": "gift_card_to_split"}):
        create_custom_field("Quotation", {
            "label": "Gift Card To Split",
            "fieldname": "gift_card_to_split",
            "fieldtype": "Check",
            "insert_after": "temp_coupon_code",
            "read_only": 1,
            "hidden": 1,
            "translatable": 0
        })
        frappe.db.commit()
