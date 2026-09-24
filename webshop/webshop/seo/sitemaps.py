# //// Neoffice — added file (no upstream equivalent). What the shop's sitemaps list, in one
# //// place, with one scope: the catalogue a visitor of this site can be shown.
"""The shop's sitemaps.

What the study of 2026-09-24 measured (neoffice-maintenance#691, D9–D13):
- `/sitemap.xml`, the address every tool tries first and the one a hand-written robots.txt
  names, listed no product at all: it skipped Website Item, which has no `allow_guest_to_view`.
  The 6292 products of a client shop sat in `/sitemap_products.xml`, cited by nothing but
  `/sitemap_index.xml`, itself cited by nothing. `/sitemap.xml` is now the index.
- the brands sitemap listed catalogue URLs filtered on a brand (`?field_filters=…`) for every
  brand, used or not, of this site or not: a filtered catalogue is not a page. It lists
  nothing until the shop has real brand pages.
- the categories sitemap listed every group shown on the website, empty ones included, and
  those of the other site of the instance.
- every `lastmod` of the index and of the static pages was today's date, and `changefreq` /
  `priority` were set everywhere. Google reads `lastmod` only if it is reliably true, and
  ignores the other two: they are gone.
"""

from urllib.parse import quote

import frappe
from frappe.utils.caching import redis_cache

from webshop.webshop.multi_site import get_current_profile_name, site_url

SITEMAP_LIMIT = 50000
CACHE_TTL = 6 * 60 * 60

# Builder pages that are pieces of the site chrome, not pages of their own.
CHROME_KEYWORDS = ("footer", "navbar", "header", "navigation", "menu")

# The shop's listing pages (webshop/www), listed when they have something to show.
SHOP_LISTINGS = ("all-products", "shop-by-category", "occasions")


def index_entries():
	"""The sitemaps the index lists, on the domain of the site being browsed."""
	names = ["sitemap_pages.xml", "sitemap_products.xml", "sitemap_categories.xml", "sitemap_brands.xml"]
	if frappe.db.table_exists("Blog Post") and frappe.db.exists("Blog Post", {"published": 1}):
		names.append("sitemap_blog.xml")
	return [{"loc": _loc(name)} for name in names]


def _loc(route):
	"""Absolute, percent-encoded and XML-escaped address of a route on this site."""
	from webshop.www.sitemap_utils import prepare_url_for_xml

	route = (route or "").strip("/")
	return prepare_url_for_xml(site_url(quote(route.encode("utf-8"))) if route else site_url(""))


def _file_loc(path):
	"""The same for a file: a picture named `IMG 2611.jpg` or `a&b.png` must not break the XML."""
	from webshop.www.sitemap_utils import prepare_url_for_xml

	path = path or ""
	if not path.startswith(("http://", "https://")):
		path = quote(path.encode("utf-8"))
	return prepare_url_for_xml(site_url(path))


def _day(value):
	return f"{value:%Y-%m-%d}" if value else None


def product_links():
	return _product_links(get_current_profile_name())[:SITEMAP_LIMIT]


@redis_cache(ttl=CACHE_TTL)
def _product_links(website_profile=None):
	"""Every product page the catalogue shows on this site, with its pictures."""
	from webshop.webshop.multi_site import effective_price_list
	from webshop.webshop.product_data_engine.catalogue_scope import visible_item_filters

	filters = visible_item_filters()
	# A variant hidden from the listings is still a page of its own until the shop decides
	# otherwise (decision D-1 of the study): the sitemap follows the listing on everything else.
	filters.pop("variant_of", None)
	products = frappe.get_all(
		"Website Item",
		fields=["route", "item_code", "modified", "web_item_name", "website_image", "slideshow"],
		filters=filters,
		order_by="ranking desc, modified desc",
	)
	products = [p for p in products if p.route]
	if not products:
		return []

	codes = [p.item_code for p in products]
	# A price change changes what the page and its structured data say: it counts as a change.
	price_list = effective_price_list()
	price_changes = {}
	if price_list:
		for row in frappe.get_all(
			"Item Price",
			filters={"price_list": price_list, "item_code": ["in", codes]},
			fields=["item_code", "max(modified) as changed"],
			group_by="item_code",
		):
			price_changes[row.item_code] = row.changed
	item_changes = dict(
		frappe.get_all("Item", filters={"name": ["in", codes]}, fields=["name", "modified"], as_list=True)
	)
	slides = {}
	slideshows = list({p.slideshow for p in products if p.slideshow})
	if slideshows:
		for row in frappe.get_all(
			"Website Slideshow Item",
			filters={"parent": ["in", slideshows], "image": ["is", "set"]},
			fields=["parent", "image"],
			order_by="idx asc",
		):
			slides.setdefault(row.parent, []).append(row.image)

	links = []
	for product in products:
		images = []
		for image in [product.website_image] + slides.get(product.slideshow, []):
			if image and image not in images:
				images.append(image)
		changed = max(
			value
			for value in (product.modified, item_changes.get(product.item_code), price_changes.get(product.item_code))
			if value
		)
		links.append(
			{
				"loc": _loc(product.route),
				"lastmod": _day(changed),
				"images": [{"loc": _file_loc(image)} for image in images],
			}
		)
	return links


def category_links():
	return _category_links(get_current_profile_name())[:SITEMAP_LIMIT]


