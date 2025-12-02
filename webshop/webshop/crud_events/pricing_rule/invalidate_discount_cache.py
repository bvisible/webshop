"""
Invalidate webshop cache when Pricing Rules are created, modified, or deleted.
This ensures that discount information is always up-to-date on the webshop.
"""
import frappe
from frappe import _


def execute(doc, method=None):
    """
    Hook to invalidate webshop caches when a Pricing Rule is modified.

    Args:
        doc: The Pricing Rule document
        method: The method being called (on_update, after_insert, on_trash)
    """
    # Only process selling pricing rules (not buying)
    if not doc.selling:
        return

    # Only process if it affects webshop (coupon-based or discount-based)
    if not (doc.coupon_code_based or doc.discount_percentage or doc.discount_amount):
        return

    invalidate_webshop_discount_cache(doc.name)


def invalidate_webshop_discount_cache(pricing_rule_name=None):
    """
    Invalidate all webshop caches related to discounts and prices.

    Args:
        pricing_rule_name: Optional name of the pricing rule for logging
    """
    try:
        # Clear carousel cache (contains price/discount info)
        from webshop.webshop.utils.carousel_cache import CarouselCacheManager
        cache_manager = CarouselCacheManager()
        cache_manager.clear_cache()

        # Clear brand carousel cache
        try:
            from webshop.webshop.utils.brand_carousel_helper import clear_brand_carousel_cache
            clear_brand_carousel_cache()
        except ImportError:
            pass

        # Clear any product-related caches
        clear_product_price_cache()

        if pricing_rule_name:
            frappe.logger().info(f"Webshop cache invalidated due to Pricing Rule: {pricing_rule_name}")

    except Exception as e:
        frappe.log_error(
            f"Error invalidating webshop cache for Pricing Rule {pricing_rule_name}: {str(e)}",
            "Webshop Cache Invalidation Error"
        )


def clear_product_price_cache():
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

    except Exception as e:
        frappe.log_error(f"Error clearing product price cache: {str(e)}", "Cache Clear Error")
