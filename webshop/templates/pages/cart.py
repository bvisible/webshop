# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

no_cache = 1

#//// Neoffice — frappe was used below without being imported: /cart answered 500
#//// (3c014716da, 2026-08-28).
import frappe

from webshop.webshop.shopping_cart.cart import get_cart_quotation
#//// Neoffice — added: the links our follow-up e-mails send. ▼▼▼ /cart?add=ITEM&qty=N
#//// (reorder) and /cart?coupon=CODE (abandoned-cart reminder) must DO what the e-mail
#//// promised (b8160bb709, 2026-09-03). A guest is sent to sign in and comes back to
#//// the same URL — a cart and a coupon belong to a customer. The explicit commit is
#//// load-bearing: Frappe never commits a GET, and the redirect ends the request, so
#//// without it the cart change would be rolled back. ▲▲▲
from frappe import _


def handle_email_links():
    """/cart?add=ITEM&qty=1 (reorder) and /cart?coupon=CODE (cart reminder).

    Both come from the follow-up emails. A guest is sent to sign in first —
    the cart and the coupon belong to a customer — then lands back here.
    """
    from urllib.parse import quote, urlencode

    from frappe.utils import cint

    from webshop.webshop.shopping_cart.cart import apply_coupon_code, update_cart

    add, coupon = frappe.form_dict.get("add"), frappe.form_dict.get("coupon")
    if not (add or coupon):
        return
    if frappe.session.user == "Guest":
        wanted = {k: v for k, v in (("add", add), ("qty", frappe.form_dict.get("qty")), ("coupon", coupon)) if v}
        frappe.local.flags.redirect_location = "/login?redirect-to=" + quote("/cart?" + urlencode(wanted))
        raise frappe.Redirect
    try:
        if add and frappe.db.exists("Website Item", {"item_code": add, "published": 1}):
            update_cart(add, cint(frappe.form_dict.get("qty")) or 1, add_qty=True)
        if coupon:
            apply_coupon_code(coupon, "")
    except Exception:
        frappe.log_error("Cart link from an email failed", frappe.get_traceback())
    # a GET is never committed by Frappe, and the redirect ends the request:
    # without this the cart change (and the error log) would be rolled back
    frappe.db.commit()
    frappe.local.flags.redirect_location = "/cart"
    raise frappe.Redirect


def get_context(context):
    #//// Neoffice — links from the follow-up emails land here
    handle_email_links()
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
