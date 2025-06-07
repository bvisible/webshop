import frappe

def execute():
	"""Add stock filter fields to Webshop Settings if they don't exist"""
	
	# Check if fields already exist
	webshop_settings = frappe.get_doc("Webshop Settings")
	
	# Set default values for new fields if they don't exist
	if not hasattr(webshop_settings, 'enable_stock_filter'):
		frappe.db.set_value("Webshop Settings", None, "enable_stock_filter", 0)
		
	if not hasattr(webshop_settings, 'stock_filter_default_checked'):
		frappe.db.set_value("Webshop Settings", None, "stock_filter_default_checked", 1)
		
	frappe.db.commit()
	print("Added stock filter fields to Webshop Settings")