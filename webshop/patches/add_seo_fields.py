# //// Neoffice — added file (no upstream equivalent): the Search engines fields of Item Group and
# //// Brand (neoffice-maintenance#691, lot 6, 2026-09-25). Website Item carries its own in its
# //// JSON. What the merchant writes there is the page's title and description for search engines
# //// (seo/page_meta.py); left empty, the page says what it computes, which the form's preview shows.

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

TITLE_HELP = "About 60 characters show in Google's results. Empty: the page's own title."
DESCRIPTION_HELP = "About 160 characters show in Google's results. Empty: the page's own description."
AI_HELP = "Set when a proposal from Nora filled these fields: the merchant decides, the document remembers."


def fields(after):
	return [
		{
			"fieldname": "seo_title",
			"fieldtype": "Data",
			"label": "Title for search engines",
			"description": TITLE_HELP,
			"insert_after": after,
		},
		{
			"fieldname": "seo_description",
			"fieldtype": "Small Text",
			"label": "Description for search engines",
			"description": DESCRIPTION_HELP,
			"insert_after": "seo_title",
		},
		{
			"fieldname": "seo_ai_assisted",
			"fieldtype": "Check",
			"label": "Written with AI assistance",
			"description": AI_HELP,
			"read_only": 1,
			"insert_after": "seo_description",
		},
		{
			"fieldname": "seo_ai_assisted_on",
			"fieldtype": "Datetime",
			"label": "Written with AI assistance on",
			"read_only": 1,
			"depends_on": "seo_ai_assisted",
			"insert_after": "seo_ai_assisted",
		},
		{
			"fieldname": "seo_preview",
			"fieldtype": "HTML",
			"label": "Google preview",
			"insert_after": "seo_ai_assisted_on",
		},
	]


def execute():
	item_group_after = (
		"google_product_category"
		if frappe.get_meta("Item Group").has_field("google_product_category")
		else "website_title"
	)
	create_custom_fields({"Item Group": fields(item_group_after), "Brand": fields("description")}, update=True)
	frappe.clear_cache(doctype="Item Group")
	frappe.clear_cache(doctype="Brand")
