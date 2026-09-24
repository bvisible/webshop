# //// Neoffice — added file (no upstream equivalent). The robots.txt a shop serves when its
# //// owner wrote none.
"""A sane default robots.txt for a shop.

Frappe serves Website Settings' robots.txt, or the Website Profile's, or nothing. Nothing is
what every new shop served (osiris, 2026-09-24): no `Sitemap:` line, so search engines had to
guess where the products are listed, and the cart, the account pages and the internal search
were open to crawling.

Rules that matter here:
- `/cart` would also block `/cartes-cadeaux`: paths are anchored with `$` or end in `/` or `?`.
- `/api/` stays open: until the listings are rendered on the server, Google's renderer loads
  the category grids through `/api/method/...`, and blocking it empties them for Google too.
- One `User-agent: *` group. A robot named in a group of its own ignores the `*` group
  (RFC 9309), so blocking a robot by name means repeating these lines in its group.
"""

from webshop.webshop.multi_site import site_url

PRIVATE_PATHS = (
	"/app$",
	"/app/",
	"/cart$",
	"/cart?",
	"/checkout$",
	"/checkout?",
	"/login$",
	"/login?",
	"/me$",
	"/update-password",
	"/update-profile",
	"/orders$",
	"/orders/",
	"/invoices$",
	"/invoices/",
	"/quotations$",
	"/quotations/",
	"/addresses$",
	"/my_addresses$",
	"/wishlist$",
	"/gift_cards$",
	"/loyalty_points$",
	"/thank_you",
	"/payment-success",
	"/search$",
	"/search?",
)

# Query parameters that only filter or search a listing: the same products, again.
LISTING_PARAMETERS = ("field_filters", "attribute_filters", "search")


def default_robots_txt() -> str:
	"""robots.txt for the site being browsed, pointing at its own sitemap."""
	lines = ["User-agent: *"]
	lines += [f"Disallow: {path}" for path in PRIVATE_PATHS]
	lines += [f"Disallow: /*?*{parameter}=" for parameter in LISTING_PARAMETERS]
	lines += ["", f"Sitemap: {site_url('sitemap.xml')}"]
	return "\n".join(lines) + "\n"
