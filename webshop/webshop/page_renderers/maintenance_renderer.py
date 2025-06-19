import frappe
from frappe.website.page_renderers.base_renderer import BaseRenderer
from frappe.utils import cint, now_datetime
from frappe import _


class MaintenancePageRenderer(BaseRenderer):
	def __init__(self, path=None, http_status_code=None):
		super().__init__(path=path, http_status_code=http_status_code)
		self.http_status_code = 503  # Service Unavailable
		
	def can_render(self):
		"""Check if maintenance mode is active and should block this request"""
		
		if not self.is_maintenance_active():
			return False
			
		maintenance_mode = self.get_maintenance_mode()
		
		# Always allow login page
		if self.path in ['login', 'api/method/login', 'api/method/logout']:
			return False
			
		# Check if request is for API
		if self.path.startswith('api/'):
			# Allow auth endpoints
			if any(endpoint in self.path for endpoint in ['login', 'logout', 'auth']):
				return False
			# Block other API calls during maintenance
			frappe.throw(_("Service temporarily unavailable due to maintenance"), frappe.ServiceUnavailableError)
			
		# Check if user can bypass maintenance
		if self.can_user_bypass_maintenance():
			return False
			
		# Check which paths to block based on maintenance mode
		maintenance_mode = self.get_maintenance_mode()
		
		if maintenance_mode == "Webshop Only":
			# Block only webshop related paths
			webshop_paths = [
				'products', 'all-products', 'cart', 'checkout', 
				'orders', 'invoices', 'addresses', 'wishlist', 
				'gift-cards', 'product-search', 'shop-by-category'
			]
			return any(self.path.startswith(p) for p in webshop_paths)
			
		elif maintenance_mode == "Website and Webshop":
			# Block all paths except excluded ones
			excluded_paths = ['login', 'assets', 'files', 'private/files', 'api/method/login', 'api/method/logout']
			# Check exact match for login or prefix match for other paths
			if self.path == 'login' or any(self.path.startswith(p) for p in excluded_paths):
				return False
			return True
			
		return False
		
	def render(self):
		"""Render the maintenance page or redirect to login"""
		# Check if we should redirect to login instead of showing maintenance page
		redirect_to_login = cint(frappe.db.get_single_value('Webshop Settings', 'redirect_to_login'))
		
		if redirect_to_login:
			# Redirect to login page
			frappe.local.flags.redirect_location = "/login"
			raise frappe.Redirect
		
		# Otherwise, render the maintenance page
		from webshop.webshop.maintenance import get_maintenance_context
		
		context = get_maintenance_context()
		
		# Add additional context
		context.update({
			'http_status_code': self.http_status_code,
			'title': _('Under Maintenance'),
		})
		
		# Use the existing maintenance template
		html = frappe.render_template('webshop/www/maintenance.html', context)
		
		return self.build_response(html, http_status_code=self.http_status_code)
		
	def is_maintenance_active(self):
		"""Check if maintenance mode is currently active"""
		maintenance_website = cint(frappe.db.get_single_value('Webshop Settings', 'maintenance_website'))
		maintenance_webshop = cint(frappe.db.get_single_value('Webshop Settings', 'maintenance_webshop'))
		return maintenance_website or maintenance_webshop
		
	def get_maintenance_mode(self):
		"""Get current maintenance mode setting"""
		maintenance_website = cint(frappe.db.get_single_value('Webshop Settings', 'maintenance_website'))
		maintenance_webshop = cint(frappe.db.get_single_value('Webshop Settings', 'maintenance_webshop'))
		
		if maintenance_website and maintenance_webshop:
			return "Website and Webshop"
		elif maintenance_website:
			return "Website and Webshop"  # If website is on, everything is blocked
		elif maintenance_webshop:
			return "Webshop Only"
		else:
			return "Disabled"
		
	def can_user_bypass_maintenance(self):
		"""Check if current user can bypass maintenance mode"""
		if frappe.session.user == "Guest":
			return False
			
		# Check if system users are allowed during maintenance
		allow_system_users = cint(frappe.db.get_single_value(
			'Webshop Settings', 'allow_system_users_during_maintenance'
		))
		
		if allow_system_users:
			# Check if user has system manager or website manager role
			user_roles = frappe.get_roles(frappe.session.user)
			bypass_roles = ['System Manager', 'Website Manager', 'Administrator']
			return any(role in user_roles for role in bypass_roles)
			
		return False