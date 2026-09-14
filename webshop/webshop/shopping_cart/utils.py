# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt
import frappe

from webshop.webshop.doctype.webshop_settings.webshop_settings import is_cart_enabled


def show_cart_count():
	if (
		is_cart_enabled()
		and frappe.db.get_value("User", frappe.session.user, "user_type") == "Website User"
	):
		return True

	return False


def set_cart_count(login_manager):
	# since this is run only on hooks login event
	# make sure user is already a customer
	# before trying to set cart count
	user_is_customer = is_customer()
	if not user_is_customer:
		return

	if show_cart_count():
		from webshop.webshop.shopping_cart.cart import set_cart_count

		# set_cart_count will try to fetch existing cart quotation
		# or create one if non existent (and create a customer too)
		# cart count is calculated from this quotation's items
		set_cart_count()


def clear_cart_count(login_manager):
	if show_cart_count():
		frappe.local.cookie_manager.delete_cookie("cart_count")


def update_website_context(context):
	cart_enabled = is_cart_enabled()
	context["shopping_cart_enabled"] = cart_enabled

	# //// Neoffice — added: the wishlist icon lives in the Builder-built header, which is
	# //// rendered on every page, so the flag has to be in the website context and not
	# //// only on the shop's own pages (da044ea692, 2025-03-13 "add template wishlist").
	# Include wishlist component in all pages
	if frappe.db.get_single_value("Webshop Settings", "enable_wishlist"):
		context["include_wishlist"] = True

	# //// Neoffice — the customer's account pages are the shop's pages too (2026-09-14). Frappe
	# //// renders them (the order list, the account card, the address web form), so they
	# //// never got the shop's scope: on a dark site they sat on a near-white page with the
	# //// chrome's light ink on Frappe's white cards and forms. They carry `product-page` now,
	# //// the class the shop's ground and buttons hang on (webshop_ground.scss). This hook runs
	# //// after the page's own get_context, so the class is added, never overwritten.
	if is_account_page(context):
		classes = (context.get("body_class") or "").split()
		if "product-page" not in classes:
			context["body_class"] = " ".join(classes + ["product-page"])


# //// Neoffice — added (2026-09-14), see update_website_context.
ACCOUNT_PAGES = ("me", "update-password", "update-profile", "third_party_apps")


def is_account_page(context) -> bool:
	"""A page of the customer's account area: a route of the portal menu (orders, invoices,
	addresses, and what the shop adds — gift cards…) or one of Frappe's own account pages."""
	path = str(context.get("path") or getattr(frappe.local, "path", "") or "").strip("/")
	if not path:
		return False
	routes = set(ACCOUNT_PAGES)
	try:
		portal = frappe.get_cached_doc("Portal Settings")
		for row in list(portal.get("menu") or []) + list(portal.get("custom_menu") or []):
			if row.get("enabled") and row.get("route"):
				routes.add(str(row.get("route")).strip("/"))
	except Exception:
		pass
	return any(path == route or path.startswith(route + "/") for route in routes if route)


def is_customer():
	if frappe.session.user and frappe.session.user != "Guest":
		contact_name = frappe.get_value("Contact", {"email_id": frappe.session.user})
		if contact_name:
			contact = frappe.get_doc("Contact", contact_name)
			for link in contact.links:
				if link.link_doctype == "Customer":
					return True

		return False
