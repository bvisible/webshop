import frappe
import re
import json
from frappe import _
from builder.builder.doctype.builder_page.builder_page import get_block_html, execute_script
from bs4 import BeautifulSoup

@frappe.whitelist(allow_guest=True)
def get_builder_component_by_route(route, use_cache=True):
    """
    Retrieves a Builder component from its route.
    
    This function first searches for a Builder page with the specified route,
    then extracts the ID of the component referenced in this page.
    Finally, it returns the component itself.
    
    Args:
        route (str): The route of the page that uses the component
        use_cache (bool): Use cache to speed up retrieval
        
    Returns:
        dict: The Builder component or None if not found
    """
    # Define cache key
    cache_key = None
    if use_cache:
        cache_key = f"builder_component_by_route:{route}"
        cached_result = frappe.cache().get_value(cache_key)
        if cached_result:
            return cached_result
    
    try:
        # Get the page by its route
        pages = frappe.get_all(
            "Builder Page",
            filters={
                "route": route,
                "published": 1
            },
            fields=["name", "blocks"],
            order_by="modified desc",
            limit=1
        )
        
        if not pages:
            return None
            
        page = pages[0]
        blocks = page.blocks
        
        if isinstance(blocks, str):
            blocks = json.loads(blocks)
            
        # Iterate through the blocks to find the component ID
        component_id = find_component_id(blocks)
        
        if not component_id:
            return None
            
        # Get the component
        components = frappe.get_all(
            "Builder Component",
            filters={
                "name": component_id
            },
            fields=["name", "block", "component_name"],
            limit=1
        )
        
        if not components:
            return None
            
        component = components[0]
        result = {
            "name": component.name,
            "component_name": component.component_name,
            "block": json.loads(component.block) if isinstance(component.block, str) else component.block
        }
        
        # Mettre en cache le résultat
        if use_cache and cache_key:
            frappe.cache().set_value(cache_key, result, expires_in_sec=300)  # 5 minutes
            
        return result
    except Exception as e:
        frappe.log_error("Error getting builder component by route", 
                        f"Error: {str(e)}\nTraceback: {frappe.get_traceback()}")
        return None
        
def find_component_id(blocks):
    """
    Recursively find the ID of the first extended component in the blocks.
    
    Args:
        blocks (list/dict): The blocks to analyze
        
    Returns:
        str: The ID of the component found or None
    """
    if not blocks:
        return None
        
    # If it's a single block
    if isinstance(blocks, dict):
        # Check if this block extends a component
        if blocks.get("extendedFromComponent"):
            return blocks["extendedFromComponent"]
            
        # Check children
        if blocks.get("children"):
            return find_component_id(blocks["children"])
            
        return None
        
    # If it's a list of blocks
    for block in blocks:
        # Check if this block extends a component
        if block.get("extendedFromComponent"):
            return block["extendedFromComponent"]
            
        # Check children
        if block.get("children"):
            component_id = find_component_id(block["children"])
            if component_id:
                return component_id
                
    return None

