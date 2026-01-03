import frappe
from frappe import _
from webshop.webshop.shopping_cart.cart import get_party, get_address_docs


def get_context(context):
	"""Context for the addresses management page"""
	context.no_cache = 1
	context.show_sidebar = True

	# Check if user is logged in
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/my_addresses"
		raise frappe.Redirect

	# Get current customer
	party = get_party()
	if not party:
		frappe.throw(_("No customer account found"))

	context.party = party

	# Get all addresses linked to this customer
	context.addresses = get_address_docs(party=party)

	# Get default country from system settings
	context.default_country = frappe.db.get_single_value("System Settings", "country") or "Switzerland"

	# Get all countries for the dropdown
	context.countries = frappe.get_all(
		"Country",
		fields=["name", "country_name"],
		order_by="country_name"
	)

	return context
