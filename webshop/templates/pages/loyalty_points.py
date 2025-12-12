# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.utils import flt

from webshop.webshop.doctype.webshop_settings.webshop_settings import get_shopping_cart_settings
from webshop.webshop.utils.utils import format_currency_value

no_cache = 1


def get_context(context):
    """Get context for the loyalty points page"""
    context.no_cache = 1
    context.show_sidebar = True

    settings = get_shopping_cart_settings()

    # Check if loyalty points is enabled
    context.enabled = settings.enable_loyalty_points and settings.loyalty_program

    if not context.enabled:
        return

    # Check if user is logged in
    if frappe.session.user == "Guest":
        context.customer = None
        return

    # Get customer linked to the user
    customer = get_customer_for_user()
    context.customer = customer

    if not customer:
        return

    # Get customer's loyalty program
    customer_loyalty_program = frappe.db.get_value(
        "Customer", customer, "loyalty_program"
    )
    context.loyalty_program = customer_loyalty_program

    if not customer_loyalty_program:
        return

    # Get loyalty program details
    try:
        loyalty_program = frappe.get_doc("Loyalty Program", customer_loyalty_program)
        context.loyalty_program_name = loyalty_program.loyalty_program_name
        context.conversion_factor = loyalty_program.conversion_factor
    except frappe.DoesNotExistError:
        context.loyalty_program = None
        return

    # Get total available points
    from erpnext.accounts.doctype.loyalty_program.loyalty_program import (
        get_loyalty_program_details_with_points,
    )

    loyalty_details = get_loyalty_program_details_with_points(
        customer, customer_loyalty_program
    )

    context.total_points = loyalty_details.get("loyalty_points", 0)

    # Calculate points value
    if context.conversion_factor and context.total_points:
        points_value = flt(context.total_points) * flt(context.conversion_factor)
        currency = frappe.get_cached_value(
            "Company", loyalty_program.company, "default_currency"
        ) if loyalty_program.company else "CHF"
        context.points_value = format_currency_value(points_value, currency=currency)
        context.conversion_rate = format_currency_value(
            context.conversion_factor, currency=currency
        )
    else:
        context.points_value = None
        context.conversion_rate = None

    # Get points history
    context.points_history = get_loyalty_points_history_for_customer(customer, limit=10)
    context.has_more_entries = len(context.points_history) >= 10


def get_customer_for_user():
    """Get the customer linked to the current user"""
    user = frappe.session.user

    # First check if there's a contact linked to this user
    contact = frappe.db.get_value(
        "Contact",
        {"user": user},
        "name"
    )

    if contact:
        # Get customer linked to this contact
        customer = frappe.db.get_value(
            "Dynamic Link",
            {
                "parent": contact,
                "parenttype": "Contact",
                "link_doctype": "Customer"
            },
            "link_name"
        )
        if customer:
            return customer

    # Fallback: check if user email matches a customer
    customer = frappe.db.get_value("Customer", {"email_id": user}, "name")

    return customer


def get_loyalty_points_history_for_customer(customer, limit=10, offset=0):
    """Get loyalty points history for a customer"""
    entries = frappe.get_all(
        "Loyalty Point Entry",
        filters={"customer": customer},
        fields=[
            "name",
            "posting_date",
            "loyalty_points",
            "purchase_amount",
            "invoice_type",
            "invoice"
        ],
        order_by="posting_date desc, creation desc",
        limit_page_length=limit,
        limit_start=offset
    )

    return entries


@frappe.whitelist()
def get_loyalty_points_history(offset=0, limit=10):
    """API to get loyalty points history with pagination"""
    if frappe.session.user == "Guest":
        frappe.throw(_("Please log in to view your loyalty points."))

    customer = get_customer_for_user()
    if not customer:
        return {"entries": [], "has_more": False}

    offset = int(offset)
    limit = int(limit)

    entries = get_loyalty_points_history_for_customer(customer, limit=limit + 1, offset=offset)

    has_more = len(entries) > limit
    if has_more:
        entries = entries[:limit]

    # Format dates for display
    for entry in entries:
        entry["posting_date"] = frappe.utils.format_date(entry["posting_date"])

    return {
        "entries": entries,
        "has_more": has_more
    }
