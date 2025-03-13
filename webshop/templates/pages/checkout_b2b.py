# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from webshop.webshop.shopping_cart.cart import get_cart_quotation, get_party, _get_cart_quotation

def get_context(context):
    """Context for the B2B checkout page"""
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
    context.customer_name = frappe.db.get_value("Customer", party, "customer_name")
    
    return context
