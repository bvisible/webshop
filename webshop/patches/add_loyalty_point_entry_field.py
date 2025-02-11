import frappe

def execute():
	"""Add loyalty point entry fields to Quotation, Sales Order and Sales Invoice"""
	
	# List of fields to add
	fields = [
		{
			"fieldname": "loyalty_program",
			"label": "Loyalty Program",
			"fieldtype": "Link",
			"options": "Loyalty Program",
			"insert_after": "base_total_taxes_and_charges",
			"read_only": 1,
			"print_hide": 1
		},
		{
			"fieldname": "loyalty_points",
			"label": "Loyalty Points",
			"fieldtype": "Float",
			"insert_after": "loyalty_program",
			"read_only": 1,
			"print_hide": 1
		},
		{
			"fieldname": "loyalty_amount",
			"label": "Loyalty Amount",
			"fieldtype": "Currency",
			"insert_after": "loyalty_points",
			"read_only": 1,
			"print_hide": 1
		},
		{
			"fieldname": "loyalty_point_entry",
			"label": "Loyalty Point Entry",
			"fieldtype": "Link",
			"options": "Loyalty Point Entry",
			"insert_after": "loyalty_amount",
			"read_only": 1,
			"print_hide": 1,
			"description": "Reference to the Loyalty Point Entry created when points are applied",
			"allow_on_submit": 1
		}
	]
	
	for field in fields:
		if not frappe.db.exists("Custom Field", {
			"dt": "Quotation",
			"fieldname": field["fieldname"]
		}):
			custom_field = frappe.get_doc({
				"doctype": "Custom Field",
				"dt": "Quotation",
				"fieldname": field["fieldname"],
				"label": field["label"],
				"fieldtype": field["fieldtype"],
				"options": field.get("options"),
				"insert_after": field["insert_after"],
				"read_only": field.get("read_only", 0),
				"print_hide": field.get("print_hide", 0),
				"description": field.get("description", ""),
				"translatable": 0
			})
			custom_field.insert(ignore_permissions=True)
			
	frappe.db.commit()
