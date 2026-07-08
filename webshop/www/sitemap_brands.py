# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

import json
from urllib.parse import quote

import frappe
#//// Neoffice multi-site: build absolute URLs on the current site's domain
from webshop.webshop.multi_site import site_url as get_url
from frappe.utils.caching import redis_cache
from webshop.www.sitemap_utils import prepare_url_for_xml, escape_xml

no_cache = 1
base_template_path = "www/sitemap_brands.xml"


def get_context(context):
    """Generate the brands sitemap XML"""
    #//// Neoffice multi-site: vary the redis cache key per site
    from webshop.webshop.multi_site import get_current_profile_name
    links = get_brand_links(website_profile=get_current_profile_name())
    
    # Limit to 50,000 URLs per sitemap as per Google guidelines
    if len(links) > 50000:
        links = links[:50000]
    
    return {"links": links}


@redis_cache(ttl=6 * 60 * 60)
def get_brand_links(website_profile=None):
    """Get all brands with their pages"""
    links = []
    
    try:
        # Get all brands
        brands = frappe.get_all(
            "Brand",
            fields=["name", "brand", "modified", "image"],
            order_by="brand asc"
        )
        
        for brand in brands:
            if brand.brand:
                # Create brand page URL with field filters
                # Format: /all-products?field_filters={"brand":["Brand Name"]}
                field_filters = json.dumps({"brand": [brand.brand]})
                brand_url = f"all-products?field_filters={quote(field_filters)}"
                
                link = {
                    "loc": prepare_url_for_xml(get_url(brand_url)),
                    "lastmod": f"{brand.modified:%Y-%m-%d}",
                    "changefreq": "weekly",
                    "priority": 0.7
                }
                
                # Add brand image if available
                if brand.image:
                    link["images"] = [{
                        "loc": prepare_url_for_xml(get_url(brand.image)),
                        "title": escape_xml(brand.brand)
                    }]
                
                links.append(link)
                
    except Exception as e:
        frappe.log_error(f"Error generating brands sitemap: {str(e)}", "Sitemap Generation")
    
    return links