#//// Neoffice — added file (no upstream equivalent).
#//// Coupon Code.sales_invoice: a gift card SOLD by the shop is created from an
#//// invoice, and this link is how the shop finds which sale issued which card
#//// (3bc2d836f1, 2025-02-11).
import frappe

def execute():
    """Add a link to Sales Invoice in Coupon Code"""
    
    # Check if the field already exists
    if not frappe.db.exists('Custom Field', {'dt': 'Coupon Code', 'fieldname': 'sales_invoice'}):
        # Create the custom field
        custom_field = frappe.get_doc({
            'doctype': 'Custom Field',
            'dt': 'Coupon Code',
            'label': 'Sales Invoice',
            'fieldname': 'sales_invoice',
            'fieldtype': 'Link',
            'options': 'Sales Invoice',
            'insert_after': 'customer',
            'read_only': 1,
            'allow_on_submit': 0,
            'translatable': 0
        })
        
        custom_field.insert(ignore_permissions=True)
        
        frappe.db.commit()
