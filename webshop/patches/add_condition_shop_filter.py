# //// Neoffice — added file (second-hand feature, no upstream equivalent).
# //// Register the Condition facet in the shop sidebar. The filter builder
# //// only renders it once a published item is used or refurbished (see
# //// product_data_engine/filters.py), so a shop that sells new goods only
# //// sees exactly what it saw before.

import frappe

FIELDNAME = "item_condition"


def execute():
	if not frappe.db.exists("DocType", "Webshop Settings"):
		return

	settings = frappe.get_single("Webshop Settings")
	if any(row.fieldname == FIELDNAME for row in (settings.filter_fields or [])):
		return

	settings.append("filter_fields", {"fieldname": FIELDNAME})
	settings.flags.ignore_permissions = True
	settings.flags.ignore_mandatory = True
	settings.save()
	frappe.db.commit()
