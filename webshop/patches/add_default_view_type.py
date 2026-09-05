# //// Neoffice — added file (no upstream equivalent).
# //// Webshop Settings.default_view_type (Grid / List): our listing offers both views
# //// and remembers a shop-wide default (3bc2d836f1, 2025-02-11). Existing sites are
# //// set to "Grid", which is what upstream renders unconditionally.
import frappe

def execute():
    """Adds the default_view_type field to Webshop settings"""
    frappe.reload_doc("webshop", "doctype", "webshop_settings")
    
    # Set default value for existing installations
    if frappe.db.exists("Webshop Settings"):
        frappe.db.set_value("Webshop Settings", "Webshop Settings", "default_view_type", "Grid")