@frappe.whitelist(allow_guest=True)
def get_builder_page_content(route=None, page_name=None, content_only=False, skip_scripts=False, skip_styles=False, use_cache=True):
    """
    Render a Builder Page and return the HTML and CSS content with all global settings.
    
    Parameters:
        route (str, optional): Route of the page to render
        page_name (str, optional): Name of the page to render
        content_only (bool, optional): If True, only return HTML content without styles or scripts
        skip_scripts (bool, optional): If True, skip loading client scripts
        skip_styles (bool, optional): If True, skip loading client styles
        use_cache (bool, optional): If True, try to use cached version if available
    """
    
    # Define cache key if caching is enabled
    cache_key = None
    if use_cache:
        cache_params = f"{route}_{page_name}_{content_only}_{skip_scripts}_{skip_styles}"
        cache_key = f"builder_page_content:{cache_params}"
        cached_result = frappe.cache().get_value(cache_key)
        if cached_result:
            return cached_result
    
    try:
        # Get page_name from route if provided
        if route and not page_name:
            page_list = frappe.get_all(
                "Builder Page", 
                filters={
                    "route": route,
                    "published": 1  # Only get published pages
                },
                fields=["name"],
                order_by="modified desc",
                limit=1
            )
            
            if not page_list:
                result = {
                    "content": f"<div>Error: Page not found for route: {route}</div>",
                    "success": False,
                    "message": f"Page not found for route: {route}"
                }
                if not content_only:
                    result.update({
                        "style": "",
                        "global_style": "",
                        "global_script": "",
                        "client_scripts": [],
                        "client_styles": [],
                        "fonts": {}
                    })
                return result
                
            page_name = page_list[0].name
            
        # If no route or page_name provided
        if not page_name:
            result = {
                "content": "<div>Error: No page identifier provided</div>",
                "success": False,
                "message": "No page identifier provided"
            }
            if not content_only:
                result.update({
                    "style": "",
                    "global_style": "",
                    "global_script": "",
                    "client_scripts": [],
                    "client_styles": [],
                    "fonts": {}
                })
            return result
        
        # Try to get from cache by page name if not already checked by route
        if use_cache and not route:
            cache_key = f"builder_page_content:{page_name}_{content_only}_{skip_scripts}_{skip_styles}"
            cached_result = frappe.cache().get_value(cache_key)
            if cached_result:
                return cached_result
        
        # Get the page document
        page = frappe.get_cached_doc("Builder Page", page_name)
        
        # Prepare the result dictionary with content
        result = {"success": True}
        
        # Process blocks to generate HTML content
        blocks = page.blocks
        if isinstance(blocks, str):
            blocks = json.loads(blocks)
        
        # Get raw HTML and style
        content, style, fonts = get_block_html(blocks)
        
        # Process page data and context only if needed
        # Skip render_template if content has {% include %} - those should be rendered by parent template
        has_jinja = "{% " in content or "{{ " in content
        has_includes = "{% include" in content

        if has_jinja and not has_includes:
            # Only render if there's Jinja but NO includes (includes must be rendered by parent)
            # Get page data
            page_data = {}
            if page.page_data_script:
                _locals = dict(data=frappe._dict())
                execute_script(page.page_data_script, _locals, page.name)
                page_data = _locals["data"]

            # Create context and render template
            context = frappe._dict()
            context.update(page_data)

            # Get HTML and style with context
            from frappe.utils.jinja import render_template
            content = render_template(content, context)

            if not content_only:
                result["page_data"] = page_data
        elif has_jinja and has_includes:
            # Has includes - pass page_data but don't render (parent template will handle includes)
            page_data = {}
            if page.page_data_script:
                _locals = dict(data=frappe._dict())
                execute_script(page.page_data_script, _locals, page.name)
                page_data = _locals["data"]
            if not content_only:
                result["page_data"] = page_data
        
        # Post-process content
        content = content.replace(
            "{% include 'templates/generators/webpage_scripts.html' %}", 
            "<!-- webpage_scripts.html omis intentionnellement -->"
        )
        
        # Replace body tag with div while preserving attributes
        content = re.sub(r'<body([^>]*)>', r'<div\1 class="builder-body-container">', content)
        content = re.sub(r'</body>', '</div>', content)
        
        # Add content to result
        result["content"] = content
        
        # If only content is requested, return early
        if content_only:
            # Cache and return
            if use_cache and cache_key:
                frappe.cache().set_value(cache_key, result, expires_in_sec=300)  # Cache for 5 minutes
            return result
        
        # Add style to result
        result["style"] = style
        result["fonts"] = fonts
        
        # Process client scripts and styles only if needed
        if not skip_scripts or not skip_styles:
            client_scripts = []
            client_styles = []
            
            for script in page.get("client_scripts", []):
                script_doc = frappe.get_cached_doc("Builder Client Script", script.builder_script)
                
                if not skip_scripts and script_doc.script_type == "JavaScript":
                    client_scripts.append({
                        "name": script_doc.name,
                        "url": script_doc.public_url,
                        "content": script_doc.script
                    })
                elif not skip_styles and script_doc.script_type != "JavaScript":
                    client_styles.append({
                        "name": script_doc.name,
                        "url": script_doc.public_url,
                        "content": script_doc.script
                    })
            
            result["client_scripts"] = client_scripts
            result["client_styles"] = client_styles
        else:
            result["client_scripts"] = []
            result["client_styles"] = []
        
        # Get global styles and scripts only if needed
        if not skip_styles or not skip_scripts:
            builder_settings = frappe.get_cached_doc("Builder Settings", "Builder Settings")
            
            if not skip_styles and builder_settings.style:
                result["global_style"] = builder_settings.style
            else:
                result["global_style"] = ""
            
            if not skip_scripts and builder_settings.script:
                result["global_script"] = builder_settings.script
            else:
                result["global_script"] = ""
        else:
            result["global_style"] = ""
            result["global_script"] = ""
        
        # Cache results if needed
        if use_cache and cache_key:
            frappe.cache().set_value(cache_key, result, expires_in_sec=300)  # Cache for 5 minutes
        
        return result
    except Exception as e:
        frappe.log_error("Error rendering Builder Page", e)
        return None