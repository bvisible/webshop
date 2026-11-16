# //// Neoffice — added file (no upstream equivalent). An Item deleted by force (a script, a bulk delete) skips the
# //// link check that refuses to delete an Item its Website Item still names, and its product page stayed published:
# //// listed on /all-products, and answering 500 to whoever clicked it (neoffice-maintenance#2670). The page now says
# //// 404 (WebsiteItem.get_context); this takes the card out of the listings at the moment the Item goes.
import frappe

from webshop.webshop.doctype.override_doctype.item_group import invalidate_cache_for


def execute(doc, method=None):
	"""Unpublish the Website Items of a deleted Item; they are kept, for the staff to delete or relink."""
	rows = frappe.get_all(
		"Website Item", filters={"item_code": doc.name, "published": 1}, fields=["name", "item_group"]
	)
	for row in rows:
		# Written straight: saving the Website Item would read its Item, which no longer exists.
		frappe.db.set_value("Website Item", row.name, "published", 0, update_modified=False)
		if row.item_group:
			invalidate_cache_for(row, row.item_group)
