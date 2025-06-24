import frappe
from frappe import _


@frappe.whitelist()
def update_website_items_variant_of():
    """
    Update variant_of field for all Website Items that are variants.
    This will check the linked Item to see if it has a variant_of value
    and update the Website Item accordingly.
    
    Returns:
        dict: Result with count of updated items and any errors
    """
    updated_count = 0
    errors = []
    skipped_count = 0
    
    # Get all website items
    website_items = frappe.get_all(
        "Website Item", 
        fields=["name", "item_code", "variant_of", "has_variants"]
    )
    
    total_items = len(website_items)
    print(f"Processing {total_items} website items...")
    
    for web_item in website_items:
        try:
            # Skip if already has variant_of set or if it's a parent (has_variants=1)
            if web_item.variant_of or web_item.has_variants:
                skipped_count += 1
                continue
            
            # Get the linked Item document
            item = frappe.db.get_value(
                "Item", 
                web_item.item_code, 
                ["variant_of", "has_variants"],
                as_dict=True
            )
            
            if not item:
                errors.append({
                    "website_item": web_item.name,
                    "item_code": web_item.item_code,
                    "error": "Item not found"
                })
                continue
            
            # If the Item is a variant, update the Website Item
            if item.variant_of and not item.has_variants:
                frappe.db.set_value(
                    "Website Item",
                    web_item.name,
                    "variant_of",
                    item.variant_of
                )
                updated_count += 1
                
                # Commit every 100 records
                if updated_count % 100 == 0:
                    frappe.db.commit()
                    print(f"Updated {updated_count} website items so far...")
            else:
                skipped_count += 1
                
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
        "skipped_count": skipped_count,
        "error_count": len(errors),
        "errors": errors[:10] if errors else []  # Limit errors shown to first 10
    }
    
    print(f"\nVariant Update Complete:")
    print(f"Total Website Items: {total_items}")
    print(f"Updated: {updated_count}")
    print(f"Skipped: {skipped_count}")
    print(f"Errors: {len(errors)}")
    
    return result


@frappe.whitelist()
def fix_inconsistent_variants():
    """
    Fix Website Items where has_variants=0 but variant_of is empty,
    and the linked Item is actually a variant.
    
    Returns:
        dict: Result with count of fixed items
    """
    # Find Website Items that might need fixing
    potential_variants = frappe.db.sql("""
        SELECT 
            wi.name,
            wi.item_code,
            i.variant_of,
            i.has_variants as item_has_variants
        FROM `tabWebsite Item` wi
        INNER JOIN `tabItem` i ON wi.item_code = i.name
        WHERE wi.has_variants = 0 
        AND (wi.variant_of IS NULL OR wi.variant_of = '')
        AND i.variant_of IS NOT NULL 
        AND i.variant_of != ''
    """, as_dict=True)
    
    fixed_count = 0
    
    for item in potential_variants:
        try:
            frappe.db.set_value(
                "Website Item",
                item.name,
                "variant_of",
                item.variant_of
            )
            fixed_count += 1
            
            if fixed_count % 50 == 0:
                frappe.db.commit()
                print(f"Fixed {fixed_count} items...")
                
        except Exception as e:
            print(f"Error fixing {item.name}: {str(e)}")
    
    frappe.db.commit()
    frappe.clear_cache()
    
    print(f"\nFixed {fixed_count} Website Items with missing variant_of")
    
    return {
        "total_found": len(potential_variants),
        "fixed_count": fixed_count
    }


@frappe.whitelist()
def get_variant_statistics():
    """
    Get statistics about variants in Website Items
    
    Returns:
        dict: Statistics about variants
    """
    stats = {}
    
    # Total website items
    stats['total_website_items'] = frappe.db.count('Website Item')
    
    # Website items with has_variants=1 (parents)
    stats['parent_items'] = frappe.db.count('Website Item', {'has_variants': 1})
    
    # Website items with variant_of set (children)
    stats['variant_items'] = frappe.db.sql("""
        SELECT COUNT(*) as count 
        FROM `tabWebsite Item` 
        WHERE variant_of IS NOT NULL AND variant_of != ''
    """)[0][0]
    
    # Website items that might be variants but variant_of is not set
    stats['potential_missing_variants'] = frappe.db.sql("""
        SELECT COUNT(*) as count
        FROM `tabWebsite Item` wi
        INNER JOIN `tabItem` i ON wi.item_code = i.name
        WHERE wi.has_variants = 0 
        AND (wi.variant_of IS NULL OR wi.variant_of = '')
        AND i.variant_of IS NOT NULL 
        AND i.variant_of != ''
    """)[0][0]
    
    # Items with variants vs Website Items
    stats['items_with_variants'] = frappe.db.count('Item', {'has_variants': 1})
    stats['item_variants'] = frappe.db.sql("""
        SELECT COUNT(*) as count 
        FROM `tabItem` 
        WHERE variant_of IS NOT NULL AND variant_of != ''
    """)[0][0]
    
    return stats