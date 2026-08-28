# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

no_cache = 1

import frappe

from webshop.webshop.shopping_cart.cart import get_cart_quotation
from frappe import _


def get_context(context):
    #//// Neoffice multi-site — un site réservé aux professionnels ne montre pas
    #//// son panier à un visiteur anonyme. Le catalogue reste ouvert (vitrine),
    #//// le panier et la commande demandent un compte.
    from webshop.webshop.multi_site import site_reserve_aux_professionnels

    if frappe.session.user == "Guest" and site_reserve_aux_professionnels():
        frappe.local.flags.redirect_location = "/login?redirect-to=/cart"
        raise frappe.Redirect

    #//// Neoffice — themes print context.title as the visible page heading
    #//// and as the last breadcrumb, and Frappe defaults it to the route
    #//// name — untranslated. A French shop read "cart" on screen while
    #//// its browser tab said the translated title.
    context.title = _("Shopping Cart")
    from webshop.webshop.shopping_cart.guest_cart import check_and_merge_guest_cart
    
    # Check and merge guest cart if needed
    check_and_merge_guest_cart()
    
    context.body_class = "product-page"
    cart_data = get_cart_quotation()
    context.update(cart_data)
    
    # Add loyalty points information
    if cart_data.get("doc"):
        from webshop.webshop.utils.loyalty_cart import get_loyalty_points_for_cart
        loyalty_info = get_loyalty_points_for_cart(cart_data["doc"])
        if loyalty_info:
            context.loyalty_cart_info = loyalty_info
