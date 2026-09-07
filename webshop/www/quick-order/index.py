# //// Neoffice — added file (the quick order page, no upstream equivalent).
# //// An anonymous visitor is sent to sign in where the shop does not sell to
# //// visitors; then the module decides, from the session and the site, what the
# //// page shows. Open to every customer: nothing in it is professional but the pace.
import frappe
from frappe import _

from webshop.webshop.quick_order.api import PAGE_ROUTE, guest_allowed, page_context

no_cache = 1


def get_context(context):
	context.no_cache = 1
	context.show_sidebar = 0
	context.title = _("Commande rapide")
	if frappe.session.user == "Guest" and not guest_allowed():
		frappe.local.flags.redirect_location = f"/login?redirect-to={PAGE_ROUTE}"
		raise frappe.Redirect
	page_context(context)
	return context
