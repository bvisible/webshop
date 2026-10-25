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
		# //// Neoffice — and the account's own scope: one look for its titles, surfaces, actions and menu
		# //// (webshop_account.scss, 2026-10-25). `product-page` is the shop's ground and is on the cart, the
		# //// checkout and the catalogue too; this one is on the pages of the account only.
		classes = (context.get("body_class") or "").split()
		if "wsp-account" not in classes:
			context["body_class"] = " ".join(classes + ["wsp-account"])

		# //// Neoffice — and the account's menu on each of them (2026-10-25): the links of /me led to
		# //// pages with no sidebar, and a web form builds none of its own (utils/account_menu.py).
		from webshop.webshop.utils.account_menu import give_the_account_its_menu

		give_the_account_its_menu(context)


# //// Neoffice — added (2026-09-14), see update_website_context.
# //// Neoffice — "addresses" too: the shop's own address page (/my_addresses) and the checkout
# //// send the customer to ERPNext's address web form, which a portal menu may not list
# //// Neoffice — "address" is that web form's own route (/address/new, /address/<name>): the menu's
# //// route is /addresses, so the form was not recognised as a page of the account (2026-10-25)
# //// Neoffice — and the shop's own pages of the account, whether or not the portal menu lists them: a menu
# //// that never got the loyalty entry left /loyalty_points out of the account's scope, and its page drew
# //// its own title and surfaces (osiris, 2026-10-25)
ACCOUNT_PAGES = (
	"me",
	"update-password",
	"update-profile",
	"third_party_apps",
	"addresses",
	"address",
	"my_addresses",
	"gift_cards",
	"loyalty_points",
)


def is_account_page(context) -> bool:
	"""A page of the customer's account area: a route of the portal menu (orders, invoices,
	addresses, and what the shop adds — gift cards…) or one of Frappe's own account pages."""
	# //// Neoffice — the address asked for, not only the page that answers it: /orders is served
	# //// by Frappe's list page, whose context says "list" (a route rule maps the portal's URL to it)
	paths = {str(context.get("path") or "").strip("/"), str(getattr(frappe.local, "path", "") or "").strip("/")}
	request = getattr(frappe.local, "request", None)
	if request is not None:
		paths.add(str(getattr(request, "path", "") or "").strip("/"))
	paths.discard("")
	if not paths:
		return False
	routes = set(ACCOUNT_PAGES)
	try:
		portal = frappe.get_cached_doc("Portal Settings")
		for row in list(portal.get("menu") or []) + list(portal.get("custom_menu") or []):
			if row.get("enabled") and row.get("route"):
				routes.add(str(row.get("route")).strip("/"))
	except Exception:
		pass
	# //// Neoffice — any of the candidate paths (2026-09-14)
	return any(path == route or path.startswith(route + "/") for path in paths for route in routes if route)


def is_customer():
	if frappe.session.user and frappe.session.user != "Guest":
		contact_name = frappe.get_value("Contact", {"email_id": frappe.session.user})
		if contact_name:
			contact = frappe.get_doc("Contact", contact_name)
			for link in contact.links:
				if link.link_doctype == "Customer":
					return True

		return False
