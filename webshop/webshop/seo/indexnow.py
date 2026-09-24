# //// Neoffice — added file (no upstream equivalent): IndexNow, the protocol through which Bing,
# //// Yandex, Seznam, Naver, Yep and a few others learn that a page changed, instead of waiting
# //// for their next crawl (neoffice-maintenance#691, lot 4). Bing writes that it keeps its AI
# //// answers current from it; Google does not take part.
"""Tell search engines which product pages changed.

- The key sits at the root of every site of the instance, `/<key>.txt` (KeyRenderer): that is how
  an engine checks that a notification comes from the site it names.
- A Website Item saved while published, or withdrawn, and a selling price changed, queue the
  item's page; every ten minutes, one request per site sends what piled up. The queue is a Redis
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


def queue_website_item(doc, method=None):
	"""`doc_events` of Website Item (on_update, on_trash): its page, and the page it had before a
	change of address, which now answers with a redirection the engine should see."""
	before = doc.get_doc_before_save() if method == "on_update" else None
	if not cint(doc.published) and not (before and cint(before.published)):
		return  # never public: no engine knows this page
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
	queue_routes(
		frappe.get_all(
			"Website Item", filters={"item_code": ["in", codes], "published": 1}, pluck="route"
		)
	)


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
