# //// Neoffice — added file (no upstream equivalent). Rebuilds Website Item routes in
# //// bulk after a rename or an item-group move. Upstream computes a route once, at
# //// creation, and leaves stale URLs behind (3c1e847e26, 2025-06-24).
import frappe
from frappe import _
from frappe.utils import cstr
from frappe.website.utils import cleanup_page_name


@frappe.whitelist()
def regenerate_all_website_item_routes():
    """
    Regenerate routes for all Website Items.
    This will recalculate the route based on the current web_item_name and item_group.
    
    Returns:
        dict: Result with count of updated items and any errors
    """
    updated_count = 0
    errors = []
    unchanged_count = 0
    
    # Get all website items
    website_items = frappe.get_all(
        "Website Item", 
        fields=["name", "web_item_name", "item_group", "route", "item_code"]
    )
    
    total_items = len(website_items)
    print(f"Processing {total_items} website items...")
    
    for web_item in website_items:
        try:
            # Generate new route
            new_route = generate_route_for_website_item(
                web_item.web_item_name, 
                web_item.item_group,
                web_item.name
            )
            
            # Check if route needs updating
            if new_route != web_item.route:
                # Update the route
                frappe.db.set_value(
                    "Website Item",
                    web_item.name,
                    "route",
                    new_route
                )
                updated_count += 1
                
                # Commit every 100 records
                if updated_count % 100 == 0:
                    frappe.db.commit()
                    print(f"Updated {updated_count} routes so far...")
            else:
                unchanged_count += 1
                
        except Exception as e:
            errors.append({
                "website_item": web_item.name,
                "item_code": web_item.item_code,
                "error": str(e)
            })
    
    # Final commit
    frappe.db.commit()
    
    # Clear cache
    frappe.clear_cache()
    
    result = {
        "total_items": total_items,
        "updated_count": updated_count,
        "unchanged_count": unchanged_count,
        "error_count": len(errors),
        "errors": errors[:10] if errors else []  # Limit errors shown to first 10
    }
    
    print(f"\nRoute Regeneration Complete:")
    print(f"Total Website Items: {total_items}")
    print(f"Updated: {updated_count}")
    print(f"Unchanged: {unchanged_count}")
    print(f"Errors: {len(errors)}")
    
    return result


def generate_route_for_website_item(web_item_name, item_group, website_item_name):
    """
    Generate route for a website item following the same logic as the original system.
    
    Args:
        web_item_name: The name of the website item
        item_group: The item group
        website_item_name: The Website Item document name (for uniqueness)
    
    Returns:
        str: The generated route
    """
    # Get item group route
    item_group_route = get_item_group_route(item_group)
    
    # Clean the web item name for URL
    page_name = cleanup_page_name(web_item_name)
    
    # Build the route
    if item_group_route:
        route = f"{item_group_route}/{page_name}"
    else:
        route = f"products/{page_name}"
    
    # Ensure uniqueness by checking if route exists for other items
    existing = frappe.db.get_value(
        "Website Item",
        {"route": route, "name": ["!=", website_item_name]},
        "name"
    )
    
    if existing:
        # Add a suffix to make it unique
        # Use last 5 characters of name as suffix
        suffix = website_item_name.split("-")[-1]
        route = f"{route}-{suffix.lower()}"
    
    return route


def get_item_group_route(item_group):
    """
    Get the route for an item group, traversing up the hierarchy if needed.
    
    Args:
        item_group: The item group name
        
    Returns:
        str: The item group route or None
    """
    if not item_group:
        return None
    
    # Check if the item group has a route
    route = frappe.db.get_value("Item Group", item_group, "route")
    
    if route:
        return route
    
    # If no route, try to build from parent hierarchy
    parent_groups = get_parent_item_groups(item_group)
    if parent_groups:
        # Build route from hierarchy
        routes = []
        for group in reversed(parent_groups):
            group_route = frappe.db.get_value("Item Group", group, "route")
            if group_route:
                # Extract last part of route
                routes.append(group_route.split("/")[-1])
        
        if routes:
            return "/".join(routes)
    
    # Fallback: use cleaned item group name
    return cleanup_page_name(item_group)


def get_parent_item_groups(item_group):
    """
    Get parent item groups hierarchy.
    
    Args:
        item_group: The item group name
        
    Returns:
        list: List of parent item groups from parent to child
    """
    parents = []
    current_group = item_group
    
    while current_group:
        parent = frappe.db.get_value("Item Group", current_group, "parent_item_group")
        if parent and parent != "All Item Groups":
            parents.append(parent)
            current_group = parent
        else:
            break
    
    return parents


@frappe.whitelist()
def regenerate_routes_for_item_group(item_group):
    """
    Regenerate routes for all Website Items in a specific item group.
    
    Args:
        item_group: The item group to regenerate routes for
        
    Returns:
        dict: Result with count of updated items
    """
    updated_count = 0
    errors = []
    
    # Get all website items in this group
    website_items = frappe.get_all(
        "Website Item",
        filters={"item_group": item_group},
        fields=["name", "web_item_name", "route", "item_code"]
    )
    
    total_items = len(website_items)
    print(f"Processing {total_items} website items in group {item_group}...")
    
    for web_item in website_items:
        try:
            # Generate new route
            new_route = generate_route_for_website_item(
                web_item.web_item_name,
                item_group,
                web_item.name
            )
            
            # Update if different
            if new_route != web_item.route:
                frappe.db.set_value(
                    "Website Item",
                    web_item.name,
                    "route",
                    new_route
                )
                updated_count += 1
                
        except Exception as e:
            errors.append({
                "website_item": web_item.name,
                "item_code": web_item.item_code,
                "error": str(e)
            })
    
    frappe.db.commit()
    frappe.clear_cache()
    
    print(f"\nUpdated {updated_count} routes in item group {item_group}")
    
    return {
        "item_group": item_group,
        "total_items": total_items,
        "updated_count": updated_count,
        "errors": errors
    }


@frappe.whitelist()
def check_duplicate_routes():
    """
    Check for any duplicate routes in Website Items.
    
    Returns:
        dict: Dictionary of duplicate routes and the items using them
    """
    duplicates = frappe.db.sql("""
        SELECT 
            route,
            GROUP_CONCAT(name SEPARATOR ', ') as website_items,
            GROUP_CONCAT(item_code SEPARATOR ', ') as item_codes,
            COUNT(*) as count
        FROM `tabWebsite Item`
        WHERE route IS NOT NULL AND route != ''
        GROUP BY route
        HAVING COUNT(*) > 1
        ORDER BY count DESC
    """, as_dict=True)
    
    print(f"\nFound {len(duplicates)} duplicate routes")
    
    for dup in duplicates[:10]:  # Show first 10
        print(f"\nRoute: {dup.route}")
        print(f"Used by {dup.count} items: {dup.website_items}")
    
    return {
        "total_duplicates": len(duplicates),
        "duplicates": duplicates[:20]  # Return first 20
    }