# //// Neoffice — added file (no upstream equivalent).
"""The links to a product's sheet that its page offers: the shop's, and the reseller's own."""

from urllib.parse import quote

import frappe
from frappe import _
from frappe.utils import cint

API = "/api/method/webshop.webshop.catalogue.sheet_api."


def sheet_links(doc, settings):
	"""[{label, href, own}] the page prints at the end of its buy column; empty when nothing is offered.

	`own` marks the reseller's sheet, the one in their name: the page tells it from the shop's by a tag, not by words.
	"""
	links = []
	if cint(settings.get("enable_product_sheet")):
		links.append(
			{
				"label": _("Product sheet (PDF)"),
				"href": f"{API}product_sheet?item={quote(doc.name)}",
				"own": False,
			}
		)
	if frappe.session.user != "Guest":
		from webshop.webshop.catalogue import access

		if access.is_offered():
			links.append(
				{
					"label": _("Product sheet in my name (PDF)"),
					"href": f"{API}my_product_sheet?item={quote(doc.name)}",
					"own": True,
				}
			)
	return links
