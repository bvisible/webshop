# //// Neoffice — added file (second-hand feature, no upstream equivalent).
# //// A used or refurbished unit is its own Item, linked to the new item it
# //// copies. These fields carry its condition on the Item itself so the ERP
# //// (lists, reports, POS, manual quotations) can filter on it, and Website
# //// Item mirrors them for the shop (see website_item.json, fetch_from).

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

SECOND_HAND_DEPENDS_ON = 'eval:doc.item_condition && doc.item_condition != "New"'

CONDITION_FIELDS = [
	{
		"fieldname": "condition_section",
		"fieldtype": "Section Break",
		"label": "Condition",
		# `brand` is the last field of the Details section; the next field
		# is a Section Break, so this section holds nothing but its own fields.
		#//// Neoffice — moved from "brand" to "uoms" so the section closes the
		#//// Details tab, after the units of measure, instead of splitting it
		#//// (0227bfd0 "feat(occasion): une section État qui n'avale rien, expliquée, et un chemin depuis le catalogue").
		"insert_after": "uoms",
	},
	{
		"fieldname": "item_condition",
		"fieldtype": "Select",
		"label": "Condition",
		"options": "New\nRefurbished\nSecond-hand",
		"default": "New",
		"insert_after": "condition_section",
		"in_standard_filter": 1,
			#//// Neoffice — the choice says what it's for, so it isn't picked
			#//// blindly (0227bfd0 "feat(occasion): une section État qui n'avale rien, expliquée, et un chemin depuis le catalogue").
			"description": "New for a normal product. Second-hand or Refurbished when this item is itself the used unit: give its grade, its story, and the new model it comes from.",
		},
	{
		"fieldname": "condition_grade",
		"fieldtype": "Select",
		"label": "Condition Grade",
		"options": "\nLike New\nVery Good\nGood\nFair",
		"insert_after": "item_condition",
		"depends_on": SECOND_HAND_DEPENDS_ON,
	},
	{
		"fieldname": "condition_of_item",
		"fieldtype": "Link",
		"options": "Item",
		"label": "Used Unit Of",
		"description": "The new item this unit is a used or refurbished copy of",
		"insert_after": "condition_grade",
		"depends_on": SECOND_HAND_DEPENDS_ON,
	},
	{
		"fieldname": "condition_column",
		"fieldtype": "Column Break",
		"insert_after": "condition_of_item",
	},
	{
		"fieldname": "condition_details",
		"fieldtype": "Small Text",
		"label": "Condition Details",
		"description": "Signs of use, missing accessories, replaced parts. Shown to the customer.",
		"insert_after": "condition_column",
		"depends_on": SECOND_HAND_DEPENDS_ON,
	},
]


def execute():
	create_custom_fields({"Item": CONDITION_FIELDS}, update=True)
	frappe.clear_cache(doctype="Item")

	# `default` only applies to documents created from now on; the items that
	# exist today would keep an empty condition, and an empty facet value.
	frappe.db.sql("UPDATE `tabItem` SET item_condition = 'New' WHERE IFNULL(item_condition, '') = ''")
	if frappe.db.has_column("Website Item", "item_condition"):
		frappe.db.sql(
			"UPDATE `tabWebsite Item` SET item_condition = 'New' WHERE IFNULL(item_condition, '') = ''"
		)
	frappe.db.commit()
