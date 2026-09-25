# //// Neoffice — added file (no upstream equivalent): the User field of an account opened before
# //// its address is confirmed (webshop/webshop/auth/confirmation.py). neoffice-maintenance#691,
# //// decision D-9, 2026-09-25.

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"User": [
				{
					"fieldname": "email_confirmation_pending",
					"fieldtype": "Check",
					"label": "Email address not confirmed yet",
					"description": "Opened in the shop and signed in at once; the link of the welcome email confirms the address.",
					"read_only": 1,
					"depends_on": "email_confirmation_pending",
					"insert_after": "enabled",
				}
			]
		},
		update=True,
	)
	frappe.clear_cache(doctype="User")
	# A new field of a Single reads 0 on a site that stored no value for it, whatever its default:
	# the switch is on for every shop, as its default says, unless a merchant already set it.
	stored = frappe.db.sql(
		"select value from `tabSingles` where doctype = 'Webshop Settings' and field = 'open_account_at_once'"
	)
	if not stored:
		frappe.db.set_single_value("Webshop Settings", "open_account_at_once", 1)
