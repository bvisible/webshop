# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from webshop.webshop.doctype.webshop_settings.webshop_settings import get_shopping_cart_settings
from webshop.webshop.utils.utils import format_currency_value

no_cache = 1


def get_context(context):
    """Get context for the gift cards page"""
    #//// Neoffice — themes print context.title as the visible page
    #//// heading and as the last breadcrumb, and Frappe defaults it to
    #//// the route name — untranslated: the page read "gift-cards" on
    #//// screen while its browser tab said the translated title.
    context.title = _("Gift Cards")
    context.no_cache = 1
    context.show_sidebar = True

    settings = get_shopping_cart_settings()

    # Check if gift cards is enabled
    context.enabled = settings.enable_gift_cards

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

    # Get customer's gift cards using ignore_permissions
    context.gift_cards = get_gift_cards_for_customer(customer)
    context.has_gift_cards = len(context.gift_cards) > 0

    # Get gift card product URL for "Buy a gift card" button
    context.gift_card_product_url = get_gift_card_product_url(settings)


def get_gift_card_product_url(settings):
    """Get the URL of the gift card product from Webshop Settings"""
    if settings.gift_card_template:
        route = frappe.db.get_value("Website Item", settings.gift_card_template, "route")
        if route:
            return "/" + route
    return "/all-products"


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


def get_gift_cards_for_customer(customer):
    """Get gift cards for a customer"""
    # Use direct SQL to avoid permission issues
    gift_cards = frappe.db.sql("""
        SELECT
            name,
            coupon_name,
            coupon_code,
            gift_card_amount,
            valid_from,
            valid_upto,
            used,
            maximum_use,
            sales_invoice
        FROM `tabCoupon Code`
        WHERE customer = %(customer)s
        AND coupon_type = 'Gift Card'
        ORDER BY valid_upto DESC, creation DESC
    """, {"customer": customer}, as_dict=True)

    # Format the gift cards data
    today_date = getdate(today())
    for card in gift_cards:
        # Calculate remaining amount
        card.remaining_amount = flt(card.gift_card_amount)
        card.formatted_amount = format_currency_value(card.remaining_amount)

        # Check if card is expired
        if card.valid_upto:
            card.is_expired = getdate(card.valid_upto) < today_date
            card.formatted_valid_upto = frappe.utils.format_date(card.valid_upto)
        else:
            card.is_expired = False
            card.formatted_valid_upto = None

        # Check if card is used
        card.is_used = card.used >= card.maximum_use if card.maximum_use else False

        # Determine card status
        if card.is_expired:
            card.status = "expired"
            card.status_label = _("Expired")
        elif card.is_used or card.remaining_amount <= 0:
            card.status = "used"
            card.status_label = _("Used")
        else:
            card.status = "active"
            card.status_label = _("Active")

        # Format valid_from
        if card.valid_from:
            card.formatted_valid_from = frappe.utils.format_date(card.valid_from)

    return gift_cards


@frappe.whitelist()
def get_gift_cards(offset=0, limit=10):
    """API to get gift cards with pagination"""
    if frappe.session.user == "Guest":
        frappe.throw(_("Please log in to view your gift cards."))

    customer = get_customer_for_user()
    if not customer:
        return {"gift_cards": [], "has_more": False}

    offset = int(offset)
    limit = int(limit)

    gift_cards = get_gift_cards_for_customer(customer)

    # Apply pagination
    total = len(gift_cards)
    gift_cards = gift_cards[offset:offset + limit]

    has_more = (offset + limit) < total

    return {
        "gift_cards": gift_cards,
        "has_more": has_more
    }
