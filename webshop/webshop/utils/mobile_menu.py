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
            if nav_html and not nav_html.startswith("<nav><a href='/'></a></nav>"):
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
            "nav_content": "<nav><a href='/'>Home</a></nav>",
            "success": True,
            "method": "fallback",
            "message": _("Navigation fallback generated")
        }
        
    except Exception as e:
        frappe.log_error("Error extracting navigation", e)
        return {
            "nav_content": "<nav><a href='/'>Home</a></nav>",
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
        frappe.log_error("Error finding navbar component", e)
        return None

def extract_nav_from_component(component):
    """
    Extracts only the nav element from the component's JSON block
    and generates minimal HTML
    """
    try:
        # Check if component is valid
        if not component:
            return "<nav><a href='/'>Home</a></nav>"
            
        # Access block content based on type
        block_content = None
        if isinstance(component, dict):
            block_content = component.get('block')
        else:
            block_content = getattr(component, 'block', None)
            
        if not block_content:
            return "<nav><a href='/'>Home</a></nav>"
        
        # Parse the JSON block
        block_data = json.loads(block_content)
        
        # Recursively find the nav block
        nav_block = find_nav_block(block_data)
        
        if not nav_block:
            return "<nav><a href='/'>Home</a></nav>"
        
        # Generate minimal HTML for this block
        nav_html = generate_nav_html(nav_block)
        
        return nav_html
    except Exception as e:
        frappe.log_error("Error extracting nav from component", e)
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

def find_all_links(block, depth=0, max_depth=10):
    """
    v2.10.5: Recursively find ALL link blocks (<a>) at ANY depth level.
    Ignores webshop shortcodes ({% include ... %}).

    Args:
        block: Current block to process
        depth: Current recursion depth
        max_depth: Maximum recursion depth (protection against infinite loops)

    Returns:
        list: All link blocks found
    """
    links = []

    # Protection against infinite loops
    if depth > max_depth or not block or not isinstance(block, dict):
        return links

    # If it's a direct link, add it
    if block.get("element") == "a":
        # Check if it has valid content (href or innerHTML)
        href = block.get("attributes", {}).get("href")
        innerHTML = block.get("innerHTML")

        # Only add links with href or content
        if href or innerHTML:
            links.append(block)

    # Recursively search ALL children
    if "children" in block and isinstance(block["children"], list):
        for child in block["children"]:
            if isinstance(child, dict):
                # Ignore webshop shortcodes ({% include "webshop/..." %})
                child_html = str(child.get("innerHTML", ""))
                if "{% include" in child_html and "webshop" in child_html:
                    continue

                # Recursion
                links.extend(find_all_links(child, depth + 1, max_depth))

    return links

def generate_nav_html(nav_block):
    """
    v2.10.5: Generates minimal HTML for a nav block with recursive link extraction
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

        # v2.10.5: Use recursive extraction to find ALL links
        all_links = find_all_links(nav_block)

        # Generate HTML for each link
        links_html = ""
        for link_block in all_links:
            link_html = generate_link_html(link_block)
            if link_html:
                links_html += link_html

        # Fallback: If no links found recursively, check 'items' array
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
    v2.10.5: Generates HTML for a link block (a) with improved text extraction
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

        # v2.10.5: Extract text with better handling of innerHTML
        text = ""

        # Try innerHTML first
        if "innerHTML" in link_block and link_block["innerHTML"]:
            innerHTML_value = link_block["innerHTML"]

            # Handle None case
            if innerHTML_value is None:
                innerHTML_value = ""

            # Convert to string and clean
            text = str(innerHTML_value).strip()

            # Remove HTML tags (like <p></p>) if present
            import re
            text = re.sub(r'<[^>]+>', '', text).strip()

        # If no text and children, recursively extract text from children
        if not text and "children" in link_block and link_block["children"]:
            for child in link_block["children"]:
                if isinstance(child, dict):
                    # Skip if child is an image (logo links)
                    if child.get("element") == "img":
                        continue

                    if "innerHTML" in child:
                        child_text = str(child.get("innerHTML", "")).strip()
                        child_text = re.sub(r'<[^>]+>', '', child_text).strip()
                        if child_text:
                            text = child_text
                            break

        # v2.10.5: Skip links without valid text (logo links with only images)
        # Don't use href as text fallback - just skip the link entirely
        if not text:
            return ""

        # Generate HTML (only if we have valid text and href)
        if text and text != "#" and href and href != "#":
            return f"<a href=\"{href}\">{text}</a>"

        return ""

    except Exception as e:
        frappe.log_error("Error generating link HTML", str(e))
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
