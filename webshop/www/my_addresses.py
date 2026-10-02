# //// Neoffice — added file (no upstream equivalent). Context of the address book page:
# //// signs the visitor out to /login when anonymous, and refuses when the account has
# //// no customer (a807dc8a10, 2026-01-03).
import frappe
from frappe import _
from webshop.webshop.shopping_cart.cart import get_party, get_address_docs


def get_context(context):
	"""Context for the addresses management page"""
	context.body_class = "product-page"  # //// Neoffice — the shop's ground (webshop_ground.scss)
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

	# //// Neoffice — the form follows the envelope and the desk's Address form (maintenance#1032):
	# //// the name printed on documents, « to the attention of » and the delivery instructions are
	# //// fleet custom fields of the Address, offered only where the site has them; labels and
	# //// descriptions are the desk's own (the Address fields'), so both say the same thing.
	meta = frappe.get_meta("Address")
	context.has_field = {
		f: bool(meta.has_field(f))
		for f in ("company", "to_the_attention_of", "neo_delivery_instructions", "custom_house_number", "state")
	}
	context.field_label = {
		f: _(meta.get_field(f).label) for f in context.has_field if context.has_field[f] and meta.get_field(f).label
	}
	context.field_help = {
		f: _(meta.get_field(f).description)
		for f in context.has_field
		if context.has_field[f] and meta.get_field(f).description
	}
	# //// Neoffice — the page's script shows these: __() has no catalogue on this page, so its
	# //// strings stayed in English (« Add New Address »). They travel translated from here.
	context.texts = {
		"add": _("Add New Address"),
		"edit": _("Edit Address"),
		"loading": _("Loading..."),
		"saving": _("Saving..."),
		"deleting": _("Deleting..."),
		"confirm_delete": _("Are you sure you want to delete this address?"),
		"deleted": _("Address deleted successfully"),
		"updated": _("Address updated successfully"),
		"created": _("Address created successfully"),
		"need_title": _("Address Title is required"),
		"need_street": _("Address Line 1 is required"),
		"need_pincode": _("Postal Code is required"),
		"need_city": _("City is required"),
		"need_country": _("Country is required"),
	}

	return context
