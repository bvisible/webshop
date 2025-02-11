import frappe

def add_gift_card_data_field(doctype, insert_after):
    """Add a gift_card_data field to the given doctype"""
    field_name = "gift_card_data"
    
    if not frappe.db.exists("Custom Field", {
        "dt": doctype,
        "fieldname": field_name
    }):
        custom_field = frappe.get_doc({
            "doctype": "Custom Field",
            "dt": doctype,
            "fieldname": field_name,
            "label": "Gift Card Data",
            "fieldtype": "JSON",
            "insert_after": insert_after,
            "owner": "Administrator"
        })
        custom_field.insert(ignore_permissions=True)
        frappe.db.commit()

def execute():
    """Add a gift_card_data field to the Quotation Item, Sales Order Item and Sales Invoice Item doctypes"""
    # Add the field to the three doctypes
    add_gift_card_data_field("Quotation Item", "additional_notes")
    add_gift_card_data_field("Sales Order Item", "page_break")
    add_gift_card_data_field("Sales Invoice Item", "page_break")
