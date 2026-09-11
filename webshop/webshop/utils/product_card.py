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
	hover = second_pictures(items)
	for item in items or []:
		if item.get("item_code") in hover:
			item["hover_image"] = hover[item["item_code"]]
		item["card_html"] = render_product_card(item, settings, "grid")
		item["list_html"] = render_product_card(item, settings, "list")
	return items


def second_pictures(items):
	"""The second photo of each item that has a slideshow: {item_code: image}.

	One query for the whole listing. The tile shows it on hover, the way a fashion
	shop turns the garment around; an item with one picture shows nothing new.
	"""
	slideshows = {item.get("slideshow"): item.get("item_code") for item in items or [] if item.get("slideshow")}
	if not slideshows:
		return {}
	rows = frappe.get_all(
		"Website Slideshow Item",
		filters={"parent": ("in", list(slideshows)), "parenttype": "Website Slideshow"},
		fields=["parent", "image", "idx"],
		order_by="parent, idx",
	)
	seen = {}
	for row in rows:
		code = slideshows[row.parent]
		first = next((i for i in items if i.get("item_code") == code), None)
		main = first.get("website_image") if first else None
		if row.image and row.image != main and code not in seen:
			seen[code] = row.image
	return seen
