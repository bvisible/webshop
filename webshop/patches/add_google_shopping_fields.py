# //// Neoffice — added file (no upstream equivalent): the Google Shopping fields of Item Group
# //// (neoffice-maintenance#691, lot 3, 2026-09-24). A case keeps a group, and every group below
# //// it, out of the Merchant Center feed (seo/feeds/google.py excluded_groups): the airsoft
# //// replicas and their parts that Google's "Dangerous products" policy forbids. The Google
# //// product category is inherited the same way (google_category).

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	create_custom_fields(
		{
			"Item Group": [
				{
					"fieldname": "exclude_from_google_shopping",
					"fieldtype": "Check",
					"label": "Exclude from Google Shopping",
					"description": "Keeps this group and every group below it out of the Google Merchant Center feed.",
					"insert_after": "website_title",
				},
				{
					"fieldname": "google_product_category",
					"fieldtype": "Data",
					"label": "Google Product Category",
					"description": "Its number or its path in Google's taxonomy. Groups below inherit it.",
					"insert_after": "exclude_from_google_shopping",
				},
			]
		},
		update=True,
	)
	frappe.clear_cache(doctype="Item Group")
