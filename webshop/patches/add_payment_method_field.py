import frappe

def execute():
    """Ajoute le champ payment_method à la Quotation"""
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
