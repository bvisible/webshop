# //// Neoffice — added file (no upstream equivalent).
# //// Quotation.guest_session_id: upstream requires an account before a cart exists.
# //// Our shops let a visitor fill a cart and sign in at checkout, so the draft
# //// quotation is keyed on the browser session until then (3bc2d836f1, 2025-02-11).
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
