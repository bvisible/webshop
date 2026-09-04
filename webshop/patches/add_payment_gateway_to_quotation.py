#//// Neoffice — added file (no upstream equivalent).
#//// Quotation.payment_gateway: the cart remembers which gateway the buyer picked, so
#//// a resumed checkout re-opens the same tile instead of the shop default
#//// (3bc2d836f1, 2025-02-11).
import frappe

def execute():
    """Add a payment_gateway field to Quotation"""
    if not frappe.db.exists('Custom Field', {'dt': 'Quotation', 'fieldname': 'payment_gateway'}):
        frappe.get_doc({
            'doctype': 'Custom Field',
            'dt': 'Quotation',
            'label': 'Payment Gateway',
            'fieldname': 'payment_gateway',
            'fieldtype': 'Link',
            'options': 'Payment Gateway',
            'insert_after': 'order_type',
            'read_only': 1,
        }).insert(ignore_permissions=True)
