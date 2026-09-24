# //// Neoffice — added file (no upstream equivalent): the shop's brand pages, /brands/<slug>
# //// (neoffice-maintenance#691, lot 2). A brand's products were reachable only through the
# //// catalogue filtered on it (/all-products?field_filters={"brand": …}), which robots.txt
# //// closes and which names the plain catalogue as its reference: a search for a brand found no
# //// page of the shop, and every link to a brand (product page, carousel, category page) led there.
"""A brand page is the catalogue with its brand locked (as /occasions locks the condition), under
an address of its own, with the brand's logo and text (www/brand). Only a brand that carries
something this site shows has one: the scope of the facets, the category cards and the sitemaps."""

import json
import re
import unicodedata
from urllib.parse import quote

import frappe

ROUTE_PREFIX = "brands"


def brand_slug(name: str) -> str:
	"""The brand's name as one address segment: ASCII letters and digits joined by hyphens
	("Café & Co" → "cafe-co")."""
	ascii_name = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
	return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")


def brand_route(name: str) -> str:
	return f"{ROUTE_PREFIX}/{brand_slug(name)}"


def offered_brands() -> dict:
	"""{brand: how many items this site shows of it}, for every brand that has a page."""
	from webshop.webshop.product_data_engine.catalogue_scope import visible_item_filters

	filters = visible_item_filters()
	filters["brand"] = ["is", "set"]
	rows = frappe.get_all(
		"Website Item", fields=["brand", "count(name) as total"], filters=filters, group_by="brand"
	)
	return {row.brand: row.total for row in rows if row.brand and brand_slug(row.brand)}


def brand_page_routes() -> dict:
	"""{brand: "/brands/<slug>"} for the brands that have a page, in one query: what a template
	links a brand to (jinja method). A brand missing here has no page, and keeps its old link."""
	return {name: "/" + brand_route(name) for name in offered_brands()}


def brand_link(name: str, routes: dict | None = None) -> str:
	"""Where a link to a brand goes, without its leading slash: its page, else the catalogue
	filtered on it. `routes` is brand_page_routes(), fetched once by a caller that links many."""
	routes = brand_page_routes() if routes is None else routes
	if name in routes:
		return routes[name].lstrip("/")
	return "all-products?field_filters=" + quote(json.dumps({"brand": [name]}))


def brand_of_slug(slug: str) -> str | None:
	"""The brand behind an address segment, among those that have a page; None for any other.
	Two names folding to the same segment resolve to the first in alphabetical order."""
	if not slug:
		return None
	for name in sorted(offered_brands()):
		if brand_slug(name) == slug:
			return name
	return None
