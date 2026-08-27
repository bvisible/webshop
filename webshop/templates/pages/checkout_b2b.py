# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from webshop.webshop.shopping_cart.cart import get_cart_quotation, get_party, _get_cart_quotation

def get_context(context):
    """Context for the B2B checkout page"""
    #//// Neoffice — Frappe derives context.title from the route when nobody
    #//// sets it, and never translates it; themes print it as the visible
    #//// page heading, so the page read "checkout-b2b".
    #////
    #//// Deliberately NOT _("Checkout"): that string is shared with the cart
    #//// button, where fr renders it "Paiement" — right for a button, wrong for
    #//// a page heading that then repeats a step name. Same fix as checkout.py.
    context.title = _("Your order")
    context.no_cache = 1
    context.show_sidebar = 0

    # Check if user is logged in
    if not frappe.session.user or frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = "/login"
        raise frappe.Redirect

    # Get cart settings
    cart_settings = frappe.get_doc("Webshop Settings")
    
    # Check if B2B checkout is enabled
    if not cart_settings.activate_b2b_checkout:
        frappe.local.flags.redirect_location = "/cart"
        raise frappe.Redirect
    
    # Get party information
    party = get_party()
    if not party:
        frappe.local.flags.redirect_location = "/cart"
        raise frappe.Redirect
        
    # Check if a quotation exists
    quotation = _get_cart_quotation()
    
    # If quotation is inexistent or has no items, redirect to product page
    if not quotation or not quotation.get('items'):
        frappe.local.flags.redirect_location = '/all-products'
        raise frappe.Redirect
        
    # Check if there is a cookie with a quotation name
    if not quotation or quotation.is_new():
        quotation_name = frappe.request.cookies.get('quotation_name')
        guest_session_id = frappe.request.cookies.get('guest_session_id')
        
        if quotation_name and guest_session_id:
            # Check if quotation exists with the corresponding guest_session_id
            existing_quotation = frappe.db.get_value(
                "Quotation",
                {
                    "name": quotation_name,
                    "guest_session_id": guest_session_id,
                    "docstatus": 0,
                    "status": "Draft"
                },
                ["name", "guest_session_id"],
                as_dict=True
            )
            
            if existing_quotation:
                quotation = frappe.get_doc("Quotation", existing_quotation.name)
                
    # Check if quotation is valid after trying to retrieve from cookies
    if not quotation or not quotation.get('items'):
        frappe.local.flags.redirect_location = '/all-products'
        raise frappe.Redirect
    
    # Get cart and customer information
    cart_info = get_cart_quotation()
    
    # Check if the customer is a B2B customer
    if not cart_info.get("is_b2b_customer"):
        frappe.local.flags.redirect_location = "/cart"
        raise frappe.Redirect
            
    # Add cart information to context
    context.update(cart_info)
    
    # Add customer information to context
    #//// Neoffice — was get_value("Customer", party, "customer_name"), passing
    #//// the whole party DOCUMENT where a name is expected.
    #////
    #//// Frappe treats a non-string second argument as a FILTER dict, so instead
    #//// of "the name of this customer" the query became "the name of some
    #//// customer matching these fields" — and returned whichever row came
    #//// first. Measured on osiris: a quotation belonging to "Test B2B Webshop"
    #//// rendered « Société : E2E Nouveau », the name of an unrelated customer.
    #////
    #//// That is one company's name shown to another company, on the page where
    #//// they confirm an order billed to their account.
    context.customer_name = frappe.db.get_value("Customer", party.name, "customer_name")
    
    return context
