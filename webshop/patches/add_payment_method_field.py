#//// Neoffice — added file (no upstream equivalent).
#//// Quotation.payment_method: one gateway can carry several methods (a Wallee tile
#//// per card scheme, TWINT, invoice), so the gateway alone does not say what the
#//// buyer chose (e4603de9cf, 2025-02-19 "Improved management of payment methods").
import frappe

def execute():
    """Add payment method field to Quotation"""
    if not frappe.db.exists('Custom Field', {'dt': 'Quotation', 'fieldname': 'payment_method'}):
        frappe.get_doc({
            'doctype': 'Custom Field',
            'dt': 'Quotation',
            'label': 'Payment Method',
            'fieldname': 'payment_method',
            'fieldtype': 'Data',
            'insert_after': 'payment_schedule',
            'read_only': 1,
            'owner': 'Administrator'
        }).insert(ignore_permissions=True)
