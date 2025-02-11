import frappe

def execute():
    """Add guest_session_id field to Quotation DocType"""
    if not frappe.db.exists("Custom Field", {"dt": "Quotation", "fieldname": "guest_session_id"}):
        frappe.get_doc({
            "doctype": "Custom Field",
            "dt": "Quotation",
            "label": "Guest Session ID",
            "fieldname": "guest_session_id",
            "fieldtype": "Data",
            "insert_after": "order_type",
            "description": "Unique identifier for guest sessions",
            "hidden": 1
        }).insert()
