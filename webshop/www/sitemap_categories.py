# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

from urllib.parse import quote

import frappe
from frappe.utils import get_url
from frappe.utils.caching import redis_cache
from webshop.www.sitemap_utils import prepare_url_for_xml, escape_xml

no_cache = 1
base_template_path = "www/sitemap_categories.xml"


def get_context(context):
    """Generate the categories sitemap XML"""
    links = get_category_links()
    
    # Limit to 50,000 URLs per sitemap as per Google guidelines
    if len(links) > 50000:
        links = links[:50000]
    
    return {"links": links}


@redis_cache(ttl=6 * 60 * 60)
def get_category_links():
    """Get all published Item Groups (categories)"""
    links = []
    
    try:
        # Get all Item Groups that are shown on website
        categories = frappe.get_all(
            "Item Group",
            fields=["name", "route", "modified", "parent_item_group", "image"],
            filters={"show_in_website": 1},
            order_by="parent_item_group, name"
        )
        
        # Create a map to track hierarchy depth
        parent_map = {}
        for cat in categories:
            parent_map[cat.name] = cat.parent_item_group
        
        def get_depth(name, depth=0):
            """Calculate depth in hierarchy"""
            if not name or name not in parent_map or depth > 10:
                return depth
            parent = parent_map.get(name)
            if parent and parent != "All Item Groups":
                return get_depth(parent, depth + 1)
            return depth
        
        for category in categories:
            if category.route:
                # Calculate priority based on hierarchy depth
                depth = get_depth(category.name)
                priority = max(0.5, 0.9 - (depth * 0.1))
                
                link = {
                    "loc": prepare_url_for_xml(get_url(quote(category.route.encode("utf-8")))),
                    "lastmod": f"{category.modified:%Y-%m-%d}",
                    "changefreq": "weekly",
                    "priority": priority
                }
                
                # Add category image if available
                if category.image:
                    link["images"] = [{
                        "loc": prepare_url_for_xml(get_url(category.image)),
                        "title": escape_xml(category.name)
                    }]
                
                links.append(link)
                
    except Exception as e:
        frappe.log_error(f"Error generating categories sitemap: {str(e)}", "Sitemap Generation")
    
    return links