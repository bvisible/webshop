# //// Neoffice — added file (purchase follow-ups, no upstream equivalent).
# //// How long a unit lasts a customer; the replenishment email of a
# //// follow-up goes out at 80% of it (utils/follow_ups.py step_date).

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Item": [
				{
					"fieldname": "replenishment_days",
					"fieldtype": "Int",
					"label": "Replenishment Cycle (days)",
					"description": "How long one unit lasts a customer. A follow-up step set to the item's cycle mails at 80% of it.",
					"insert_after": "max_discount",
				}
			]
		},
		update=True,
	)
	frappe.clear_cache(doctype="Item")
