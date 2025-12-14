import frappe


def execute():
    """Disable the gift-card Web Form as it's replaced by a custom page"""
    if not frappe.db.exists("Web Form", "gift-card"):
        return

    web_form = frappe.get_doc("Web Form", "gift-card")

    if web_form.published or web_form.route == "gift-cards":
        web_form.published = 0
        web_form.route = "gift-cards-form-disabled"
        web_form.flags.ignore_permissions = True
        web_form.save(ignore_permissions=True)
        frappe.db.commit()
