import frappe

# //// Neoffice — rewritten. Upstream saved the Website Item inside the loop,
# //// once per changed field, and its `if not changed: return` sat inside the
# //// loop where it could never be true. The condition fields of the
# //// second-hand feature travel with the base fields; a field the Website
# //// Item does not have (older schema) is skipped instead of failing.
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
	# //// Neoffice — the whole function is flattened (early returns instead of upstream's
	# //// nested ifs) and the mirrored field list moved to a module constant, so the
	# //// second-hand condition fields could be added to it (d984eff855, 2026-09-03).
	# //// Behaviour is otherwise upstream's.
	"""Update Website Item if change in Item impacts it."""
	web_item = frappe.db.exists("Website Item", {"item_code": doc.item_code})
	if not web_item:
		return

	# //// Neoffice — early return when there is nothing to compare (see above).
	doc_before_save = doc.get_doc_before_save()
	if not doc_before_save:
		return

	# //// Neoffice — a mirrored field is skipped when the Website Item does not carry it:
	# //// the list now includes fields that only exist once our patches have run, and a
	# //// site mid-migration raised on the missing field (d984eff855, 2026-09-03).
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

	# //// Neoffice — see above.
	if not changed:
		return

	# //// Neoffice — see above.
	web_item_doc = frappe.get_doc("Website Item", web_item)
	web_item_doc.update(changed)
	web_item_doc.save()
