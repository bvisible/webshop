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
