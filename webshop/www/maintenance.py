# //// Neoffice — added file (no upstream equivalent). Context of the maintenance page;
# //// it is reached through MaintenancePageRenderer, not by its route (deb34ad632,
# //// 2025-06-19).
import frappe

no_cache = 1

def get_context(context):
	# This page should not be accessed directly
	# It's only rendered by the MaintenancePageRenderer
	
	# Get maintenance context if available
	from webshop.webshop.maintenance import get_maintenance_context
	maintenance_context = get_maintenance_context()
	
	# Update page context
	context.update(maintenance_context)
	
	# Ensure proper headers
	context.no_cache = 1
	context.no_breadcrumbs = True
	context.base_template_path = 'frappe/templates/web.html'
	
	return context