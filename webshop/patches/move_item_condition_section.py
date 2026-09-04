#//// Neoffice — added file (second-hand units, no upstream equivalent).
import frappe


def execute():
	"""Move the Condition section to the end of the Item's Details tab.

	Inserted after `brand`, the section swallowed every custom field other
	apps had put after `brand` too (attachments, collection, alcohol flag):
	the newest custom field lands right after its anchor, so a section break
	there captures its elders. After `uoms` nothing follows but the next tab.
	Also gives the condition select the explanation a first-time user needs.
	"""
	if not frappe.db.exists("Custom Field", "Item-condition_section"):
		return
	frappe.db.set_value("Custom Field", "Item-condition_section", "insert_after", "uoms", update_modified=False)
	if frappe.db.exists("Custom Field", "Item-item_condition"):
		frappe.db.set_value(
			"Custom Field",
			"Item-item_condition",
			"description",
			"New for a normal product. Second-hand or Refurbished when this item is itself the used unit: give its grade, its story, and the new model it comes from.",
			update_modified=False,
		)
	frappe.clear_cache(doctype="Item")
