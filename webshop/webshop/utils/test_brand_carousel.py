import frappe
from webshop.webshop.utils.brand_carousel_helper import get_brands_with_product_count

@frappe.whitelist()
def test_brand_carousel():
    """Test function to debug brand carousel"""
    try:
        # Test without cache
        brands = get_brands_with_product_count(
            limit=5,
            sort_by="product_count",
            use_cache=False,
            debug=True
        )
        
        return {
            "success": True,
            "count": len(brands),
            "brands": brands,
            "message": f"Found {len(brands)} brands"
        }
    except Exception as e:
        frappe.log_error(f"Test brand carousel error: {str(e)}", "Brand Carousel Test")
        return {
            "success": False,
            "error": str(e),
            "message": "Error loading brands"
        }

@frappe.whitelist()
def get_simple_brands():
    """Get brands using simple query for testing"""
    try:
        # Simple query to test
        brands = frappe.db.sql("""
            SELECT 
                name,
                brand,
                image,
                description
            FROM `tabBrand`
            LIMIT 10
        """, as_dict=True)
        
        return {
            "success": True,
            "count": len(brands),
            "brands": brands
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }