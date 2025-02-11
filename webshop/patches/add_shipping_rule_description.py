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