@redis_cache(ttl=CACHE_TTL)
def _category_links(website_profile=None):
	"""The category pages that hold something on this site: the groups /shop-by-category shows."""
	from webshop.webshop.product_data_engine.catalogue_scope import groups_carrying_items

	carried = groups_carrying_items()
	if not carried:
		return []
	redirected = {str(rule.get("source") or "").strip("/ ") for rule in frappe.get_hooks("website_redirects") or []}
	links = []
	for group in frappe.get_all(
		"Item Group",
		filters={"name": ["in", list(carried)]},
		fields=["route", "modified", "image", "parent_item_group"],
		order_by="lft asc",
	):
		route = (group.route or "").strip("/")
		# The root of the tree ("All Item Groups") is not a category, and its route redirects.
		if not route or not group.parent_item_group or route in redirected:
			continue
		link = {"loc": _loc(route), "lastmod": _day(group.modified)}
		if group.image:
			link["images"] = [{"loc": _file_loc(group.image)}]
		links.append(link)
	return links


def brand_links():
	return _brand_links(get_current_profile_name())[:SITEMAP_LIMIT]


@redis_cache(ttl=CACHE_TTL)
def _brand_links(website_profile=None):
	"""The brand pages of this site (lot 2): the brands carrying something it shows, the rule of
	product_data_engine/brand_pages.py, which is also what makes such a page exist."""
	from webshop.webshop.product_data_engine.brand_pages import brand_route, offered_brands

	brands = offered_brands()
	if not brands:
		return []
	links = []
	for brand in frappe.get_all(
		"Brand", filters={"name": ["in", list(brands)]}, fields=["name", "modified", "image"], order_by="name asc"
	):
		link = {"loc": _loc(brand_route(brand.name)), "lastmod": _day(brand.modified)}
		if brand.image:
			link["images"] = [{"loc": _file_loc(brand.image)}]
		links.append(link)
	return links


def page_links():
	return _page_links(get_current_profile_name())[:SITEMAP_LIMIT]


@redis_cache(ttl=CACHE_TTL)
def _page_links(website_profile=None):
	"""The site's own pages: Builder pages of this site, Web Pages, the shop's listings."""
	home_routes = _home_routes()
	links = {}

	def add(route, modified=None, image=None):
		route = (route or "").strip("/")
		loc = _loc("") if route in home_routes else _loc(route)
		if loc in links:
			return
		link = {"loc": loc, "lastmod": _day(modified)}
		if image:
			link["images"] = [{"loc": _file_loc(image)}]
		links[loc] = link

	try:
		for page in _builder_pages(website_profile):
			add(page.route, page.modified, page.meta_image)
	except Exception:
		# One source that fails must not take the whole sitemap down (it answered 500).
		frappe.log_error("Sitemap: Builder pages skipped", frappe.get_traceback())

	try:
		for page in frappe.get_all(
			"Web Page", filters={"published": 1}, fields=["route", "modified", "meta_image"]
		):
			if page.route:
				add(page.route, page.modified, page.meta_image)
	except Exception:
		frappe.log_error("Sitemap: Web Pages skipped", frappe.get_traceback())

	# The shop's own listings, named rather than discovered: frappe.website.router.get_pages()
	# walks every app's www folder, and one unreadable file anywhere in them (macOS "._" files
	# copied onto a server, osiris 2026-09-24) makes it raise, and this sitemap with it.
	for route in SHOP_LISTINGS:
		if _listing_has_products(route):
			add(route)

	for doctype, route, field in (("Contact Us Settings", "contact", "heading"), ("About Us Settings", "about", "page_title")):
		try:
			if frappe.db.get_single_value(doctype, field):
				add(route, frappe.db.get_single_value(doctype, "modified"))
		except Exception:
			pass

	return list(links.values())


def _home_routes():
	routes = {"", "index", "home", "homepage"}
	home = frappe.db.get_single_value("Website Settings", "home_page")
	if home:
		routes.add(home.strip("/"))
	profile = getattr(frappe.local, "website_profile_doc", None)
	if profile and profile.get("home_route"):
		routes.add(str(profile.get("home_route")).strip("/"))
	return routes


def _builder_pages(website_profile):
	"""Published Builder pages this site serves, as builder's own resolver chooses them."""
	if "builder" not in frappe.get_installed_apps():
		return []
	fields = ["route", "modified", "meta_image", "page_title", "dynamic_route", "is_template", "disable_indexing", "authenticated_access"]
	has_site_field = frappe.db.has_column("Builder Page", "neo_website_profile")
	if has_site_field:
		fields.append("neo_website_profile")
	pages = []
	for page in frappe.get_all("Builder Page", filters={"published": 1}, fields=fields):
		if not page.route or page.dynamic_route or page.is_template or page.disable_indexing or page.authenticated_access:
			continue
		# A page tagged for another site does not answer here; untagged pages serve everywhere.
		if has_site_field and website_profile and page.neo_website_profile and page.neo_website_profile != website_profile:
			continue
		words = f"{page.route} {page.page_title or ''}".lower()
		if any(keyword in words for keyword in CHROME_KEYWORDS):
			continue
		pages.append(page)
	return pages


def _listing_has_products(route) -> bool:
	"""A listing page is only worth listing when it has something to show."""
	if route == "occasions":
		from webshop.webshop.product_data_engine.listing_context import count_second_hand

		return bool(count_second_hand())
	return True


def clear_caches():
	"""Forget every cached sitemap of this site (Webshop Settings' "Regenerate" button).

	`redis_cache` stores one key per call (`<function>::<arguments>`) and gives the function a
	`clear_cache()` that deletes them all. Deleting the bare function name, as the button did,
	matched no key: the button never cleared anything.
	"""
	for function in (_product_links, _category_links, _brand_links, _page_links):
		function.clear_cache()
