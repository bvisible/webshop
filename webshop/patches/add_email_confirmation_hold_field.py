# //// Neoffice — added file (no upstream equivalent): the Sales Order field of an order held until
# //// its account's address is confirmed (webshop/webshop/auth/confirmation.py).
# //// neoffice-maintenance#691, decision D-9, 2026-09-26.

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Sales Order": [
				{
					"fieldname": "awaiting_email_confirmation",
					"fieldtype": "Check",
					"label": "On hold until the customer confirms their email address",
					"description": "Paid on account from an account opened in the shop whose address is not confirmed yet. The confirmation releases the order; resuming it by hand works too.",
					"read_only": 1,
					"no_copy": 1,
					"print_hide": 1,
					"allow_on_submit": 1,
					"depends_on": "awaiting_email_confirmation",
					"insert_after": "status",
				}
			]
		},
		update=True,
	)
	frappe.clear_cache(doctype="Sales Order")
