import frappe
import hashlib
import json
from typing import Any, Dict, List, Optional


class CarouselCacheManager:
    """Manages caching for product carousels to reduce database queries."""
    
    def __init__(self):
        self.cache_prefix = "carousel_cache"
        
    def generate_cache_key(self, **kwargs) -> str:
        """
        Generate a unique cache key based on carousel parameters.
        
        Args:
            **kwargs: All parameters passed to get_carousel_items
            
        Returns:
            str: Unique cache key
        """
        # Sort parameters to ensure consistent key generation
        sorted_params = sorted(kwargs.items())
        
        # Create a string representation of parameters
        param_str = json.dumps(sorted_params, sort_keys=True, default=str)
        
        # Generate hash for the key
        hash_digest = hashlib.md5(param_str.encode()).hexdigest()
        
        # Include site name for multi-tenant support
        site_name = frappe.local.site
        
        return f"{self.cache_prefix}:{site_name}:{hash_digest}"
    
    def get_from_cache(self, cache_key: str) -> Optional[List[Dict[str, Any]]]:
        """
        Retrieve carousel items from cache.
        
        Args:
            cache_key: The cache key to lookup
            
        Returns:
            List of carousel items or None if not cached
        """
        try:
            cached_data = frappe.cache().get_value(cache_key)
            if cached_data:
                return cached_data
        except Exception as e:
            frappe.log_error(f"Error retrieving carousel cache: {str(e)}", "Carousel Cache Error")
        
        return None
    
    def set_cache(self, cache_key: str, data: List[Dict[str, Any]], ttl: int = 3600) -> None:
        """
        Store carousel items in cache with TTL.
        
        Args:
            cache_key: The cache key to store under
            data: List of carousel items to cache
            ttl: Time to live in seconds (default: 1 hour)
        """
        try:
            frappe.cache().set_value(cache_key, data, expires_in_sec=ttl)
        except Exception as e:
            frappe.log_error(f"Error setting carousel cache: {str(e)}", "Carousel Cache Error")
    
    def clear_cache(self, pattern: Optional[str] = None) -> None:
        """
        Clear carousel cache entries.
        
        Args:
            pattern: Optional pattern to match specific cache entries
        """
        try:
            if pattern:
                # Clear specific pattern
                cache_keys = frappe.cache().get_keys(f"{self.cache_prefix}:*{pattern}*")
                for key in cache_keys:
                    frappe.cache().delete_value(key)
            else:
                # Clear all carousel cache
                cache_keys = frappe.cache().get_keys(f"{self.cache_prefix}:*")
                for key in cache_keys:
                    frappe.cache().delete_value(key)
        except Exception as e:
            frappe.log_error(f"Error clearing carousel cache: {str(e)}", "Carousel Cache Error")
    
    def clear_item_group_cache(self, item_group: str) -> None:
        """
        Clear cache for a specific item group.
        
        Args:
            item_group: The item group to clear cache for
        """
        # Since we can't easily identify which cache entries contain a specific item group,
        # we'll clear all carousel cache when an item group is modified
        self.clear_cache()
    
    def clear_promotion_cache(self) -> None:
        """Clear cache for promotional carousels."""
        # Clear all carousel cache as promotions might affect multiple carousels
        self.clear_cache()


def clear_carousel_cache_on_item_update(doc, method=None):
    """
    Hook to clear carousel cache when items are updated.
    
    Args:
        doc: The document being updated
        method: The method being called
    """
    cache_manager = CarouselCacheManager()
    
    # Clear cache based on document type
    if doc.doctype == "Website Item":
        # Clear cache when website items are modified
        cache_manager.clear_cache()
    elif doc.doctype == "Item Price":
        # Clear promotion cache when prices change
        cache_manager.clear_promotion_cache()
    elif doc.doctype == "Item Group":
        # Clear cache for specific item group
        cache_manager.clear_item_group_cache(doc.name)


def warm_carousel_cache(item_group: Optional[str] = None, only_promotions: bool = False):
    """
    Pre-populate carousel cache for common queries.
    
    Args:
        item_group: Optional item group to warm cache for
        only_promotions: Whether to warm cache for promotional items only
    """
    from webshop.webshop.utils.product_carousel_helper import get_carousel_items
    
    # Common carousel configurations to warm
    configurations = [
        {"limit": 8, "sort_by": "creation", "use_cache": True},
        {"limit": 12, "sort_by": "creation", "use_cache": True},
        {"limit": 8, "sort_by": "modified", "use_cache": True},
    ]
    
    if only_promotions:
        configurations = [
            {**config, "only_promotions": True} 
            for config in configurations
        ]
    
    if item_group:
        configurations = [
            {**config, "item_group": item_group} 
            for config in configurations
        ]
    
    # Warm cache for each configuration
    for config in configurations:
        try:
            get_carousel_items(**config)
        except Exception as e:
            frappe.log_error(
                f"Error warming carousel cache for config {config}: {str(e)}", 
                "Carousel Cache Warming Error"
            )


@frappe.whitelist()
def clear_all_carousel_cache():
    """Clear all carousel cache entries. Can be called from UI."""
    if not frappe.has_permission("Webshop Settings", "write"):
        frappe.throw("Insufficient permissions to clear carousel cache")
    
    cache_manager = CarouselCacheManager()
    cache_manager.clear_cache()
    
    return {"status": "success", "message": "Carousel cache cleared successfully"}