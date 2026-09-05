# //// Neoffice — added file (no upstream equivalent).
# //// The checkout tiles: each Payment Gateway Account gets its own title, description,
# //// logo and order, so the buyer reads "TWINT" and not "TWINT - CHF - pri". Upstream
# //// has no checkout page and no such fields (3bc2d836f1, 2025-02-11 "Add gift cards
# //// and improve shopping cart"; the section was un-collapsed by 7a1fa7d1c3).
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

def execute():
    """Add checkout display fields to Payment Gateway Account"""
    
    # List of fields to add
    fields = [
        {
            'fieldname': 'checkout_display_section',
            'label': 'Display in Checkout',
            'fieldtype': 'Section Break',
            'insert_after': 'message_examples',
            'depends_on': 'eval:frappe.db.get_single_value("Webshop Settings", "enable_checkout_page")',
            'collapsible': 0
        },
        {
            'fieldname': 'checkout_title',
            'label': 'Checkout Title',
            'fieldtype': 'Data',
            'insert_after': 'checkout_display_section',
            'translatable': 1,
            'depends_on': 'eval:frappe.db.get_single_value("Webshop Settings", "enable_checkout_page")'
        },
        {
            'fieldname': 'checkout_description',
            'label': 'Checkout Description',
            'fieldtype': 'Small Text',
            'insert_after': 'checkout_title',
            'translatable': 1,
            'depends_on': 'eval:frappe.db.get_single_value("Webshop Settings", "enable_checkout_page")'
        },
        {
            'fieldname': 'logo',
            'label': 'Logo',
            'fieldtype': 'Attach Image',
            'insert_after': 'checkout_description',
            'translatable': 0,
            'depends_on': 'eval:frappe.db.get_single_value("Webshop Settings", "enable_checkout_page")'
        }
    ]
    
    # Create each field if it doesn't exist in Payment Gateway Account
    for field in fields:
        if not frappe.get_value('Custom Field', {'dt': 'Payment Gateway Account', 'fieldname': field['fieldname']}):
            create_custom_field('Payment Gateway Account', field)
            print(f"Added field '{field['fieldname']}' to Payment Gateway Account")
        else:
            print(f"Field '{field['fieldname']}' already exists in Payment Gateway Account")
