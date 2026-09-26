# //// Neoffice — added file (no upstream equivalent): IndexNow, the protocol through which Bing,
# //// Yandex, Seznam, Naver, Yep and a few others learn that a page changed, instead of waiting
# //// for their next crawl (neoffice-maintenance#691, lot 4). Bing writes that it keeps its AI
# //// answers current from it; Google does not take part.
"""Tell search engines which product pages changed.

- The key sits at the root of every site of the instance, `/<key>.txt` (KeyRenderer): that is how
  an engine checks that a notification comes from the site it names.
- A Website Item saved while published, or withdrawn, a selling price changed, and a product
  that ran out or came back in stock, queue the item's page; every ten minutes, one request per
  site sends what piled up. The queue is a Redis
  set, so a page saved ten times in ten minutes is sent once.
- Off by default (Webshop Settings, Advanced tab): an instance never starts calling a third party
  because it migrated. A site serving business accounts only is left out, as robots.txt keeps
  crawlers out of it.
"""

from urllib.parse import urlparse

import frappe
import requests
from frappe.utils import cint
from frappe.website.page_renderers.base_renderer import BaseRenderer
from werkzeug.wrappers import Response

ENDPOINT = "https://api.indexnow.org/indexnow"
QUEUE_KEY = "webshop_indexnow_queue"
# the protocol's limit per request
BATCH_LIMIT = 10000
TIMEOUT = 20


def active_key() -> str | None:
	"""The shop's key, when notifications are switched on."""
	settings = frappe.get_cached_doc("Webshop Settings")
	if not cint(settings.get("enable_indexnow")):
		return None
	return settings.get("indexnow_key") or None


# ---------------------------------------------------------------------------------------------
# What changed


def queue_routes(routes):
	routes = {route.strip("/") for route in routes if route and route.strip("/")}
	if routes and active_key():
		frappe.cache.sadd(QUEUE_KEY, *sorted(routes))


def grouped_variants(item_codes) -> set[str]:
	"""Those of these items that are variants sold on their model's page (decision D-1,
	seo/variants.py). Such a page names its model's as canonical: an engine hears of the model's
	page, which shows the variant's price and stock, and never of the variant's own."""
	codes = [code for code in item_codes or [] if code]
	# the switch itself: get_shopping_cart_settings() would build the whole document for one value
	if not codes or not cint(frappe.db.get_single_value("Webshop Settings", "enable_variants")):
		return set()
	from webshop.webshop.seo.variants import model_page_name

	return {
		row.name
		for row in frappe.get_all(
			"Item", filters={"name": ["in", codes], "variant_of": ["is", "set"]}, fields=["name", "variant_of"]
		)
		if model_page_name(row.variant_of)
	}


def queue_website_item(doc, method=None):
	"""`doc_events` of Website Item (on_update, on_trash): its page, and the page it had before a
	change of address, which now answers with a redirection the engine should see. A variant sold
	on its model's page: the model's page instead (grouped_variants)."""
	before = doc.get_doc_before_save() if method == "on_update" else None
	if not cint(doc.published) and not (before and cint(before.published)):
		return  # never public: no engine knows this page
	if doc.get("variant_of") and doc.get("item_code") in grouped_variants([doc.get("item_code")]):
		queue_routes(frappe.get_all("Website Item", filters={"item_code": doc.variant_of, "published": 1}, pluck="route"))
		return
	routes = [doc.route]
	if before and before.route and before.route != doc.route:
		routes.append(before.route)
	queue_routes(routes)


def queue_item_price(doc, method=None):
	"""`doc_events` of Item Price: a selling price changed the pages that print it."""
	if not cint(doc.get("selling")) or not active_key():
		return
	codes = [doc.item_code]
	template = frappe.db.get_value("Item", doc.item_code, "variant_of")
	if template:
		codes.append(template)
		# a variant sold on its model's page: the model's page alone prints its price
		if doc.item_code in grouped_variants([doc.item_code]):
			codes.remove(doc.item_code)
	queue_routes(
		frappe.get_all(
			"Website Item", filters={"item_code": ["in", codes], "published": 1}, pluck="route"
		)
	)


# ---------------------------------------------------------------------------------------------
# Availability: a page whose product ran out, or came back, changed for an engine too

STOCK_STATE_KEY = "webshop_indexnow_stock_state"


