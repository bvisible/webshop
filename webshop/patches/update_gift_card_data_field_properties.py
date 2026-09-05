# //// Neoffice — added file (no upstream equivalent).
# //// Makes the gift_card_data Custom Fields hidden and read-only on the three item
# //// tables: they hold machine data (recipient, message, generated codes) that a
# //// seller was able to edit in the desk (437c6d54d7, 2025-12-04).
import frappe

def execute():
    """Update gift_card_data Custom Fields to be hidden and read_only"""
    doctypes = ["Quotation Item", "Sales Order Item", "Sales Invoice Item"]

    for doctype in doctypes:
        field_name = f"{doctype}-gift_card_data"

        if frappe.db.exists("Custom Field", field_name):
            frappe.db.set_value("Custom Field", field_name, {
                "hidden": 1,
                "read_only": 1
            })

    frappe.db.commit()
    frappe.clear_cache()
