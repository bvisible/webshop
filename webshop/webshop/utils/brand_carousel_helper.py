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
    
    # Get brands with product count using SQL for better performance
    query = """
        SELECT 
            b.name as brand_name,
            b.brand,
            b.image as logo,
            b.description,
            COUNT(DISTINCT wi.name) as product_count
        FROM `tabBrand` b
        LEFT JOIN `tabWebsite Item` wi ON wi.brand = b.name AND wi.published = 1
        GROUP BY b.name, b.brand, b.image, b.description
        HAVING product_count > 0
    """
    
    # Add sorting
    if sort_by == "product_count":
        query += " ORDER BY product_count DESC, b.brand ASC"
    elif sort_by == "random":
        query += " ORDER BY RAND()"
    else:  # default to brand_name
        query += " ORDER BY b.brand ASC"
    
    # Add limit
    query += f" LIMIT {int(limit)}"
    
    try:
        brands_data = frappe.db.sql(query, as_dict=True)
        
        if debug:
            frappe.logger().debug(f"Brand query returned {len(brands_data)} brands")
            if brands_data and len(brands_data) > 0:
                frappe.logger().debug(f"Sample brand data: {brands_data[0]}")
    except Exception as e:
        frappe.log_error(f"Error in brand carousel query: {str(e)}", "Brand Carousel Error")
        return []
    
    # Format brands for carousel
    formatted_brands = []
    for brand in brands_data:
        # Create filter for the brand
        brand_filter = '{"brand":["' + brand.brand_name + '"]}'
        
        formatted_brand = {
            "brand_name": brand.brand,  # This is the alias from SQL query
            "logo": brand.logo,
            "route": f"all-products?field_filters={quote(brand_filter)}",
            "description": brand.description or "",
            "product_count": brand.product_count
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
    for brand_name in brand_names:
        if brand_name in brand_map:
            brand = brand_map[brand_name]
            
            # Get product count
            product_count = frappe.db.count(
                "Website Item",
                filters={"brand": brand_name, "published": 1}
            )
            
            if product_count > 0:
                brand_filter = '{"brand":["' + brand_name + '"]}'
                formatted_brand = {
                    "brand_name": brand.brand,
                    "logo": brand.image,
                    "route": f"all-products?field_filters={quote(brand_filter)}",
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