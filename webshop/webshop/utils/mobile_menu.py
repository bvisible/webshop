import frappe
import json
from frappe import _
from webshop.webshop.utils.builder import get_builder_component_by_route, get_builder_page_content

@frappe.whitelist(allow_guest=True)
def get_navigation_content(route="navbar", use_cache=True):
    """
    Extracts only the navigation from the component associated with the specified route.
    Optimized for performance by using caching and minimal processing.
    
    Args:
        route (str): The route associated with the component (default "navbar")
        use_cache (bool): Use cache for results (default True)
    
    Returns:
        dict: HTML content of the navigation and status
    """
    try:
        # Method 1: Try to retrieve the component by its route
        component_data = get_builder_component_by_route(route, use_cache=use_cache)
        
        if component_data and component_data.get("block"):
            # Extract only the nav block from the JSON
            nav_html = extract_nav_from_component({
                "block": json.dumps(component_data["block"]) 
                if isinstance(component_data["block"], dict) 
                else component_data["block"]
            })
            
            return {
                "nav_content": nav_html,
                "success": True,
                "method": "route_component",
                "component": component_data.get("name")
            }
        
        # Method 2: Search directly for a nav element in the page with the same route
        page_data = get_builder_page_content(route=route, use_cache=use_cache)
        
        if page_data and page_data.get("blocks"):
            # Create an object similar to a component
            page_component = {
                "block": page_data.get("blocks"),
                "name": page_data.get("name")
            }
            
            # Extract only the nav block from the JSON
            nav_html = extract_nav_from_component(page_component)
            
            # Verify that we have found a nav element (avoid default fallback)
            if nav_html and not nav_html.startswith("<nav><a href='/'>Accueil</a></nav>"):
                return {
                    "nav_content": nav_html,
                    "success": True,
                    "method": "route_page_nav",
                    "page": page_data.get("name")
                }
        
        # Method 3 (fallback): Search directly for the Navbar component
        component = find_navbar_component()
        
        if component:
            # Extract only the nav block from the JSON
            nav_html = extract_nav_from_component(component)
            
            return {
                "nav_content": nav_html,
                "success": True,
                "method": "direct_search",
                "component": component.name
            }
        
        # No method worked, use fallback navigation
        return {
            "nav_content": "<nav><a href='/'>Accueil</a></nav>",
            "success": True,
            "method": "fallback",
            "message": _("Navigation fallback generated")
        }
        
    except Exception as e:
        frappe.log_error("Error extracting navigation", 
                        f"Error: {str(e)}\nTraceback: {frappe.get_traceback()}")
        return {
            "nav_content": "<nav><a href='/'>Accueil</a></nav>",
            "success": True,
            "method": "error_fallback",
            "message": str(e)
        }

def find_navbar_component():
    """
    Search for the Navbar component in Builder Component
    """
    try:
        # Case-insensitive search for "navbar"
        filters = [
            ["component_name", "like", "navbar"],
            ["docstatus", "<", 2]  # Do not include deleted documents
        ]
        
        components = frappe.get_all(
            "Builder Component",
            filters=filters,
            fields=["name", "component_name", "block"],
            order_by="modified desc",
            limit=1
        )
        
        if not components:
            return None
            
        return components[0]
    except Exception as e:
        frappe.log_error("Error finding navbar component", str(e))
        return None

def extract_nav_from_component(component):
    """
    Extracts only the nav element from the component's JSON block
    and generates minimal HTML
    """
    try:
        if not component or not component.block:
            return "<nav><a href='/'>Accueil</a></nav>"
        
        # Parse the JSON block
        block_data = json.loads(component.block)
        
        # Recursively find the nav block
        nav_block = find_nav_block(block_data)
        
        if not nav_block:
            return "<nav><a href='/'>Home</a></nav>"
        
        # Generate minimal HTML for this block
        nav_html = generate_nav_html(nav_block)
        
        return nav_html
    except Exception as e:
        frappe.log_error("Error extracting nav from component", str(e))
        return "<nav><a href='/'>Home</a></nav>"

def find_nav_block(block):
    """
    Recursively find the first block of type 'nav' or with element='nav'
    """
    if not block:
        return None
        
    # Check if it's a nav block
    if block.get("element") == "nav":
        return block
        
    # Check children
    if "children" in block and isinstance(block["children"], list):
        for child in block["children"]:
            result = find_nav_block(child)
            if result:
                return result
                
    return None

def generate_nav_html(nav_block):
    """
    Generates minimal HTML for a nav block
    """
    try:
        if not nav_block:
            return "<nav><a href='/'>Home</a></nav>"
            
        # Extract basic attributes
        attributes = {}
        
        # Classes
        classes = nav_block.get("classes", [])
        if classes and isinstance(classes, list):
            attributes["class"] = " ".join(classes)
            
        # Other block attributes
        if "attributes" in nav_block and isinstance(nav_block["attributes"], dict):
            for key, value in nav_block["attributes"].items():
                if key and value is not None:
                    attributes[key] = value
        
        # Generate attribute string
        attrs_str = ""
        for key, value in attributes.items():
            attrs_str += f" {key}=\"{value}\""
        
        # Generate content of child elements (links)
        links_html = ""
        
        if "children" in nav_block and isinstance(nav_block["children"], list):
            for child in nav_block["children"]:
                link_html = generate_link_html(child)
                if link_html:
                    links_html += link_html
        
        # Si aucun enfant n'a été trouvé, vérifier s'il y a des 'items'
        if not links_html and "items" in nav_block and isinstance(nav_block["items"], list):
            for item in nav_block["items"]:
                link_html = generate_item_html(item)
                if link_html:
                    links_html += link_html
        
        # If no links found, use default link
        if not links_html:
            links_html = "<a href='/'>Home</a>"
        
        # Construct final HTML
        return f"<nav{attrs_str}>{links_html}</nav>"
    
    except Exception as e:
        frappe.log_error("Error generating nav HTML", str(e))
        return "<nav><a href='/'>Home</a></nav>"

def generate_link_html(link_block):
    """
    Generates HTML for a link block (a)
    """
    try:
        if not link_block:
            return ""
            
        # If not a link, ignore
        if link_block.get("element") != "a":
            return ""
            
        # Extract attributes
        href = "#"
        if "attributes" in link_block and isinstance(link_block["attributes"], dict):
            href = link_block["attributes"].get("href", "#")
        
        # Extract text
        text = ""
        if "innerHTML" in link_block:
            text = link_block["innerHTML"]
        
        # If no text and children, use first child as text
        if not text and "children" in link_block and link_block["children"]:
            first_child = link_block["children"][0]
            if "innerHTML" in first_child:
                text = first_child["innerHTML"]
        
        # If still no text, use URL as text
        if not text:
            text = href
            
        # Generate HTML
        return f"<a href=\"{href}\">{text}</a>"
    
    except Exception as e:
        return ""

def generate_item_html(item):
    """
    Generates HTML for a menu item in the format items[]
    """
    try:
        if not item:
            return ""
            
        href = item.get("href", "#")
        label = item.get("label", href)
        
        # Generate HTML
        return f"<a href=\"{href}\">{label}</a>"
    
    except Exception as e:
        return ""
