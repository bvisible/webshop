# //// Neoffice — added file (no upstream equivalent).
"""The shop's promises, overridable per site.

Website Profile belongs to neoffice_theme; the shop adds its own fields to it, as it
reads the profile's price list and guest customer already. Empty on the profile
means "the Webshop Settings value". Nothing to do on a site without profiles.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

PROMISE_FIELDS = [
	{
		"fieldname": "promise_section",
		"fieldtype": "Section Break",
		"label": "Shopping Promises (this site)",
		"insert_after": "sales_partner",
		"collapsible": 1,
		"description": "Leave a field empty to keep the Webshop Settings value.",
	},
	{
		"fieldname": "free_shipping_from",
		"fieldtype": "Currency",
		"label": "Free Shipping From",
		"insert_after": "promise_section",
	},
	{
		"fieldname": "delivery_delay",
		"fieldtype": "Data",
		"label": "Delivery Time",
		"insert_after": "free_shipping_from",
	},
	{
		"fieldname": "promise_column",
		"fieldtype": "Column Break",
		"insert_after": "delivery_delay",
	},
	{
		"fieldname": "return_days",
		"fieldtype": "Int",
		"label": "Return Period (days)",
		"insert_after": "promise_column",
	},
	{
		"fieldname": "promise_note",
		"fieldtype": "Data",
		"label": "Extra Promise",
		"insert_after": "return_days",
	},
]


def execute():
	if not frappe.db.exists("DocType", "Website Profile"):
		return
	create_custom_fields({"Website Profile": PROMISE_FIELDS}, ignore_validate=True)
