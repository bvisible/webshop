# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

from urllib.parse import quote

import frappe
from frappe.utils import get_url
from frappe.utils.caching import redis_cache
from webshop.www.sitemap_utils import prepare_url_for_xml, escape_xml

no_cache = 1
base_template_path = "www/sitemap_products.xml"


def get_context(context):
    """Generate the products sitemap XML"""
    #//// Neoffice multi-site: scope to the current site (arg varies the redis cache key per site)
    from webshop.webshop.multi_site import get_current_profile_name
    links = get_product_links(get_current_profile_name())
    
    # Limit to 50,000 URLs per sitemap as per Google guidelines
    if len(links) > 50000:
        links = links[:50000]
    
    return {"links": links}


@redis_cache(ttl=6 * 60 * 60)
def get_product_links(website_profile=None):
    """Get all published Website Items with their images"""
    links = []
    
    try:
        #//// Neoffice multi-site: hide items restricted to other sites
        from webshop.webshop.multi_site import excluded_item_names
        product_filters = {"published": 1}
        _excluded = excluded_item_names()
        if _excluded:
            product_filters["name"] = ["not in", _excluded]
        # Get all published Website Items
        products = frappe.get_all(
            "Website Item",
            fields=["route", "name", "modified", "web_item_name", "website_image", "ranking"],
            filters=product_filters,
            order_by="ranking desc, modified desc"
        )
        
        for product in products:
            if product.route:
                link = {
                    "loc": prepare_url_for_xml(get_url(quote(product.route.encode("utf-8")))),
                    "lastmod": f"{product.modified:%Y-%m-%d}",
                    "changefreq": "daily",
                    "priority": min(0.9, 0.7 + (product.ranking or 0) * 0.01)
                }
                
                # Add product image if available
                if product.website_image:
                    link["images"] = [{
                        "loc": prepare_url_for_xml(get_url(product.website_image)),
                        "title": escape_xml(product.web_item_name)
                    }]
                
                links.append(link)
                
    except Exception as e:
        frappe.log_error(f"Error generating products sitemap: {str(e)}", "Sitemap Generation")
    
    return links