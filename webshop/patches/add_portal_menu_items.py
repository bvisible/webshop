# //// Neoffice — added file (no upstream equivalent).
# //// Portal Menu Items for /loyalty-points and /gift-cards, added only when the
# //// matching Webshop Setting is on. Upstream's portal knows Orders, Invoices and
# //// Addresses and nothing else (2f63a51219, 2025-12-12). reference_doctype is left
# //// empty on purpose: setting it made the portal check a permission the customer
# //// does not hold and hid the entry (9909429ca3).
import frappe


def execute():
    """Add Portal Menu Items for loyalty points and gift cards if enabled"""
    settings = frappe.get_doc("Webshop Settings")

    # Add loyalty points menu if enabled
    if settings.enable_loyalty_points:
        add_portal_menu_item_if_not_exists(
            title="Loyalty",
            route="/loyalty-points",
            role="Customer"
        )

    # Add gift cards menu if enabled
    if settings.enable_gift_cards:
        # //// Neoffice — the page's address is /gift-cards since 2026-10-25 (it was /gift_cards, and before that
        # //// /gift-cards again); this patch used to delete a row with the hyphen, which is now the right one.
        add_portal_menu_item_if_not_exists(
            title="Gift cards",
            route="/gift-cards",
            role="Customer"
        )


def add_portal_menu_item_if_not_exists(title, route, role):
    """Add a Portal Menu Item if it doesn't already exist"""
    exists = frappe.db.exists("Portal Menu Item", {
        "route": route,
        "parenttype": "Portal Settings"
    })

    if not exists:
        # Get last idx
        last_idx = frappe.db.sql("""
            SELECT MAX(idx)
            FROM `tabPortal Menu Item`
            WHERE parenttype='Portal Settings'
        """)[0][0] or 0

        # Create menu entry
        portal_settings = frappe.get_doc("Portal Settings")
        portal_settings.append("menu", {
            "title": title,
            "enabled": 1,
            "route": route,
            "role": role,
            "idx": last_idx + 1
        })
        portal_settings.save()
        frappe.db.commit()
