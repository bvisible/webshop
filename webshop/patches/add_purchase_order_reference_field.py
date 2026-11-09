# //// Neoffice — added file (no upstream equivalent). The Reference of a Purchase
# //// Order: the customer order or invoice it was bought for. The procurement of
# //// the multi-warehouse feature writes it (one purchase order per customer
# //// document since 2026-11-09, no more stacking into the supplier's open draft),
# //// and merging the drafts of one supplier joins the references of the merged
# //// orders. Shown in the list, so a draft says at a glance whom it is for.

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

FIELDNAME = "neo_source_reference"

FIELD = {
	"fieldname": FIELDNAME,
	"label": "Reference",
	"fieldtype": "Data",
	"insert_after": "supplier_name",
	"in_list_view": 1,
	"in_standard_filter": 1,
	"no_copy": 1,
}


def execute():
	create_custom_fields({"Purchase Order": [FIELD]}, update=True)
	frappe.clear_cache(doctype="Purchase Order")
