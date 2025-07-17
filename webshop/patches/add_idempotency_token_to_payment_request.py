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