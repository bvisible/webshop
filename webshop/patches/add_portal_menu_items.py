import frappe


def execute():
    """Add Portal Menu Items for loyalty points and gift cards if enabled"""
    settings = frappe.get_doc("Webshop Settings")

    # Add loyalty points menu if enabled
    if settings.enable_loyalty_points:
        add_portal_menu_item_if_not_exists(
            title="Loyalty Points",
            route="/loyalty_points",
            role="Customer"
        )

    # Add gift cards menu if enabled
    if settings.enable_gift_cards:
        # Remove old route with hyphen if exists
        old_exists = frappe.db.exists("Portal Menu Item", {
            "route": "/gift-cards",
            "parenttype": "Portal Settings"
        })
        if old_exists:
            frappe.db.delete("Portal Menu Item", {
                "route": "/gift-cards",
                "parenttype": "Portal Settings"
            })

        add_portal_menu_item_if_not_exists(
            title="Gift cards",
            route="/gift_cards",
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
