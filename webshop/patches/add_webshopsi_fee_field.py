#//// Neoffice — added file (no upstream equivalent).
#//// Sales Taxes and Charges.is_webshopsi_fee: paying by instalments adds a fee line
#//// that the cart must be able to recognise, drop and re-add when the plan changes
#//// (662c26b650, 2026-05-26 "fold webshopsi_integration (Facture method) into
#//// webshop"). Label is French because it is what the accountant reads in the desk.
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
