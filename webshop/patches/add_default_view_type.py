import frappe

def execute():
    """Adds the default_view_type field to Webshop settings"""
    frappe.reload_doc("webshop", "doctype", "webshop_settings")
    
    # Set default value for existing installations
    if frappe.db.exists("Webshop Settings"):
        frappe.db.set_value("Webshop Settings", "Webshop Settings", "default_view_type", "Grid")
