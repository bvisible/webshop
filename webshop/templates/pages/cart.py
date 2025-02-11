# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

no_cache = 1

from webshop.webshop.shopping_cart.cart import get_cart_quotation


def get_context(context):
    from webshop.webshop.shopping_cart.guest_cart import check_and_merge_guest_cart
    
    # Check and merge guest cart if needed
    check_and_merge_guest_cart()
    
    context.body_class = "product-page"
    context.update(get_cart_quotation())
