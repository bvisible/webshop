# //// Neoffice — added file (the reseller's catalogues page, no upstream equivalent).
"""/my-catalogues: a reseller asks for a PDF catalogue of the products they choose, and follows it.

A visitor is sent to sign in; a signed-in account the shop did not allow gets the 403 page, so the
route tells nothing about who may use it. Every label comes from the server: a website page has no
`__()` catalogue of its own, and this page speaks the shop's language.
"""

import frappe
from frappe import _

from webshop.webshop.catalogue import access

no_cache = 1
PAGE_ROUTE = "/my-catalogues"


def labels():
	return {
		"lead": _(
			"Make a PDF catalogue of the products you choose, with your logo, your colours and your prices: "
			"your markup is added to what you pay. It takes a few seconds to a minute, and you can leave this page."
		),
		"brand_needed": _("Save your brand first: a catalogue carries your name, your logo and your colours."),
		"brand_link": _("Open the brand page"),
		"no_engine": _("This server cannot make PDF documents."),
		"new": _("New catalogue"),
		"title": _("Title"),
		"title_example": _("For example: Catalogue 2027"),
		"what": _("What goes in it"),
		"what_hint": _("A product is in the catalogue when any of your choices brings it."),
		"categories": _("Categories"),
		"categories_hint": _("A category brings its sub-categories."),
		"brands": _("Brands"),
		"products": _("Products"),
		"filter": _("Filter the list"),
		"search": _("Search a product by name, reference or brand"),
		"search_none": _("No product found."),
		"add": _("Add"),
		"remove": _("Remove"),
		"chosen": _("Chosen products"),
		"none_chosen": _("Nothing chosen yet."),
		"count_zero": _("Choose at least one category, one brand or one product."),
		"count_none_offered": _("The shop offers none of these products."),
		"count_n": _("{0} products in this catalogue."),
		"count_too_many": _("That is more than {0} products: narrow it down."),
		"options": _("Options"),
		"markup": _("Markup (%)"),
		"markup_hint": _("Starts from your brand's markup. Between 0 and 300."),
		"prices": _("Prices"),
		"prices_customers": _("Show my prices"),
		"prices_none": _("No prices"),
		"layout": _("Layout"),
		"layout_grid": _("Grid: three products a row"),
		"layout_list": _("List: one product a row"),
		"create": _("Make the catalogue"),
		"mine": _("Your catalogues"),
		"none_yet": _("You have not made a catalogue yet."),
		"col_title": _("Title"),
		"col_date": _("Made on"),
		"col_products": _("Products"),
		"col_pages": _("Pages"),
		"col_status": _("Status"),
		"status_Queued": _("Waiting"),
		"status_Running": _("In progress"),
		"status_Ready": _("Ready"),
		"status_Failed": _("Failed"),
		"stage_prices": _("Computing your prices"),
		"stage_pictures": _("Preparing the pictures"),
		"stage_render": _("Laying out the pages"),
		"download": _("Download"),
		"remake": _("Make it again"),
		"remake_hint": _("Same choices, prices computed again."),
		"delete": _("Delete"),
		"delete_confirm": _("Delete this catalogue?"),
		"kept": _("Prices of {0}. Kept until {1}."),
		"busy": _("A catalogue is being made: the next one can start when it is ready."),
		"loading": _("Loading…"),
		"failed": _("This could not be done. Try again."),
	}


def get_context(context):
	context.body_class = "product-page"  # the shop's ground (webshop_ground.scss)
	context.no_cache = 1
	context.title = _("Catalogues")
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = f"/login?redirect-to={PAGE_ROUTE}"
		raise frappe.Redirect
	if not access.is_offered():
		raise frappe.PermissionError(_("The reseller catalogue is not available for your account."))
	context.config = {"labels": labels()}
	return context
