#//// Neoffice — added file (no upstream equivalent). Hides the Builder-rendered
#//// header and footer on /login while the site is closed, by injecting CSS into the
#//// page context — the login page is served by Frappe and does not go through our
#//// page renderer (deb34ad632, 2025-06-19).
import frappe
from frappe.utils import cint


def inject_maintenance_css(context):
	"""Inject CSS to hide builder elements on login page during maintenance"""
	# Only inject on login page
	if getattr(frappe.local, 'request', None) and frappe.local.request.path != "/login":
		return
		
	# Check if maintenance mode is active
	maintenance_website = cint(frappe.db.get_single_value('Webshop Settings', 'maintenance_website'))
	maintenance_webshop = cint(frappe.db.get_single_value('Webshop Settings', 'maintenance_webshop'))
		
	# Only inject CSS if website maintenance is active
	if maintenance_website:		
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