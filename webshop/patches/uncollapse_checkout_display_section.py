import frappe


def execute():
    """Un-collapse the 'Display in Checkout' section on Payment Gateway Account
    so its checkout_title / checkout_description fields are visible by default
    (they document a payment method at checkout — e.g. the multi-payment
    explanation). The section was created collapsible=1, hiding those fields."""
    name = frappe.db.get_value(
        "Custom Field",
        {"dt": "Payment Gateway Account", "fieldname": "checkout_display_section"},
        "name",
    )
    if name:
        frappe.db.set_value("Custom Field", name, "collapsible", 0)
        frappe.clear_cache(doctype="Payment Gateway Account")
