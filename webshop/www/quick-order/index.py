# //// Neoffice — added file (the reseller's quick order page, no upstream equivalent).
# //// Signs an anonymous visitor in first; then the module decides, from the session
# //// and the site, whether this account is a reseller and what the page shows.
import frappe
from frappe import _

from webshop.webshop.quick_order.api import PAGE_ROUTE, page_context

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.show_sidebar = 0
	context.title = _("Commande rapide")
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = f"/login?redirect-to={PAGE_ROUTE}"
		raise frappe.Redirect
	page_context(context)
	return context
