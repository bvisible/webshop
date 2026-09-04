#//// Neoffice — added file (no upstream equivalent).
#//// Payment Request.custom_idempotency_token (unique): a double click on "Pay" used
#//// to raise two Payment Requests and two charges. The token is minted by the page
#//// and the second call returns the first request (0033eef43d, 2025-07-17 "fix bug
#//// transform quotation and fix bug multi clic button").
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

def execute():
    """Add idempotency token field to Payment Request"""
    
    # Check if field already exists
    if not frappe.db.exists("Custom Field", {"dt": "Payment Request", "fieldname": "custom_idempotency_token"}):
        
        # Create custom field for idempotency token
        create_custom_field("Payment Request", {
            "fieldname": "custom_idempotency_token",
            "label": "Idempotency Token",
            "fieldtype": "Data",
            "hidden": 1,
            "no_copy": 1,
            "print_hide": 1,
            "report_hide": 1,
            "read_only": 1,
            "length": 100,
            "unique": 1,
            "description": "Unique token to prevent duplicate payment requests"
        })
        
        # Create index for better performance
        frappe.db.add_index("Payment Request", ["custom_idempotency_token"])
        
        frappe.db.commit()
        print("Added custom_idempotency_token field to Payment Request")
    else:
        print("custom_idempotency_token field already exists in Payment Request")