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
			"Make a catalogue of the products you choose, with your prices: your markup is added to what you pay. "
			"A PDF with your logo and your colours, an Excel or CSV file, or a feed your own shop can read. "
			"It takes a few seconds to a minute, and you can leave this page."
		),
		"brand_needed": _("Save your brand first: a catalogue carries your name, your logo and your colours."),
		"brand_link": _("Open the brand page"),
		"no_engine": _("This server cannot make PDF documents."),
		"new": _("New catalogue"),
		"format": _("Format"),
		"format_pdf": _("PDF catalogue"),
		"format_xlsx": _("Excel workbook"),
		"format_csv": _("CSV file"),
		"format_feed": _("Product feed for my shop"),
		"hint_pdf": _("A document to print or send, with your logo and your colours."),
		"hint_xlsx": _(
			"A workbook to read and filter: one line for each thing that can be bought. A product with variants is one line for each."
		),
		"hint_csv": _(
			"For importing into another system: comma-separated, UTF-8, the same column names every time. To read it yourself, choose Excel."
		),
		"hint_feed": _(
			"An address your shop or your script reads, always up to date: photos, descriptions and your selling prices. Whoever has the address can read it."
		),
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
		"markup_particular": _(
			"Your particular markups ({0}) replace it for the categories, brands and products they name. "
			"You change them on your brand page."
		),
		"prices": _("Prices"),
		"prices_customers": _("Show my prices"),
		"prices_selling": _("My selling prices"),
		"prices_tariff": _("What I pay (confidential)"),
		"prices_both": _("What I pay and my selling prices"),
		"prices_none": _("No prices"),
		"quality": _("Pictures"),
		"quality_standard": _("Standard"),
		"quality_light": _("Light: for an e-mail"),
		"quality_print": _("High: for a printer"),
		"quality_hint": _("Light makes a small file, high keeps the pictures sharp on paper and a larger file."),
		"language": _("Language of the texts"),
		"language_source": _("The shop's own language"),
		"language_hint": _("The name and the description of each product, as the shop's visitors read them in that language."),
		"layout": _("Layout"),
		"layout_grid": _("Grid: three products a row"),
		"layout_list": _("List: one product a row"),
		"create": _("Make the catalogue"),
		"create_xlsx": _("Make the workbook"),
		"create_csv": _("Make the CSV file"),
		"create_feed": _("Save the feed"),
		"count_lines": _("{0} lines in this file."),
		"count_lines_too_many": _("That is more than {0} lines: narrow it down."),
		"mine": _("Your catalogues"),
		"none_yet": _("You have not made a catalogue yet."),
		"col_title": _("Title"),
		"col_date": _("Made on"),
		"col_products": _("Products"),
		"col_pages": _("Pages"),
		"col_format": _("Format"),
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
		"feed_title": _("Your product feed"),
		"feed_status_Queued": _("Waiting to be refreshed"),
		"feed_status_Running": _("Being refreshed"),
		"feed_status_Ready": _("Ready"),
		"feed_status_Failed": _("The last refresh failed"),
		"feed_lines": _("Lines: {0} · Prices of {1}"),
		"feed_fetched": _("Last read: {0}"),
		"feed_never_fetched": _("Nobody has read it yet."),
		"feed_choices": _("Categories: {0} · Brands: {1} · Products: {2} · Markup: {3} %"),
		"feed_prices_customers": _("your selling prices"),
		"feed_prices_none": _("no prices"),
		"feed_kept": _("The previous file is still served."),
		"feed_csv": _("CSV address"),
		"feed_json": _("JSON address"),
		"feed_secret": _("Keep these addresses to yourself: whoever has one can read your feed."),
		"feed_change": _("To change what the feed carries, choose Product feed above and save: the address stays the same."),
		"share": _("Share"),
		"share_hint": _("A link that shows the catalogue to somebody who has no account, and an e-mail that carries it."),
		"share_days": _("The link lasts"),
		"share_days_7": _("7 days"),
		"share_days_14": _("14 days"),
		"share_days_30": _("30 days"),
		"share_make": _("Make a link"),
		"share_new": _("A new link"),
		"share_new_hint": _("The current link stops working at once."),
		"share_stop": _("Stop the link"),
		"share_until": _("The link shows the catalogue until {0}."),
		"share_opened": _("Last opened: {0}."),
		"share_expired": _("This link has expired."),
		"share_never": _("Not opened yet."),
		"mail_title": _("Send it by e-mail"),
		"mail_hint": _("The e-mail holds the link, not the file, and goes out in the name of your brand. Nothing is sent unless you press the button."),
		"mail_to": _("To"),
		"mail_to_hint": _("One e-mail address."),
		"mail_message": _("Your message"),
		"mail_send": _("Send"),
		"mail_sent": _("The e-mail is on its way."),
		"copy": _("Copy"),
		"copied": _("Copied"),
		"feed_refresh": _("Refresh now"),
		"feed_rotate": _("New address"),
		"feed_rotate_confirm": _("The current address stops working at once. Continue?"),
		"feed_delete": _("Stop the feed"),
		"feed_delete_confirm": _("Stop the feed? Its address stops working at once."),
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
