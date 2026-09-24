# //// Neoffice — added file (no upstream equivalent): /llms.txt, a short Markdown card of the shop
# //// for language models (llmstxt.org). neoffice-maintenance#691, lot 4.
"""What the shop is, what it sells and how to reach it, in the few lines a language model reads:
the site's name, its categories and brand pages with their addresses, its delivery and return
promises, its contact, its sitemap.

Never a price: a price copied into an answer outlives the next change. Google says it does not
use the file, and no assistant documents reading it for shopping (study, note 05): it costs
little and nothing is expected of it. A site serving business accounts only has none, as it
shows visitors no catalogue.
"""

import frappe
from frappe import _
from frappe.utils import cint
from frappe.website.page_renderers.base_renderer import BaseRenderer
from werkzeug.wrappers import Response

ROUTE = "llms.txt"
MAX_CATEGORIES = 20
MAX_BRANDS = 30


def llms_txt() -> str | None:
	"""The card of the site being browsed, or None where it has no public catalogue."""
	from webshop.webshop.multi_site import site_is_business_only, site_url
	from webshop.webshop.product_data_engine.brand_pages import brand_page_routes, offered_brands
	from webshop.webshop.seo.site import shop_name
	from webshop.webshop.seo.text import one_line

	if site_is_business_only():
		return None
	name = shop_name() or _("Online shop")
	categories = top_categories()
	total = sum(count for _group, _route, count in categories)
	lines = [f"# {name}", ""]
	if total:
		lines += [
			"> " + _("{0}: an online shop, {1} products in {2} categories.").format(name, total, len(categories)),
			"",
		]
	if categories:
		lines.append(f"## {_('Categories')}")
		lines += [f"- [{group}]({site_url('/' + route)}): {products(count)}" for group, route, count in categories]
		lines.append("")
	brands = offered_brands()
	routes = brand_page_routes() if brands else {}
	if routes:
		lines.append(f"## {_('Brands')}")
		ordered = sorted(routes, key=lambda brand: (-brands.get(brand, 0), brand))[:MAX_BRANDS]
		lines += [f"- [{brand}]({site_url(routes[brand])})" for brand in ordered]
		lines.append("")

	settings = frappe.get_cached_doc("Webshop Settings")
	shopping = []
	if settings.get("delivery_delay"):
		shopping.append("- " + labelled(_("Delivery"), one_line(settings.delivery_delay)))
	if cint(settings.get("return_days")) > 0:
		shopping.append("- " + labelled(_("Returns"), _("{0} days").format(cint(settings.return_days))))
	if settings.get("store_hours"):
		shopping.append(f"- [{_('Store hours')}]({site_url('/store-hours')})")
	if shopping:
		lines += [f"## {_('Delivery and returns')}", *shopping, ""]
	contact = [one_line(settings.get(field)) for field in ("store_email", "store_phone", "store_address")]
	contact = [value for value in contact if value]
	if contact:
		lines += [f"## {_('Contact')}", *(f"- {value}" for value in contact), ""]
	# "Optional" is the llmstxt.org section a model may skip: its name is the format's, not ours
	lines += ["## Optional", f"- [{_('Sitemap')}]({site_url('/sitemap.xml')})", ""]
	return "\n".join(lines)


def products(count: int) -> str:
	return _("one product") if count == 1 else _("{0} products").format(count)


def labelled(label: str, value: str) -> str:
	"""A label and its value as the language writes them: "Returns: 30 days", "Retours : 30 jours"."""
	return _("{0}: {1}", context="A label and its value, as in Returns: 30 days").format(label, value)


def top_categories() -> list[tuple[str, str, int]]:
	"""(group, route, how many products it holds) for the first level of the tree that carries
	something this site shows, fullest first; one level lower when a single group holds it all
	(a shop whose tree is "All > Products > …")."""
	from webshop.webshop.product_data_engine.catalogue_scope import groups_carrying_items

	carried = groups_carrying_items()
	if not carried:
		return []
	# the root of the tree is not a category, and rarely shown on the website: never take the
	# first carried group for it (the categories listed were the children of "Products")
	root = frappe.db.get_value("Item Group", {"lft": 1}, "name")
	groups = frappe.get_all(
		"Item Group", filters={"name": ["in", list(carried)]}, fields=["name", "route", "parent_item_group"]
	)

	def children(parent):
		return [g for g in groups if g.parent_item_group == parent and (g.route or "").strip("/")]

	level = children(root)
	if len(level) == 1 and children(level[0].name):
		level = children(level[0].name)
	return sorted(
		((g.name, g.route.strip("/"), carried[g.name]) for g in level), key=lambda row: (-row[2], row[0])
	)[:MAX_CATEGORIES]


class LlmsTxtRenderer(BaseRenderer):
	"""/llms.txt of the site being browsed."""

	def can_render(self):
		return self.path == ROUTE

	def render(self):
		text = llms_txt()
		if text is None:
			return Response(status=404)
		response = Response(text, mimetype="text/markdown")
		response.charset = "utf-8"
		response.headers["Cache-Control"] = "public, max-age=3600"
		return response
