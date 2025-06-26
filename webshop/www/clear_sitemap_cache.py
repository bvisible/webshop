#!/usr/bin/env python
"""
Script to clear sitemap cache and force regeneration
Usage: bench --site site1.local execute webshop.www.clear_sitemap_cache.clear_cache
"""

import frappe
from frappe.utils.caching import clear_cache


def clear_sitemap_cache():
    """Clear all sitemap caches to force regeneration"""
    
    # List of cache keys to clear
    cache_functions = [
        "webshop.www.sitemap.get_published_doctype_pages",
        "webshop.www.sitemap.get_builder_pages", 
        "webshop.www.sitemap.get_web_pages",
        "webshop.www.sitemap_products.get_product_links",
        "webshop.www.sitemap_categories.get_category_links",
        "webshop.www.sitemap_brands.get_brand_links",
        "webshop.www.sitemap_blog.get_blog_links",
        "webshop.www.sitemap_pages.get_builder_page_links",
        "webshop.www.sitemap_pages.get_web_page_links"
    ]
    
    # Clear each cache
    for func in cache_functions:
        try:
            clear_cache(func)
            print(f"✓ Cleared cache for {func}")
        except Exception as e:
            print(f"✗ Error clearing cache for {func}: {str(e)}")
    
    print("\n✅ Sitemap cache cleared! The sitemaps will be regenerated on next access.")
    
    
if __name__ == "__main__":
    clear_sitemap_cache()