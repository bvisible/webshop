# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

import frappe
from frappe.utils import nowdate
# //// Neoffice multi-site: build absolute URLs on the current site's domain
from webshop.webshop.multi_site import site_url as get_url
from webshop.www.sitemap_utils import prepare_url_for_xml

no_cache = 1
base_template_path = "www/sitemap_index.xml"


def get_context(context):
    """Generate the sitemap index that references all other sitemaps"""
    
    sitemaps = [
        {
            "loc": prepare_url_for_xml(get_url("sitemap.xml")),
            "lastmod": nowdate(),
            "description": "Main sitemap with all content types"
        },
        {
            "loc": prepare_url_for_xml(get_url("sitemap_products.xml")),
            "lastmod": nowdate(),
            "description": "Products sitemap (Website Items)"
        },
        {
            "loc": prepare_url_for_xml(get_url("sitemap_categories.xml")),
            "lastmod": nowdate(),
            "description": "Product categories sitemap (Item Groups)"
        },
        {
            "loc": prepare_url_for_xml(get_url("sitemap_brands.xml")),
            "lastmod": nowdate(),
            "description": "Brands sitemap"
        },
        {
            "loc": prepare_url_for_xml(get_url("sitemap_blog.xml")),
            "lastmod": nowdate(),
            "description": "Blog posts sitemap"
        },
        {
            "loc": prepare_url_for_xml(get_url("sitemap_pages.xml")),
            "lastmod": nowdate(),
            "description": "Static and dynamic pages sitemap"
        }
    ]
    
    return {"sitemaps": sitemaps}