def on_stock_ledger_entry(doc, method=None):
	"""Stock Ledger Entry on_submit: remembers what a voucher moves, when notifications are on.
	Availability cannot be read here: ERPNext updates the warehouse's Bin only after the ledger
	entry (see utils/used_items.py, the same rule for the second-hand units)."""
	if active_key():
		frappe.flags.setdefault("webshop_indexnow_moved", set()).add(doc.item_code)


def check_moved_items(doc, method=None):
	"""Every document's on_submit / on_cancel ("*" in hooks.py): once a voucher is done, its items
	are checked in the background, after the commit — a stock reconciliation moves thousands."""
	moved = frappe.flags.get("webshop_indexnow_moved")
	if not moved or doc.doctype == "Stock Ledger Entry":
		return
	frappe.flags.webshop_indexnow_moved = set()
	frappe.enqueue(
		"webshop.webshop.seo.indexnow.queue_availability_flips",
		item_codes=sorted(moved),
		queue="short",
		enqueue_after_commit=True,
	)


def queue_availability_flips(item_codes):
	"""The pages of the items whose availability changed since the last look (in stock, out of
	stock, on back order), and of their models: a model's page shows its variants' stock. The
	last state is kept in Redis; an item seen for the first time is queued once, which costs an
	engine nothing."""
	if not active_key():
		return
	from webshop.webshop.seo.availability import schema_availability

	pages = frappe.get_all(
		"Website Item",
		filters={"item_code": ["in", list(item_codes)], "published": 1},
		fields=["item_code", "route", "variant_of"],
	)
	routes, models = [], set()
	grouped = grouped_variants([page.item_code for page in pages if page.variant_of])
	for page in pages:
		state = schema_availability(page.item_code)
		previous = frappe.cache.hget(STOCK_STATE_KEY, page.item_code)
		if previous == state:
			continue
		frappe.cache.hset(STOCK_STATE_KEY, page.item_code, state)
		# a variant sold on its model's page: the model's page alone, added below
		if page.item_code not in grouped:
			routes.append(page.route)
		if page.variant_of:
			models.add(page.variant_of)
	if models:
		routes += frappe.get_all("Website Item", filters={"item_code": ["in", sorted(models)], "published": 1}, pluck="route")
	queue_routes(routes)


def take_queue() -> list[str]:
	"""What piled up, removed from the queue; a page queued meanwhile stays for the next run."""
	members = frappe.cache.smembers(QUEUE_KEY) or set()
	if members:
		frappe.cache.srem(QUEUE_KEY, *members)
	return sorted(m.decode() if isinstance(m, bytes) else str(m) for m in members)


# ---------------------------------------------------------------------------------------------
# Sending


def submit_queue():
	"""Every ten minutes (hooks.py cron): one request per site, for what piled up."""
	key = active_key()
	if not key:
		return
	routes = take_queue()
	if not routes:
		return
	from webshop.webshop.multi_site import site_is_business_only, site_url
	from webshop.webshop.seo.feeds.google import feed_sites, serving

	for site in feed_sites():
		with serving(site):
			if site_is_business_only():
				continue
			urls = [site_url("/" + route) for route in routes]
			key_location = site_url(f"/{key}.txt")
		host = urlparse(key_location).netloc
		for start in range(0, len(urls), BATCH_LIMIT):
			send(host, key, key_location, urls[start : start + BATCH_LIMIT])


def send(host, key, key_location, urls) -> bool:
	payload = {"host": host, "key": key, "keyLocation": key_location, "urlList": urls}
	try:
		response = requests.post(ENDPOINT, json=payload, timeout=TIMEOUT)
	except requests.RequestException as error:
		frappe.log_error("IndexNow: request failed", f"{host}: {error}")
		return False
	# 200 received, 202 received while the engine checks the key
	if response.status_code not in (200, 202):
		frappe.log_error("IndexNow: notification refused", f"{host}: HTTP {response.status_code}\n{response.text[:1000]}")
		return False
	return True


# ---------------------------------------------------------------------------------------------
# The key's file


class KeyRenderer(BaseRenderer):
	"""/<key>.txt on every site: the key, so an engine can check a notification is the site's."""

	def can_render(self):
		key = active_key()
		return bool(key) and self.path == f"{key}.txt"

	def render(self):
		response = Response(active_key() or "", mimetype="text/plain")
		response.charset = "utf-8"
		return response
