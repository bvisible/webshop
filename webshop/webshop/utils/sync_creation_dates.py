# //// Neoffice — added file (no upstream equivalent). Copies the Item creation date
# //// onto its Website Item so "New arrivals" sorts on when the product existed, not on
# //// when it was published — a bulk publication otherwise makes the whole catalogue
# //// new on the same day (3c1e847e26, 2025-06-24).
import frappe
from frappe import _


@frappe.whitelist()
def sync_creation_dates_from_items():
    """
    Synchronize creation dates from Item to Website Item.
    This will update the creation date of Website Items to match their corresponding Item.
    
    Returns:
        dict: Result with count of updated items and any errors
    """
    updated_count = 0
    errors = []
    unchanged_count = 0
    
    # Get all website items with their linked item code
    website_items = frappe.db.sql("""
        SELECT 
            wi.name as website_item_name,
            wi.item_code,
            wi.creation as website_creation,
            i.creation as item_creation
        FROM `tabWebsite Item` wi
        INNER JOIN `tabItem` i ON wi.item_code = i.name
        WHERE wi.item_code IS NOT NULL AND wi.item_code != ''
    """, as_dict=True)
    
    total_items = len(website_items)
    print(f"Processing {total_items} website items...")
    
    for web_item in website_items:
        try:
            # Check if dates are different
            if web_item.item_creation != web_item.website_creation:
                # Update the creation date directly in database
                # Note: We need to use SQL because creation is a system field
                frappe.db.sql("""
                    UPDATE `tabWebsite Item`
                    SET creation = %s
                    WHERE name = %s
                """, (web_item.item_creation, web_item.website_item_name))
                
                updated_count += 1
                
                # Commit every 100 records
                if updated_count % 100 == 0:
                    frappe.db.commit()
                    print(f"Updated {updated_count} website items so far...")
            else:
                unchanged_count += 1
                
        except Exception as e:
            errors.append({
                "website_item": web_item.website_item_name,
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
    
    print(f"\nCreation Date Sync Complete:")
    print(f"Total Website Items: {total_items}")
    print(f"Updated: {updated_count}")
    print(f"Unchanged: {unchanged_count}")
    print(f"Errors: {len(errors)}")
    
    return result


@frappe.whitelist()
def preview_creation_date_changes(limit=20):
    """
    Preview which Website Items would have their creation dates changed.
    
    Args:
        limit: Number of items to preview (default 20)
        
    Returns:
        dict: Preview of changes that would be made
    """
    # Get website items with different creation dates
    different_dates = frappe.db.sql("""
        SELECT 
            wi.name as website_item_name,
            wi.item_code,
            wi.web_item_name,
            wi.creation as website_creation,
            i.creation as item_creation,
            TIMESTAMPDIFF(DAY, i.creation, wi.creation) as days_difference
        FROM `tabWebsite Item` wi
        INNER JOIN `tabItem` i ON wi.item_code = i.name
        WHERE wi.creation != i.creation
        ORDER BY ABS(TIMESTAMPDIFF(DAY, i.creation, wi.creation)) DESC
        LIMIT %s
    """, limit, as_dict=True)
    
    total_different = frappe.db.sql("""
        SELECT COUNT(*) as count
        FROM `tabWebsite Item` wi
        INNER JOIN `tabItem` i ON wi.item_code = i.name
        WHERE wi.creation != i.creation
    """)[0][0]
    
    print(f"\nFound {total_different} Website Items with different creation dates")
    print(f"\nShowing preview of {len(different_dates)} items:")
    
    for item in different_dates:
        print(f"\n{item.web_item_name} ({item.item_code}):")
        print(f"  Current Website Item date: {item.website_creation}")
        print(f"  Will change to Item date: {item.item_creation}")
        print(f"  Difference: {abs(item.days_difference)} days")
    
    return {
        "total_items_to_update": total_different,
        "preview": different_dates
    }


@frappe.whitelist()
def get_newest_products(limit=20):
    """
    Get the newest products based on Item creation date.
    
    Args:
        limit: Number of products to return
        
    Returns:
        list: List of newest products
    """
    products = frappe.db.sql("""
        SELECT 
            wi.name,
            wi.web_item_name,
            wi.item_code,
            wi.item_group,
            wi.brand,
            wi.creation as website_creation,
            i.creation as item_creation
        FROM `tabWebsite Item` wi
        INNER JOIN `tabItem` i ON wi.item_code = i.name
        WHERE wi.published = 1
        ORDER BY i.creation DESC
        LIMIT %s
    """, limit, as_dict=True)
    
    print(f"\nNewest {len(products)} products (by Item creation date):")
    for idx, product in enumerate(products, 1):
        print(f"{idx}. {product.web_item_name} - Created: {product.item_creation}")
    
    return products


@frappe.whitelist()
def update_specific_website_item_date(website_item_name):
    """
    Update creation date for a specific Website Item.
    
    Args:
        website_item_name: Name of the Website Item to update
        
    Returns:
        dict: Result of the update
    """
    # Get the website item and its linked item
    data = frappe.db.sql("""
        SELECT 
            wi.name as website_item_name,
            wi.item_code,
            wi.creation as website_creation,
            i.creation as item_creation
        FROM `tabWebsite Item` wi
        INNER JOIN `tabItem` i ON wi.item_code = i.name
        WHERE wi.name = %s
    """, website_item_name, as_dict=True)
    
    if not data:
        return {"error": "Website Item not found or has no linked Item"}
    
    item_data = data[0]
    
    if item_data.website_creation == item_data.item_creation:
        return {
            "message": "Creation dates are already synchronized",
            "website_creation": item_data.website_creation,
            "item_creation": item_data.item_creation
        }
    
    # Update the date
    frappe.db.sql("""
        UPDATE `tabWebsite Item`
        SET creation = %s
        WHERE name = %s
    """, (item_data.item_creation, website_item_name))
    
    frappe.db.commit()
    frappe.clear_cache()
    
    return {
        "message": "Creation date updated successfully",
        "website_item": website_item_name,
        "old_date": item_data.website_creation,
        "new_date": item_data.item_creation
    }