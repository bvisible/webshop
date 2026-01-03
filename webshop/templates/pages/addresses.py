import frappe
from frappe import _
from webshop.webshop.shopping_cart.cart import get_party, get_address_docs


def get_context(context):
	"""Context for the addresses management page"""
	context.no_cache = 1
	context.show_sidebar = True

	# Check if user is logged in
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/addresses"
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


@frappe.whitelist()
def delete_address(address_name):
	"""Delete an address if it belongs to the current user's customer"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Please login to continue"))

	party = get_party()
	if not party:
		frappe.throw(_("No customer account found"))

	# Check if address belongs to this customer
	address = frappe.get_doc("Address", address_name)
	is_linked = False
	for link in address.links:
		if link.link_doctype == "Customer" and link.link_name == party.name:
			is_linked = True
			break

	if not is_linked:
		frappe.throw(_("Address not found or access denied"))

	# Check if address is used in any pending quotations
	quotations = frappe.get_all(
		"Quotation",
		filters={
			"party_name": party.name,
			"docstatus": 0,
			"customer_address": address_name
		}
	)
	if quotations:
		# Clear address from quotations first
		for q in quotations:
			frappe.db.set_value("Quotation", q.name, "customer_address", None)

	quotations_shipping = frappe.get_all(
		"Quotation",
		filters={
			"party_name": party.name,
			"docstatus": 0,
			"shipping_address_name": address_name
		}
	)
	if quotations_shipping:
		for q in quotations_shipping:
			frappe.db.set_value("Quotation", q.name, "shipping_address_name", None)

	# Delete the address
	frappe.delete_doc("Address", address_name)
	frappe.db.commit()

	return {"success": True, "message": _("Address deleted successfully")}


@frappe.whitelist()
def get_address(address_name):
	"""Get address details for editing"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Please login to continue"))

	party = get_party()
	if not party:
		frappe.throw(_("No customer account found"))

	# Check if address belongs to this customer
	address = frappe.get_doc("Address", address_name)
	is_linked = False
	for link in address.links:
		if link.link_doctype == "Customer" and link.link_name == party.name:
			is_linked = True
			break

	if not is_linked:
		frappe.throw(_("Address not found or access denied"))

	return {
		"name": address.name,
		"address_title": address.address_title,
		"address_line1": address.address_line1,
		"address_line2": address.address_line2,
		"city": address.city,
		"state": address.state,
		"country": address.country,
		"pincode": address.pincode,
		"phone": address.phone,
		"email_id": address.email_id,
		"is_primary_address": address.is_primary_address,
		"is_shipping_address": address.is_shipping_address
	}


@frappe.whitelist()
def update_address(address_name, address_data):
	"""Update an existing address"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Please login to continue"))

	party = get_party()
	if not party:
		frappe.throw(_("No customer account found"))

	# Parse address data if string
	if isinstance(address_data, str):
		address_data = frappe.parse_json(address_data)

	# Check if address belongs to this customer
	address = frappe.get_doc("Address", address_name)
	is_linked = False
	for link in address.links:
		if link.link_doctype == "Customer" and link.link_name == party.name:
			is_linked = True
			break

	if not is_linked:
		frappe.throw(_("Address not found or access denied"))

	# Update address fields
	address.address_title = address_data.get("address_title")
	address.address_line1 = address_data.get("address_line1")
	address.address_line2 = address_data.get("address_line2")
	address.city = address_data.get("city")
	address.state = address_data.get("state")
	address.country = address_data.get("country")
	address.pincode = address_data.get("pincode")
	address.phone = address_data.get("phone")
	address.email_id = address_data.get("email_id")
	address.is_primary_address = address_data.get("is_primary_address", 0)
	address.is_shipping_address = address_data.get("is_shipping_address", 0)

	address.save()

	# Update customer's primary address if needed
	if address.is_primary_address:
		from frappe.contacts.doctype.address.address import get_address_display
		customer = frappe.get_doc("Customer", party.name)
		customer.customer_primary_address = address.name
		customer.primary_address = get_address_display(address.name)
		customer.save(ignore_permissions=True)

	frappe.db.commit()

	return {"success": True, "message": _("Address updated successfully")}
