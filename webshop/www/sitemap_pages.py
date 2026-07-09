# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

from urllib.parse import quote

import frappe
from frappe.utils import nowdate
#//// Neoffice multi-site: build absolute URLs on the current site's domain
from webshop.webshop.multi_site import site_url as get_url
from frappe.utils.caching import redis_cache
from webshop.www.sitemap_utils import prepare_url_for_xml, escape_xml

no_cache = 1
base_template_path = "www/sitemap_pages.xml"


def get_context(context):
    """Generate the pages sitemap XML (Builder Pages, Web Pages, static pages)"""
    #//// Neoffice multi-site: vary the redis cache key per site
    from webshop.webshop.multi_site import get_current_profile_name
    links = []

    # Get Builder Pages
    links.extend(get_builder_page_links(website_profile=get_current_profile_name()))

    # Get Web Pages
    links.extend(get_web_page_links(website_profile=get_current_profile_name()))
    
    # Get static pages
    links.extend(get_static_page_links())
    
    # Remove duplicates and sort
    seen = set()
    unique_links = []
    for link in links:
        if link["loc"] not in seen:
            seen.add(link["loc"])
            unique_links.append(link)
    
    unique_links.sort(key=lambda x: (-x.get("priority", 0.5), x["loc"]))
    
    # Limit to 50,000 URLs per sitemap
    if len(unique_links) > 50000:
        unique_links = unique_links[:50000]
    
    return {"links": unique_links}


@redis_cache(ttl=6 * 60 * 60)
def get_builder_page_links(website_profile=None):
    """Get all published Builder Pages"""
    links = []
    
    try:
        # Check if Builder app is installed
        if "builder" not in frappe.get_installed_apps():
            return links
        
        # Get all published Builder Pages
        builder_pages = frappe.get_all(
            "Builder Page",
            fields=["name", "route", "modified", "page_title", "meta_image"],
            filters={"published": 1}
        )
        
        # Keywords to exclude (footer, navbar, etc.)
        exclude_keywords = ["footer", "navbar", "header", "navigation", "menu"]
        
        for page in builder_pages:
            if page.route:
                # Skip pages with excluded keywords
                page_title_lower = (page.page_title or "").lower()
                route_lower = page.route.lower()
                
                if any(keyword in route_lower or keyword in page_title_lower for keyword in exclude_keywords):
                    continue
                
                # Homepage gets highest priority
                priority = 1.0 if page.route in ["homepage", ""] else 0.7
                
                link = {
                    "loc": prepare_url_for_xml(get_url(quote(page.route.encode("utf-8")))),
                    "lastmod": f"{page.modified:%Y-%m-%d}",
                    "changefreq": "weekly",
                    "priority": priority
                }
                
                # Add meta image if available
                if page.meta_image:
                    link["images"] = [{
                        "loc": prepare_url_for_xml(get_url(page.meta_image)),
                        "title": escape_xml(page.page_title)
                    }]
                
                links.append(link)
                
    except Exception as e:
        frappe.log_error(f"Error getting Builder pages for sitemap: {str(e)}", "Sitemap Generation")
    
    return links


@redis_cache(ttl=6 * 60 * 60)
def get_web_page_links(website_profile=None):
    """Get all published Web Pages"""
    links = []
    
    try:
        # Get all published Web Pages
        web_pages = frappe.get_all(
            "Web Page",
            fields=["name", "route", "modified", "title", "meta_image"],
            filters={"published": 1}
        )
        
        for page in web_pages:
            if page.route:
                link = {
                    "loc": prepare_url_for_xml(get_url(quote(page.route.encode("utf-8")))),
                    "lastmod": f"{page.modified:%Y-%m-%d}",
                    "changefreq": "monthly",
                    "priority": 0.6
                }
                
                # Add meta image if available
                if page.meta_image:
                    link["images"] = [{
                        "loc": prepare_url_for_xml(get_url(page.meta_image)),
                        "title": escape_xml(page.title)
                    }]
                
                links.append(link)
                
    except Exception as e:
        frappe.log_error(f"Error getting Web Pages for sitemap: {str(e)}", "Sitemap Generation")
    
    return links


def get_static_page_links():
    """Get static pages like contact, about, etc."""
    links = []
    
    # Add contact page if exists
    try:
        contact_settings = frappe.get_doc("Contact Us Settings", "Contact Us Settings")
        if contact_settings.heading:
            links.append({
                "loc": prepare_url_for_xml(get_url("contact")),
                "lastmod": f"{contact_settings.modified:%Y-%m-%d}" if contact_settings.modified else nowdate(),
                "changefreq": "monthly",
                "priority": 0.7
            })
    except:
        pass
    
    # Add about page if exists
    try:
        about_settings = frappe.get_doc("About Us Settings", "About Us Settings")
        if about_settings.page_title:
            links.append({
                "loc": prepare_url_for_xml(get_url("about")),
                "lastmod": f"{about_settings.modified:%Y-%m-%d}" if about_settings.modified else nowdate(),
                "changefreq": "monthly",
                "priority": 0.7
            })
    except:
        pass
    
    # Add other static pages
    static_pages = [
        {"route": "all-products", "priority": 0.9, "changefreq": "daily"},
        {"route": "shop-by-category", "priority": 0.8, "changefreq": "weekly"},
    ]
    
    for page in static_pages:
        links.append({
            "loc": prepare_url_for_xml(get_url(quote(page["route"].encode("utf-8")))),
            "lastmod": nowdate(),
            "changefreq": page.get("changefreq", "weekly"),
            "priority": page.get("priority", 0.5)
        })
    
    return links