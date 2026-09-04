#//// Neoffice — added file (no upstream equivalent). Jinja helper giving the wishlist
#//// count to the Builder-built header (da044ea692, 2025-03-13).
import frappe
from frappe import _

def get_wishlist_data():
    """
    Get the number of items in the user's wishlist.
    Returns a dictionary with the count of wishlist items.
    """
    wishlist_items_count = 0
    
    # Check if the user is logged in
    if frappe.session.user != "Guest":
        # Check if the wishlist exists for this user
        if frappe.db.exists("Wishlist", frappe.session.user):
            # Count the number of items in the wishlist
            wishlist_items_count = frappe.db.count(
                "Wishlist Item", 
                {"parent": frappe.session.user}
            )
    
    return {
        "wishlist_items_count": wishlist_items_count
    }
