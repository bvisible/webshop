# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

from urllib.parse import quote

import frappe
from frappe.utils import nowdate
# //// Neoffice multi-site: build absolute URLs on the current site's domain
from webshop.webshop.multi_site import site_url as get_url
from frappe.utils.caching import redis_cache
from frappe.website.router import get_doctypes_with_web_view, get_pages
from webshop.www.sitemap_utils import prepare_url_for_xml, escape_xml

no_cache = 1
base_template_path = "www/sitemap.xml"


def get_context(context):
    """Generate the sitemap XML including all published content"""
    # //// Neoffice multi-site: vary the redis cache key per site
    from webshop.webshop.multi_site import get_current_profile_name
    links = []

    # Get default Frappe pages
    links.extend(get_frappe_pages())

    # Get published pages from doctypes (Website Items, Blog Posts, etc.)
    links.extend(get_published_doctype_pages(website_profile=get_current_profile_name()))

    # Get Builder Pages
    links.extend(get_builder_pages(website_profile=get_current_profile_name()))

    # Get Web Pages
    links.extend(get_web_pages(website_profile=get_current_profile_name()))
    
    # Get webshop specific pages
    links.extend(get_webshop_static_pages())
    
    # Remove duplicates based on loc
    seen = set()
    unique_links = []
    for link in links:
        if link["loc"] not in seen:
            seen.add(link["loc"])
            unique_links.append(link)
    
    # Sort by priority then by loc
    unique_links.sort(key=lambda x: (-x.get("priority", 0.5), x["loc"]))
    
    return {"links": unique_links}


def get_frappe_pages():
    """Get pages from Frappe's default page system"""
    links = []
    for route, page in get_pages().items():
        if page.sitemap:
            links.append({
                "loc": prepare_url_for_xml(get_url(quote(page.name.encode("utf-8")))),
                "lastmod": nowdate(),
                "changefreq": "weekly",
                "priority": 0.8 if route in ["", "products", "contact", "about"] else 0.5
            })
    return links


@redis_cache(ttl=6 * 60 * 60)
def get_published_doctype_pages(website_profile=None):
    """Get all published pages from doctypes with web view"""
    links = []
    
    # Get all doctypes with web view
    doctypes_with_web_view = get_doctypes_with_web_view()
    
    for doctype in doctypes_with_web_view:
        try:
            meta = frappe.get_meta(doctype)
            
            # Skip if guests can't view
            if not meta.allow_guest_to_view:
                continue
            
            # Get the condition field for published status
            condition_field = None
            if hasattr(meta, "is_published_field") and meta.is_published_field:
                condition_field = meta.is_published_field
            elif doctype == "Website Item":
                condition_field = "published"
            elif doctype == "Blog Post":
                condition_field = "published"
            else:
                # Try to get from controller
                try:
                    controller = frappe.get_controller(doctype)
                    if hasattr(controller, "website") and hasattr(controller.website, "condition_field"):
                        condition_field = controller.website.condition_field
                except:
                    pass
            
            if not condition_field:
                continue
            
            # Get all published documents
            filters = {condition_field: 1}
            
            # Special handling for Website Items to include only those with routes
            if doctype == "Website Item":
                docs = frappe.get_all(
                    doctype,
                    fields=["route", "name", "modified", "ranking"],
                    filters=filters,
                    order_by="modified desc"
                )
                for doc in docs:
                    if doc.route:
                        links.append({
                            "loc": prepare_url_for_xml(get_url(quote(doc.route.encode("utf-8")))),
                            "lastmod": f"{doc.modified:%Y-%m-%d}",
                            "changefreq": "daily",
                            "priority": min(0.9, 0.7 + (doc.ranking or 0) * 0.01)
                        })
            elif doctype == "Blog Post":
                docs = frappe.get_all(
                    doctype,
                    fields=["route", "name", "modified", "featured"],
                    filters=filters,
                    order_by="modified desc"
                )
                for doc in docs:
                    if doc.route:
                        links.append({
                            "loc": prepare_url_for_xml(get_url(quote(doc.route.encode("utf-8")))),
                            "lastmod": f"{doc.modified:%Y-%m-%d}",
                            "changefreq": "monthly",
                            "priority": 0.7 if doc.featured else 0.6
                        })
            elif doctype == "Item Group":
                docs = frappe.get_all(
                    doctype,
                    fields=["route", "name", "modified"],
                    filters=filters,
                    order_by="modified desc"
                )
                for doc in docs:
                    if doc.route:
                        links.append({
                            "loc": prepare_url_for_xml(get_url(quote(doc.route.encode("utf-8")))),
                            "lastmod": f"{doc.modified:%Y-%m-%d}",
                            "changefreq": "weekly",
                            "priority": 0.8
                        })
            else:
                # For other doctypes
                docs = frappe.get_all(
                    doctype,
                    fields=["route", "name", "modified"],
                    filters=filters,
                    order_by="modified desc"
                )
                for doc in docs:
                    if doc.route:
                        links.append({
                            "loc": prepare_url_for_xml(get_url(quote(doc.route.encode("utf-8")))),
                            "lastmod": f"{doc.modified:%Y-%m-%d}",
                            "changefreq": "monthly",
                            "priority": 0.5
                        })
            
        except Exception as e:
            # Log error but continue with other doctypes
            frappe.log_error(f"Error getting sitemap entries for {doctype}: {str(e)}", "Sitemap Generation")
            continue
    
    return links


