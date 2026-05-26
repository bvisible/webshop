import frappe

def execute():
    """Add birthday field to Contact"""
    if not frappe.db.exists('Custom Field', {'dt': 'Contact', 'fieldname': 'birthday'}):
        frappe.get_doc({
            'doctype': 'Custom Field',
            'dt': 'Contact',
            'label': "Birthday",
            'fieldname': 'birthday',
            'fieldtype': 'Date',
            'insert_after': 'full_name',
            'translatable': 0,
            'unique': 0,
            'in_list_view': 0,
            'in_standard_filter': 0,
            'reqd': 0
        }).insert(ignore_permissions=True)
