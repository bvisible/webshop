import frappe

def execute():
    """Move page_break field under description in Sales Item doctypes using Property Setter"""
    doctypes = [
        "Quotation Item",
        "Sales Order Item",
        "Sales Invoice Item"
    ]

    for doctype in doctypes:
        property_setter_name = f"{doctype}-page_break-insert_after"

        # Check if Property Setter already exists
        if not frappe.db.exists("Property Setter", property_setter_name):
            frappe.get_doc({
                "doctype": "Property Setter",
                "doctype_or_field": "DocField",
                "doc_type": doctype,
                "field_name": "page_break",
                "property": "insert_after",
                "property_type": "Data",
                "value": "description"
            }).insert(ignore_permissions=True)

    frappe.db.commit()
    frappe.clear_cache()
