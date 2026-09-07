# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

no_cache = 1

# //// Neoffice — frappe was used below without being imported: /cart answered 500
# //// (3c014716da, 2026-08-28).
import frappe

from webshop.webshop.shopping_cart.cart import get_cart_quotation
# //// Neoffice — added: the links our follow-up e-mails send. ▼▼▼ /cart?add=ITEM&qty=N
# //// (reorder) and /cart?coupon=CODE (abandoned-cart reminder) must DO what the e-mail
# //// promised (b8160bb709, 2026-09-03). A guest is sent to sign in and comes back to
# //// the same URL — a cart and a coupon belong to a customer. The explicit commit is
# //// load-bearing: Frappe never commits a GET, and the redirect ends the request, so
# //// without it the cart change would be rolled back. ▲▲▲
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


# //// Neoffice — added (2026-09-07): a cart line keeps the rate it was added with,
# //// and a plain view never re-prices. A line added before its item had a selling
# //// price (or on a list without one) therefore stayed at CHF 0.00 for good, even
# //// once the price existed — reported on a second-hand unit. When, and only when, a
# //// non-gift-card line is actually at zero, re-price the quotation once (the same
# //// path update_cart uses; gift cards keep their chosen amount) and re-read it.
def _reprice_if_stale(cart_data):
    from frappe.utils import flt

    doc = cart_data.get("doc") if cart_data else None
    if not doc or not doc.get("name") or not doc.get("items"):
        return cart_data
    from webshop.webshop.shopping_cart.cart import apply_cart_settings, is_gift_card_item

    stale = any(flt(item.get("rate")) == 0 and not is_gift_card_item(item.item_code) for item in doc.get("items"))
    if not stale:
        return cart_data
    user = frappe.session.user
    try:
        # the shop re-prices its own cart; ERPNext v15 checks Item/Account read perms
        # inside validate that a portal customer lacks (neoffice-maintenance#277).
        frappe.set_user("Administrator")
        quotation = frappe.get_doc("Quotation", doc.name)
        quotation.flags.ignore_permissions = True
        apply_cart_settings(quotation=quotation)
        quotation.save(ignore_version=True)
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        frappe.log_error("Cart reprice on view failed", frappe.get_traceback())
        return cart_data
    finally:
        frappe.set_user(user)
    return get_cart_quotation()


def get_context(context):
    # //// Neoffice — links from the follow-up emails land here
    handle_email_links()
    # //// Neoffice multi-site — a site reserved for professionals does not show
    # //// its cart to an anonymous visitor. The catalog stays open (showcase),
    # //// but the cart and the order require an account.
    from webshop.webshop.multi_site import site_is_business_only

    if frappe.session.user == "Guest" and site_is_business_only():
        frappe.local.flags.redirect_location = "/login?redirect-to=/cart"
        raise frappe.Redirect

    # //// Neoffice — themes print context.title as the visible page heading
    # //// and as the last breadcrumb, and Frappe defaults it to the route
    # //// name — untranslated. A French shop read "cart" on screen while
    # //// its browser tab said the translated title.
    context.title = _("Shopping Cart")
    from webshop.webshop.shopping_cart.guest_cart import check_and_merge_guest_cart
    
    # Check and merge guest cart if needed
    check_and_merge_guest_cart()
    
    context.body_class = "product-page"
    cart_data = get_cart_quotation()
    cart_data = _reprice_if_stale(cart_data)
    context.update(cart_data)
    # //// Neoffice — whoever may fill a cart here is offered the quick order (quick_order/api.py)
    from webshop.webshop.quick_order.api import may_use_quick_order

    context.show_quick_order = may_use_quick_order()
    
    # Add loyalty points information
    if cart_data.get("doc"):
        from webshop.webshop.utils.loyalty_cart import get_loyalty_points_for_cart
        loyalty_info = get_loyalty_points_for_cart(cart_data["doc"])
        if loyalty_info:
            context.loyalty_cart_info = loyalty_info
