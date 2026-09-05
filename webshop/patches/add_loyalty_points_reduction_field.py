# //// Neoffice — added file (no upstream equivalent).
# //// Sales Taxes and Charges.is_loyalty_points_reduction: points spent are booked as a
# //// negative charge line, and this flag is what lets the cart, the summary and the
# //// invoice tell that line apart from a real tax (3bc2d836f1, 2025-02-11).
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

def execute():
	custom_field = {
		"Sales Taxes and Charges": [
			{
				"fieldname": "is_loyalty_points_reduction",
				"label": "Is a reduction in loyalty points ?",
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