@redis_cache(ttl=6 * 60 * 60)
def get_builder_pages(website_profile=None):
    """Get all published Builder Pages"""
    links = []
    
    try:
        # Check if Builder app is installed
        if "builder" not in frappe.get_installed_apps():
            return links
        
        # Get all published Builder Pages
        builder_pages = frappe.get_all(
            "Builder Page",
            fields=["name", "route", "modified", "page_title"],
            filters={"published": 1}
        )
        
        # Keywords to exclude (footer, navbar, etc.)
        exclude_keywords = ["footer", "navbar", "header", "navigation", "menu"]
        
        for page in builder_pages:
            if page.route:
                # Skip pages with excluded keywords in route or title
                page_title_lower = (page.page_title or "").lower()
                route_lower = page.route.lower()
                
                if any(keyword in route_lower or keyword in page_title_lower for keyword in exclude_keywords):
                    continue
                    
                # Homepage gets highest priority
                priority = 1.0 if page.route in ["homepage", ""] else 0.7
                
                links.append({
                    "loc": prepare_url_for_xml(get_url(quote(page.route.encode("utf-8")))),
                    "lastmod": f"{page.modified:%Y-%m-%d}",
                    "changefreq": "weekly",
                    "priority": priority
                })
    except Exception as e:
        # Log error but don't break the sitemap
        frappe.log_error(f"Error getting Builder pages: {str(e)}", "Sitemap Generation")
    
    return links


def get_webshop_static_pages():
    """Get static pages specific to webshop"""
    links = []
    
    # Add static webshop pages
    static_pages = [
        {"route": "all-products", "title": "All Products", "priority": 0.9, "changefreq": "daily"},
        {"route": "shop-by-category", "title": "Shop by Category", "priority": 0.8, "changefreq": "weekly"},
    ]
    
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
    
    for page in static_pages:
        links.append({
            "loc": prepare_url_for_xml(get_url(quote(page["route"].encode("utf-8")))),
            "lastmod": nowdate(),
            "changefreq": page.get("changefreq", "weekly"),
            "priority": page.get("priority", 0.5)
        })
    
    return links


@redis_cache(ttl=6 * 60 * 60)
def get_web_pages(website_profile=None):
    """Get all published Web Pages"""
    links = []
    
    try:
        # Get all published Web Pages
        web_pages = frappe.get_all(
            "Web Page",
            fields=["name", "route", "modified", "title"],
            filters={"published": 1}
        )
        
        for page in web_pages:
            if page.route:
                links.append({
                    "loc": prepare_url_for_xml(get_url(quote(page.route.encode("utf-8")))),
                    "lastmod": f"{page.modified:%Y-%m-%d}",
                    "changefreq": "monthly",
                    "priority": 0.6
                })
    except Exception as e:
        # Log error but don't break the sitemap
        frappe.log_error(f"Error getting Web Pages: {str(e)}", "Sitemap Generation")
    
    return links