# //// Neoffice — added file (no upstream equivalent).
"""The links to a product's sheet that its page offers: the shop's, and the reseller's own."""

from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import cint

API = "/api/method/webshop.webshop.catalogue.sheet_api."


def sheet_links(doc, settings):
	"""[{label, href}] the page prints under its promises; empty when nothing is offered."""
	links = []
	if cint(settings.get("enable_product_sheet")):
		links.append({"label": _("Product sheet (PDF)"), "href": f"{API}product_sheet?item={quote(doc.name)}"})
	if frappe.session.user != "Guest":
		from webshop.webshop.catalogue import access

		if access.is_offered():
			links.append({"label": _("Product sheet in my name (PDF)"), "href": f"{API}my_product_sheet?item={quote(doc.name)}"})
	return links
