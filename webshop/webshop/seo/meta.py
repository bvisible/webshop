# //// Neoffice — added file (no upstream equivalent). The meta tags the shop's pages were
# //// missing: what not to index, what a listing or a category holds, which address is the
# //// reference (neoffice-maintenance#691).
import frappe
from frappe import _
from frappe.utils import cint, comma_and

from webshop.webshop.multi_site import site_url
from webshop.webshop.seo.site import shop_name
from webshop.webshop.seo.text import truncate

DESCRIPTION_LIMIT = 158

# Pages with nothing to show a searcher: a cart, an account, a search result, a receipt.
NOINDEX_ROUTES = {
	"cart",
	"checkout",
	"checkout_b2b",
	"wishlist",
	"gift_cards",
	"loyalty_points",
	"login",
	"search",
	"product_search",
	"my_addresses",
	"customer_reviews",
	"thank_you",
	"payment-success",
	"quick-order",
	"order",
}
NOINDEX_PREFIXES = ("orders/", "invoices/", "quotations/", "order/")
# A listing narrowed by a search or a facet: the same products as the plain listing.
LISTING_PARAMETERS = ("search", "field_filters", "attribute_filters")


def update_website_context(context):
	"""`update_website_context` hook: the robots.txt default and the `noindex` of private pages."""
	path = request_path(context)
	if path == "robots.txt":
		# Frappe's www/robots.py rendered an empty file when nobody wrote one.
		if not (context.get("robots_txt") or "").strip():
			from webshop.webshop.seo.robots import default_robots_txt

			context["robots_txt"] = default_robots_txt()
		return
	if should_not_index(path, context):
		metatags = context.get("metatags")
		if metatags is not None:
			metatags["robots"] = "noindex, follow"


def request_path(context) -> str:
	"""The path asked for, without slashes: the page's own, else the request's."""
	request = getattr(frappe.local, "request", None)
	for candidate in (
		getattr(request, "path", None) if request is not None else None,
		getattr(frappe.local, "path", None),
		context.get("path"),
	):
		if candidate:
			return str(candidate).strip("/")
	return ""


def should_not_index(path, context) -> bool:
	if path in NOINDEX_ROUTES or path.startswith(NOINDEX_PREFIXES):
		return True
	from webshop.webshop.shopping_cart.utils import is_account_page

	if is_account_page(context):
		return True
	form = getattr(frappe.local, "form_dict", None) or {}
	return any(form.get(parameter) for parameter in LISTING_PARAMETERS)


def catalogue_summary(item_groups=None, extra_filters=None):
	"""(how many visible products, their three most frequent brands) in `item_groups`."""
	from webshop.webshop.product_data_engine.catalogue_scope import visible_item_filters

	filters = visible_item_filters()
	if item_groups is not None:
		if not item_groups:
			return 0, []
		filters["item_group"] = ["in", list(item_groups)]
	for fieldname, values in (extra_filters or {}).items():
		filters[fieldname] = ["in", list(values)]
	rows = frappe.get_all(
		"Website Item", fields=["brand", "count(name) as total"], filters=filters, group_by="brand"
	)
	total = sum(row.total for row in rows)
	brands = [row.brand for row in sorted(rows, key=lambda row: -row.total) if row.brand][:3]
	return total, brands


def summary_description(subject, total, brands) -> str:
	"""« Chaussures : 12 produits, dont Trailhead, Salomon et Hoka. » — within 158 characters."""
	if total == 1:
		text = _("{0}: one product.").format(subject)
	elif brands:
		text = _("{0}: {1} products, including {2}.").format(subject, total, comma_and(brands, add_quotes=False))
	else:
		text = _("{0}: {1} products.").format(subject, total)
	return truncate(text, DESCRIPTION_LIMIT)


def subtree_groups(item_group) -> list:
	"""The group and every group under it."""
	bounds = frappe.db.get_value("Item Group", item_group, ["lft", "rgt"], as_dict=True)
	if not bounds:
		return []
	return frappe.get_all(
		"Item Group", filters={"lft": [">=", bounds.lft], "rgt": ["<=", bounds.rgt]}, pluck="name"
	)


def first_product_image(item_groups=None, extra_filters=None):
	"""The picture of the first visible product, for a page that has none of its own."""
	from webshop.webshop.product_data_engine.catalogue_scope import visible_item_filters

	filters = visible_item_filters()
	filters["website_image"] = ["is", "set"]
	if item_groups is not None:
		if not item_groups:
			return None
		filters["item_group"] = ["in", list(item_groups)]
	for fieldname, values in (extra_filters or {}).items():
		filters[fieldname] = ["in", list(values)]
	image = frappe.get_all(
		"Website Item", filters=filters, pluck="website_image", order_by="ranking desc, modified desc", limit=1
	)
	return image[0] if image else None


def listing_metatags(context, title, route, locked_field_filters=None):
	"""Description, picture and canonical address of a product listing (/all-products, /occasions)."""
	name = shop_name()
	# The context keeps this string apart from another app's "{0} at {1}" (a time: "à"), which
	# Frappe's merged catalogue would otherwise lend it: "Tous les produits à <boutique>".
	subject = _("{0} at {1}", context="Shop name in a page description").format(title, name) if name else title
	total, brands = catalogue_summary(extra_filters=locked_field_filters)
	metatags = frappe._dict(context.get("metatags") or {})
	if total:
		metatags["description"] = summary_description(subject, total, brands)
		image = first_product_image(extra_filters=locked_field_filters)
		if image:
			metatags["image"] = image
	context.metatags = metatags
	context.canonical_url = listing_canonical(route)


def listing_canonical(route) -> str:
	"""A listing's reference address. Filters and searches show the same catalogue: the plain
	listing. A page of it is its own reference (`?start=`, since lot 2 links the pages): Google
	asks each page of a series to be canonical to itself, not to the first, or the products of
	the other pages are never reached."""
	form = frappe.form_dict
	start = cint(form.get("start"))
	if start > 0 and not any(form.get(key) for key in (*LISTING_PARAMETERS, "price_range")):
		return site_url(f"{route}?start={start}")
	return site_url(route)
