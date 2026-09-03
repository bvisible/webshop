import frappe

#//// Neoffice — rewritten. Upstream saved the Website Item inside the loop,
#//// once per changed field, and its `if not changed: return` sat inside the
#//// loop where it could never be true. The condition fields of the
#//// second-hand feature travel with the base fields; a field the Website
#//// Item does not have (older schema) is skipped instead of failing.
MIRRORED_FIELDS = [
	"item_name",
	"item_group",
	"stock_uom",
	"brand",
	"description",
	"disabled",
	"item_condition",
	"condition_grade",
	"condition_of_item",
	"condition_details",
]


def execute(doc, method=None):
	"""Update Website Item if change in Item impacts it."""
	web_item = frappe.db.exists("Website Item", {"item_code": doc.item_code})
	if not web_item:
		return

	doc_before_save = doc.get_doc_before_save()
	if not doc_before_save:
		return

	web_item_meta = frappe.get_meta("Website Item")
	changed = {}
	for field in MIRRORED_FIELDS:
		if field != "disabled" and not web_item_meta.has_field(field):
			continue
		if doc_before_save.get(field) == doc.get(field):
			continue
		if field == "disabled":
			changed["published"] = not doc.get(field)
		else:
			changed[field] = doc.get(field)

	if not changed:
		return

	web_item_doc = frappe.get_doc("Website Item", web_item)
	web_item_doc.update(changed)
	web_item_doc.save()
