# //// Neoffice — added file (no upstream equivalent): the product identifiers' two switches of
# //// Webshop Settings, on as their default says (neoffice-maintenance#691, plan note 20, B2 and B4).
import frappe

SWITCHES = ("show_product_identifiers", "search_supplier_references")


def execute():
	# A new field of a Single reads 0 on a site that stored no value for it, whatever its default:
	# each switch is on for every shop, unless a merchant already set it.
	for field in SWITCHES:
		stored = frappe.db.sql(
			"select value from `tabSingles` where doctype = 'Webshop Settings' and field = %s", field
		)
		if not stored:
			frappe.db.set_single_value("Webshop Settings", field, 1)
