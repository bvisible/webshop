# //// Neoffice — added file (no upstream equivalent). Drops the shop's price caches
# //// when an Item Price changes. Our listing caches prices and discounts to keep the
# //// facets fast; upstream reads them live and needs no invalidation (e7a63e7680,
# //// 2025-12-02 "add automatic cache invalidation for Pricing Rule and Item Price
# //// changes").
"""
Invalidate webshop cache when Item Prices are created, modified, or deleted.
This ensures that price information is always up-to-date on the webshop.
"""
import frappe
from frappe import _


def execute(doc, method=None):
    """
    Hook to invalidate webshop caches when an Item Price is modified.

    Args:
        doc: The Item Price document
        method: The method being called (on_update, after_insert, on_trash)
    """
    # Only process selling prices
    if not doc.selling:
        return

    invalidate_webshop_price_cache(doc.item_code, doc.price_list)


def invalidate_webshop_price_cache(item_code=None, price_list=None):
    """
    Invalidate all webshop caches related to prices.

    Args:
        item_code: Optional item code for logging
        price_list: Optional price list for logging
    """
    try:
        # Clear carousel cache (contains price info)
        from webshop.webshop.utils.carousel_cache import CarouselCacheManager
        cache_manager = CarouselCacheManager()
        cache_manager.clear_cache()

        # Clear promotion cache specifically
        cache_manager.clear_promotion_cache()

        # Clear brand carousel cache
        try:
            from webshop.webshop.utils.brand_carousel_helper import clear_brand_carousel_cache
            clear_brand_carousel_cache()
        except ImportError:
            pass

        # Clear product price caches
        clear_product_price_cache(item_code)

        # Clear website item cache if item_code is provided
        if item_code:
            clear_website_item_cache(item_code)

        if item_code:
            frappe.logger().info(f"Webshop cache invalidated for Item Price: {item_code}")

    except Exception as e:
        frappe.log_error(
            f"Error invalidating webshop cache for Item Price {item_code}: {str(e)}",
            "Webshop Cache Invalidation Error"
        )


def clear_product_price_cache(item_code=None):
    """Clear product price related caches."""
    try:
        # Clear discount preview cache
        cache_keys = frappe.cache().get_keys("discount_preview:*")
        for key in cache_keys:
            frappe.cache().delete_value(key)

        # Clear any product info cache
        cache_keys = frappe.cache().get_keys("product_info:*")
        for key in cache_keys:
            frappe.cache().delete_value(key)

        # Clear webshop item cache
        cache_keys = frappe.cache().get_keys("webshop_item:*")
        for key in cache_keys:
            frappe.cache().delete_value(key)

        # Clear specific item cache if provided
        if item_code:
            frappe.clear_document_cache("Item", item_code)
            # Also clear Website Item cache
            website_item = frappe.db.get_value("Website Item", {"item_code": item_code}, "name")
            if website_item:
                frappe.clear_document_cache("Website Item", website_item)

    except Exception as e:
        frappe.log_error(f"Error clearing product price cache: {str(e)}", "Cache Clear Error")


def clear_website_item_cache(item_code):
    """Clear cache for a specific website item."""
    try:
        website_item = frappe.db.get_value("Website Item", {"item_code": item_code}, "name")
        if website_item:
            from webshop.webshop.doctype.website_item.website_item import invalidate_cache_for_web_item
            invalidate_cache_for_web_item(frappe.get_doc("Website Item", website_item))
    except Exception as e:
        frappe.log_error(f"Error clearing website item cache: {str(e)}", "Cache Clear Error")
