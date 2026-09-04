#//// Neoffice — added file (no upstream equivalent).
#//// Shipping Rule.description (translatable): the checkout shows the buyer what each
#//// shipping option means; upstream only ever renders the rule's name (3bc2d836f1,
#//// 2025-02-11).
import frappe

def execute():
    """Add a description field to Shipping Rules"""
    if not frappe.db.exists('Custom Field', {'dt': 'Shipping Rule', 'fieldname': 'description'}):
        frappe.get_doc({
            'doctype': 'Custom Field',
            'dt': 'Shipping Rule',
            'label': 'Description',
            'fieldname': 'description',
            'fieldtype': 'Small Text',
            'insert_after': 'label',
            'translatable': 1,
        }).insert(ignore_permissions=True)
