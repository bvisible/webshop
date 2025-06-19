import frappe
from frappe.utils import cint


def inject_maintenance_css(context):
	"""Inject CSS to hide builder elements on login page during maintenance"""
	# Only inject on login page
	if frappe.local.request and frappe.local.request.path != "/login":
		return
		
	frappe.log_error(f"Injecting CSS on login page", "Maintenance CSS Debug")
		
	# Check if maintenance mode is active
	maintenance_website = cint(frappe.db.get_single_value('Webshop Settings', 'maintenance_website'))
	maintenance_webshop = cint(frappe.db.get_single_value('Webshop Settings', 'maintenance_webshop'))
	
	frappe.log_error(f"Maintenance mode - Website: {maintenance_website}, Webshop: {maintenance_webshop}", "Maintenance CSS Debug")
	
	# Only inject CSS if website maintenance is active
	if maintenance_website:
		frappe.log_error(f"Adding CSS to hide builder elements", "Maintenance CSS Debug")
		
		# Add custom CSS to context
		if not hasattr(context, 'custom_css') or context.custom_css is None:
			context.custom_css = ""
			
		# Instead of custom_css, add to head_html which is more reliable
		if not hasattr(context, 'head_html') or context.head_html is None:
			context.head_html = ""
			
		context.head_html += """
		<style>
			/* Hide builder elements on login page during maintenance */
			.builder-body-container,
			[class*="builder-body-container"] {
				display: none !important;
				visibility: hidden !important;
				opacity: 0 !important;
				height: 0 !important;
				overflow: hidden !important;
			}
			
			.builder-header,
			.builder-footer,
			[class*="builder-header"],
			[class*="builder-footer"] {
				display: none !important;
			}
			
			/* Also hide specific builder elements that might appear */
			.builder-wrapper,
			.builder-section,
			.builder-block {
				display: none !important;
			}
		</style>
		"""
		
		frappe.log_error(f"CSS injected to head_html", "Maintenance CSS Debug")