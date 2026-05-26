import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

def execute():
    # Créer le champ personnalisé
    custom_field = {
        "Sales Taxes and Charges": [
            {
                "fieldname": "is_webshopsi_fee",
                "label": "Est un frais WebshopSI ?",
                "fieldtype": "Check",
                "insert_after": "included_in_paid_amount",
                "read_only": 1,
                "print_hide": 1
            }
        ]
    }

    for doctype, fields in custom_field.items():
        for field in fields:
            create_custom_field(doctype, field)
