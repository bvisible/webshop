# //// Neoffice — added file (no upstream equivalent).
# //// Payment Request.from_checkout: a Payment Request raised by our checkout must be
# //// told apart from one a salesperson e-mailed by hand — only the first may conclude
# //// an order on its own and redirect to /thank_you (3bc2d836f1, 2025-02-11).
import frappe

def execute():
    """Add a from_checkout field to Payment Request"""
    if not frappe.db.exists('Custom Field', {'dt': 'Payment Request', 'fieldname': 'from_checkout'}):
        frappe.get_doc({
            'doctype': 'Custom Field',
            'dt': 'Payment Request',
            'label': 'From Checkout',
            'fieldname': 'from_checkout',
            'fieldtype': 'Check',
            'insert_after': 'reference_name',
            'read_only': 1,
            'translatable': 0,
            'owner': 'Administrator'
        }).insert(ignore_permissions=True)
