import frappe
from frappe import _
from typing import List, Dict, Optional
from urllib.parse import quote
from webshop.webshop.utils.carousel_cache import CarouselCacheManager


def get_brands_with_product_count(limit: int = 20, sort_by: str = "brand_name", 
                                 use_cache: bool = False, cache_ttl: int = 3600, debug: bool = False) -> List[Dict]:
    """
    Get brands with their product count and formatted for carousel display.
    
    Args:
        limit: Maximum number of brands to return
        sort_by: Sort criteria - "brand_name", "product_count", or "random"
        use_cache: Whether to use cache
        cache_ttl: Cache time to live in seconds
        
    Returns:
        List of brand dictionaries formatted for carousel
    """
    if use_cache:
        cache_manager = CarouselCacheManager()
        cache_params = {
            "type": "brands",
            "limit": limit,
            "sort_by": sort_by
        }
        cache_key = cache_manager.generate_cache_key(**cache_params)
        
        # Try to get from cache
        cached_brands = cache_manager.get_from_cache(cache_key)
        if cached_brands is not None:
            return cached_brands
    
    # //// Neoffice — the brands this site shows something of, counted as the brand pages and the
    # //// facets count them (brand_pages.offered_brands: published, not sold, visible on this
    # //// site, gift cards and hidden variants out), 2026-09-29. The hand-written query counted
    # //// published items of the site but kept hidden variants, and the carousel include did not
    # //// even use it: it listed every Brand record, so a public shop's home page offered a brand
    # //// with no product, whose card led to an empty catalogue.
    from webshop.webshop.product_data_engine.brand_pages import brand_link, brand_route, offered_brands

    offered = offered_brands()
    if not offered:
        return []
    brands_data = frappe.get_all(
        "Brand", filters={"name": ["in", list(offered)]}, fields=["name", "brand", "image", "description"]
    )
    # //// Neoffice — sorted and cut here, over offered_brands (see above), not in SQL
    if sort_by == "product_count":
        brands_data.sort(key=lambda b: (-offered[b.name], (b.brand or b.name).lower()))
    # //// Neoffice — see the sort marker above
    elif sort_by == "random":
        import random

        random.shuffle(brands_data)
    # //// Neoffice — see the sort marker above
    else:  # default to brand_name
        brands_data.sort(key=lambda b: (b.brand or b.name).lower())
    # //// Neoffice — see the sort marker above
    brands_data = brands_data[: int(limit)]

    if debug:
        frappe.logger().debug(f"Brand carousel: {len(brands_data)} brands")

    # Format brands for carousel
    formatted_brands = []
    # //// Neoffice — a brand links to its own page when it has one (#691 lot 2), else to the
    # //// catalogue filtered on it, which robots.txt closes (brand_pages.brand_link). Every
    # //// brand offered here has a page: the routes come from the same reading.
    page_routes = {name: "/" + brand_route(name) for name in offered}
    for brand in brands_data:
        # //// Neoffice — no brand filter built here any more: brand_link gives the address.
        formatted_brand = {
            "brand_name": brand.brand,
            "logo": brand.image,
            # //// Neoffice — see brand_link above.
            "route": brand_link(brand.name, page_routes),
            "description": brand.description or "",
            "product_count": offered[brand.name],
        }
        formatted_brands.append(formatted_brand)

    # Cache the results if cache is enabled
    if use_cache and 'cache_manager' in locals():
        cache_manager.set_cache(cache_key, formatted_brands, cache_ttl)
    
    return formatted_brands


def get_top_brands(limit: int = 8, use_cache: bool = True, cache_ttl: int = 7200) -> List[Dict]:
    """
    Get top brands sorted by product count.
    
    Args:
        limit: Maximum number of brands to return
        use_cache: Whether to use cache (default: True)
        cache_ttl: Cache time to live in seconds (default: 2 hours)
        
    Returns:
        List of top brands
    """
    return get_brands_with_product_count(
        limit=limit,
        sort_by="product_count",
        use_cache=use_cache,
        cache_ttl=cache_ttl
    )


def get_featured_brands(brand_names: List[str], use_cache: bool = True, 
                       cache_ttl: int = 3600) -> List[Dict]:
    """
    Get specific featured brands in a custom order.
    
    Args:
        brand_names: List of brand names to feature
        use_cache: Whether to use cache
        cache_ttl: Cache time to live in seconds
        
    Returns:
        List of featured brands in the specified order
    """
    if not brand_names:
        return []
    
    if use_cache:
        cache_manager = CarouselCacheManager()
        cache_params = {
            "type": "featured_brands",
            "brands": ",".join(sorted(brand_names))
        }
        cache_key = cache_manager.generate_cache_key(**cache_params)
        
        # Try to get from cache
        cached_brands = cache_manager.get_from_cache(cache_key)
        if cached_brands is not None:
            return cached_brands
    
    # Get brand data
    brands_data = frappe.get_all(
        "Brand",
        filters={
            "name": ["in", brand_names]
        },
        fields=["name", "brand", "image", "description"]
    )
    
    # Create a map for easy lookup
    brand_map = {b.name: b for b in brands_data}
    
    # Format brands in the requested order
    formatted_brands = []
    # //// Neoffice — a brand links to its own page when it has one (#691 lot 2), and a featured
    # //// brand shows only when this site shows something of it, counted as the brand page and the
    # //// facets count it (brand_pages.offered_brands, 2026-09-29; it counted per brand, without
    # //// the hidden variants and gift cards rules).
    from webshop.webshop.product_data_engine.brand_pages import brand_link, brand_route, offered_brands

    offered = offered_brands()
    page_routes = {name: "/" + brand_route(name) for name in offered}
    for brand_name in brand_names:
        if brand_name in brand_map:
            brand = brand_map[brand_name]
            # //// Neoffice — the figure of offered_brands (see the marker above the loop)
            product_count = offered.get(brand_name, 0)
            if product_count > 0:
                # //// Neoffice — no brand filter built here any more: brand_link gives the address.
                formatted_brand = {
                    "brand_name": brand.brand,
                    "logo": brand.image,
                    # //// Neoffice — see brand_link above.
                    "route": brand_link(brand_name, page_routes),
                    "description": brand.description or "",
                    "product_count": product_count
                }
                formatted_brands.append(formatted_brand)
    
    # Cache the results if cache is enabled
    if use_cache and 'cache_manager' in locals():
        cache_manager.set_cache(cache_key, formatted_brands, cache_ttl)
    
    return formatted_brands


def clear_brand_carousel_cache():
    """Clear all brand carousel cache entries."""
    cache_manager = CarouselCacheManager()
    cache_manager.clear_cache(pattern="brands")
    cache_manager.clear_cache(pattern="featured_brands")


# Hook for cache invalidation when brands are updated
def clear_brand_cache_on_update(doc, method=None):
    """Clear brand cache when a brand is updated."""
    if doc.doctype == "Brand":
        clear_brand_carousel_cache()
    elif doc.doctype == "Website Item" and doc.brand:
        # Also clear when website items are updated as it affects product count
        clear_brand_carousel_cache()