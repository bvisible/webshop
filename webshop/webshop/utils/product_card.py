# //// Neoffice — added file (no upstream equivalent).
"""The product card, rendered on the server for every listing.

`templates/includes/product_card.html` holds the one macro every listing draws its
products with. The catalogue's JavaScript used to build its own copy of the card from
template strings (grid.js, list.js), the carousel a second one in Jinja, the wishlist
a third in macros.html — three languages for one tile, and each fix made three
times. The listing endpoint now renders the tile for each item it returns
(`card_html`, `list_html`) and the JavaScript only appends what it is given.
"""

import frappe

TEMPLATE = "webshop/templates/includes/product_card.html"


def render_product_card(item, settings, variant="grid", cart_settings=None):
	"""The HTML of one product card.

	`item` is a dict as the listing engine returns it (or a Website Item row the
	wishlist prepared); `settings` is Webshop Settings, a document or its dict.
	"""
	module = frappe.get_template(TEMPLATE).module
	return module.product_card(item, settings, variant=variant, cart_settings=cart_settings)


def attach_cards(items, settings):
	"""Give every item of a listing its grid and list tiles, in place."""
	for item in items or []:
		item["card_html"] = render_product_card(item, settings, "grid")
		item["list_html"] = render_product_card(item, settings, "list")
	return items
