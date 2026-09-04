#//// Neoffice — added file (no upstream equivalent).
#//// Unpublishes the legacy `gift-card` Web Form and frees the `gift-cards` route for
#//// our own page (d579b1c02a, 2025-12-14). Deleting the Web Form record would take
#//// the submitted records with it, so it is unpublished and renamed instead.
#//// The form's app folder (webshop/webshop/web_form/gift_card) was deleted on
#//// 2026-09-04: a standard Web Form only exists because that folder is imported at
#//// migrate, so a fresh site never gets the record and this patch no-ops there. It
#//// stays for the sites that already carry it.
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
