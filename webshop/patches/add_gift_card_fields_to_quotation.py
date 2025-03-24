import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

def execute():
    """
    Create custom fields for gift card tracking on Quotation doctype
    """
    
    # Custom field for storing original gift card coupon
    if not frappe.db.exists("Custom Field", {"dt": "Quotation", "fieldname": "gift_card_coupon"}):
        create_custom_field("Quotation", {
            "label": "Gift Card Coupon",
            "fieldname": "gift_card_coupon",
            "fieldtype": "Link",
            "options": "Coupon Code",
            "insert_after": "coupon_code",
            "read_only": 1,
            "translatable": 0
        })

    # Custom field for storing original gift card amount
    if not frappe.db.exists("Custom Field", {"dt": "Quotation", "fieldname": "gift_card_original_amount"}):
        create_custom_field("Quotation", {
            "label": "Gift Card Original Amount",
            "fieldname": "gift_card_original_amount",
            "fieldtype": "Currency",
            "insert_after": "gift_card_coupon",
            "read_only": 1,
            "depends_on": "eval:doc.gift_card_coupon && doc.gift_card_coupon !== ''",
            "translatable": 0
        })
