import frappe
from frappe import _
from datetime import datetime, timedelta

@frappe.whitelist()
def calculate_frequently_bought_together():
    """
    Calculate frequently bought together products based on sales invoice data
    from the last 6 months
    """
    try:
        # Clear existing data
        frappe.db.sql("DELETE FROM `tabFrequently Bought Together`")
        
        # Get all item combinations from sales invoices in the last 6 months
        six_months_ago = datetime.now() - timedelta(days=180)
        
        query = """
            SELECT 
                si1.item_code as item1,
                si2.item_code as item2,
                COUNT(*) as frequency
            FROM `tabSales Invoice Item` si1
            INNER JOIN `tabSales Invoice Item` si2 
                ON si1.parent = si2.parent 
                AND si1.item_code < si2.item_code
            INNER JOIN `tabSales Invoice` si 
                ON si1.parent = si.name
            -- Ensure both items exist in Website Item
            INNER JOIN `tabWebsite Item` wi1 ON si1.item_code = wi1.item_code
            INNER JOIN `tabWebsite Item` wi2 ON si2.item_code = wi2.item_code
            WHERE 
                si.docstatus = 1
                AND si.posting_date >= %s
                AND wi1.published = 1
                AND wi2.published = 1
            GROUP BY si1.item_code, si2.item_code
            HAVING frequency >= 2
            ORDER BY frequency DESC
        """
        
        results = frappe.db.sql(query, [six_months_ago], as_dict=True)
        
        # Insert results into Frequently Bought Together table
        for result in results:
            # Create entry for item1 -> item2
            frappe.get_doc({
                "doctype": "Frequently Bought Together",
                "item_code": result.item1,
                "related_item_code": result.item2,
                "frequency": result.frequency,
                "last_calculated": datetime.now()
            }).insert(ignore_permissions=True)
            
            # Create entry for item2 -> item1 (bidirectional)
            frappe.get_doc({
                "doctype": "Frequently Bought Together",
                "item_code": result.item2,
                "related_item_code": result.item1,
                "frequency": result.frequency,
                "last_calculated": datetime.now()
            }).insert(ignore_permissions=True)
        
        frappe.db.commit()
        
        # Count total associations created
        count = frappe.db.count("Frequently Bought Together")
        
        return {
            "success": True,
            "message": _("Successfully calculated {0} product associations").format(count // 2)
        }
        
    except Exception as e:
        frappe.log_error(f"Error calculating frequently bought together: {str(e)}")
        frappe.db.rollback()
        return {
            "success": False,
            "message": _("Error calculating frequently bought together: {0}").format(str(e))
        }

def get_frequently_bought_together(item_code, limit=4):
    """
    Get frequently bought together products for a given item
    """
    if not item_code:
        return []
    
    # Get related items from the pre-calculated table
    related_items = frappe.db.sql("""
        SELECT 
            wi.item_code,
            fbt.frequency,
            wi.web_item_name,
            wi.route,
            wi.thumbnail,
            wi.website_image,
            wi.variant_of
        FROM `tabFrequently Bought Together` fbt
        INNER JOIN `tabWebsite Item` wi ON fbt.related_item_code = wi.item_code
        WHERE 
            fbt.item_code = %s
            AND wi.published = 1
        ORDER BY fbt.frequency DESC
        LIMIT %s
    """, (item_code, limit), as_dict=True)
    
    # Get prices for the items
    if related_items:
        from erpnext.utilities.product import get_price
        from webshop.webshop.shopping_cart.cart import _set_price_list
        
        settings = frappe.get_cached_doc("Webshop Settings")
        selling_price_list = settings.price_list
        
        for item in related_items:
            price_obj = get_price(
                item.item_code,
                selling_price_list,
                settings.default_customer_group,
                settings.company,
                warehouse=item.get("website_warehouse")
            )
            if price_obj:
                from webshop.webshop.utils.utils import format_currency_value
                item.price = price_obj.get("price_list_rate") or price_obj.get("rate")
                item.currency = price_obj.get("currency")
                item.formatted_price = format_currency_value(
                    item.price, 
                    currency=item.currency
                ) if item.get("price") else None
    
    return related_items