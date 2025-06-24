import frappe
from frappe import _


@frappe.whitelist()
def update_all_website_items_warehouse(warehouse_name):
    """
    Update website_warehouse for all Website Items to the specified warehouse.
    
    Args:
        warehouse_name (str): Name of the warehouse to set for all website items
        
    Returns:
        dict: Result with count of updated items and any errors
    """
    if not warehouse_name:
        frappe.throw(_("Warehouse name is required"))
    
    # Validate warehouse exists
    if not frappe.db.exists("Warehouse", warehouse_name):
        frappe.throw(_("Warehouse {0} does not exist").format(warehouse_name))
    
    updated_count = 0
    errors = []
    
    # Get all website items
    website_items = frappe.get_all("Website Item", fields=["name", "item_code", "website_warehouse"])
    
    total_items = len(website_items)
    
    for item in website_items:
        try:
            # Only update if different
            if item.website_warehouse != warehouse_name:
                frappe.db.set_value(
                    "Website Item", 
                    item.name, 
                    "website_warehouse", 
                    warehouse_name
                )
                updated_count += 1
                
                # Commit every 100 records to avoid long transactions
                if updated_count % 100 == 0:
                    frappe.db.commit()
                    print(f"Updated {updated_count}/{total_items} website items...")
                    
        except Exception as e:
            errors.append({
                "website_item": item.name,
                "item_code": item.item_code,
                "error": str(e)
            })
    
    # Final commit
    frappe.db.commit()
    
    # Clear cache for all updated items
    frappe.clear_cache()
    
    result = {
        "total_items": total_items,
        "updated_count": updated_count,
        "skipped_count": total_items - updated_count - len(errors),
        "error_count": len(errors),
        "errors": errors[:10] if errors else []  # Limit errors shown to first 10
    }
    
    print(f"\nWarehouse Update Complete:")
    print(f"Total Website Items: {total_items}")
    print(f"Updated: {updated_count}")
    print(f"Skipped (already had this warehouse): {result['skipped_count']}")
    print(f"Errors: {len(errors)}")
    
    return result


@frappe.whitelist()
def update_website_items_warehouse_by_item_group(warehouse_name, item_group=None):
    """
    Update website_warehouse for Website Items filtered by item group.
    
    Args:
        warehouse_name (str): Name of the warehouse to set
        item_group (str, optional): Item group to filter by
        
    Returns:
        dict: Result with count of updated items and any errors
    """
    if not warehouse_name:
        frappe.throw(_("Warehouse name is required"))
    
    # Validate warehouse exists
    if not frappe.db.exists("Warehouse", warehouse_name):
        frappe.throw(_("Warehouse {0} does not exist").format(warehouse_name))
    
    filters = {}
    if item_group:
        filters["item_group"] = item_group
    
    updated_count = 0
    errors = []
    
    # Get filtered website items
    website_items = frappe.get_all(
        "Website Item", 
        filters=filters,
        fields=["name", "item_code", "website_warehouse", "item_group"]
    )
    
    total_items = len(website_items)
    
    for item in website_items:
        try:
            if item.website_warehouse != warehouse_name:
                frappe.db.set_value(
                    "Website Item", 
                    item.name, 
                    "website_warehouse", 
                    warehouse_name
                )
                updated_count += 1
                
                if updated_count % 100 == 0:
                    frappe.db.commit()
                    print(f"Updated {updated_count}/{total_items} website items...")
                    
        except Exception as e:
            errors.append({
                "website_item": item.name,
                "item_code": item.item_code,
                "error": str(e)
            })
    
    frappe.db.commit()
    frappe.clear_cache()
    
    result = {
        "item_group": item_group or "All",
        "total_items": total_items,
        "updated_count": updated_count,
        "skipped_count": total_items - updated_count - len(errors),
        "error_count": len(errors),
        "errors": errors[:10] if errors else []
    }
    
    print(f"\nWarehouse Update Complete for Item Group '{item_group or 'All'}':")
    print(f"Total Website Items: {total_items}")
    print(f"Updated: {updated_count}")
    print(f"Skipped: {result['skipped_count']}")
    print(f"Errors: {len(errors)}")
    
    return result


def get_website_items_by_warehouse(warehouse_name=None):
    """
    Get count of website items grouped by warehouse.
    
    Args:
        warehouse_name (str, optional): Filter by specific warehouse
        
    Returns:
        list: List of warehouses with item counts
    """
    filters = {}
    if warehouse_name:
        filters["website_warehouse"] = warehouse_name
    
    result = frappe.db.sql("""
        SELECT 
            website_warehouse,
            COUNT(*) as item_count
        FROM `tabWebsite Item`
        WHERE website_warehouse IS NOT NULL
        {0}
        GROUP BY website_warehouse
        ORDER BY item_count DESC
    """.format("AND website_warehouse = %(warehouse)s" if warehouse_name else ""),
    {"warehouse": warehouse_name} if warehouse_name else {},
    as_dict=True)
    
    return result