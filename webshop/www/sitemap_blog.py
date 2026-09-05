# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

from urllib.parse import quote

import frappe
# //// Neoffice multi-site: build absolute URLs on the current site's domain
from webshop.webshop.multi_site import site_url as get_url
from frappe.utils.caching import redis_cache
from webshop.www.sitemap_utils import prepare_url_for_xml, escape_xml

no_cache = 1
base_template_path = "www/sitemap_blog.xml"


def get_context(context):
    """Generate the blog posts sitemap XML"""
    # //// Neoffice multi-site: vary the redis cache key per site
    from webshop.webshop.multi_site import get_current_profile_name
    links = get_blog_links(website_profile=get_current_profile_name())
    
    # Limit to 50,000 URLs per sitemap as per Google guidelines
    if len(links) > 50000:
        links = links[:50000]
    
    return {"links": links}


@redis_cache(ttl=6 * 60 * 60)
def get_blog_links(website_profile=None):
    """Get all published Blog Posts"""
    links = []
    
    try:
        # Get all published Blog Posts
        blog_posts = frappe.get_all(
            "Blog Post",
            fields=["route", "name", "modified", "title", "featured", "meta_image"],
            filters={"published": 1},
            order_by="featured desc, published_on desc, modified desc"
        )
        
        for post in blog_posts:
            if post.route:
                link = {
                    "loc": prepare_url_for_xml(get_url(quote(post.route.encode("utf-8")))),
                    "lastmod": f"{post.modified:%Y-%m-%d}",
                    "changefreq": "monthly",
                    "priority": 0.7 if post.featured else 0.6
                }
                
                # Add featured image if available
                if post.meta_image:
                    link["images"] = [{
                        "loc": prepare_url_for_xml(get_url(post.meta_image)),
                        "title": escape_xml(post.title)
                    }]
                
                links.append(link)
                
    except Exception as e:
        frappe.log_error(f"Error generating blog sitemap: {str(e)}", "Sitemap Generation")
    
    return links