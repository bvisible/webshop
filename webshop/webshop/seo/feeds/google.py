# //// Neoffice — added file (no upstream equivalent): the product feed Google Merchant Center
# //// collects, one per site. neoffice-maintenance#691 (lot 3), 2026-09-24.
"""The Google Merchant Center feed of each site: RSS 2.0 with Google's `g:` attributes.

Google fetches the file once a day, reloads the product pages and compares them with it: an item
is refused over a cent or an "in stock" of difference, and an account whose feed keeps
disagreeing with its pages is suspended. So the feed says what the page says, read the same way
(seo/facts.py for the offer, seo/availability.py for the stock), priced as a visitor with no
account sees it, since Google's crawler is one. A model's page prints no price: its published
variants are the items, tied by `item_group_id`.

Nothing is computed while Google fetches. A nightly job and the button of Webshop Settings write
each site's file; the route (FeedRenderer) serves it, behind the settings' token.
"""

import hmac
import os
import re
from contextlib import contextmanager
from xml.sax.saxutils import escape

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime
from frappe.website.page_renderers.base_renderer import BaseRenderer
from werkzeug.wrappers import Response

from webshop.webshop.seo.availability import BACK_ORDER, IN_STOCK, OUT_OF_STOCK

FEED_ROUTE = "feeds/google.xml"
FEED_DONE_EVENT = "webshop_google_feed_done"
GOOGLE_NAMESPACE = "http://base.google.com/ns/1.0"
MAX_ADDITIONAL_IMAGES = 10
MAX_ID = 50
MAX_TITLE = 150
MAX_DESCRIPTION = 5000
MAX_PRODUCT_TYPE = 750
AVAILABILITY = {IN_STOCK: "in_stock", OUT_OF_STOCK: "out_of_stock", BACK_ORDER: "backorder"}
CONDITION = {"New": "new", "Refurbished": "refurbished", "Second-hand": "used"}
# The names shops give their variant attributes, in the fleet's languages, by Google attribute.
# A shop's own names go in Webshop Settings (google_feed_attribute_map).
ATTRIBUTE_NAMES = {
	"color": ("color", "colour", "couleur", "farbe", "colore", "coloris"),
	"size": ("size", "taille", "grösse", "grosse", "größe", "taglia", "pointure"),
	"material": ("material", "matière", "matiere", "materiale", "stoff"),
	"pattern": ("pattern", "motif", "muster", "motivo"),
	"gender": ("gender", "genre", "geschlecht", "sexe"),
	"age_group": ("age group", "tranche d'âge", "altersgruppe"),
}
WEIGHT_UNITS = {"kg": "kg", "g": "g", "gram": "g", "kilogram": "kg", "lb": "lb", "oz": "oz"}



def reason_label(reason: str) -> str:
	"""Why an item is not in the feed, as the report of Webshop Settings says it."""
	return {
		"model": _("a model: its published variants are the items"),
		"gift_card": _("a gift card"),
		"service": _("a bookable service"),
		"second_hand_off": _("a second-hand unit, not sent"),
		"excluded": _("excluded by the merchant (the item or its group)"),
		"no_price": _("no price shown to a visitor"),
		"no_image": _("no picture"),
		"id_too_long": _("an item code longer than 50 characters"),
		"error": _("an error, see the Error Log"),
	}.get(reason, reason)


# What would make a sent item's listing better (the report Catalogue Ready for Google, lot 6).
# Google's own thresholds: a description is worth 500 characters and more; 150 is where a listing
# starts to say something. A picture should be 800 px on each side.
SHORT_DESCRIPTION = 150
GOOD_PICTURE = 800


def entry_warnings(entry: dict, doc, first_picture: str | None = None) -> list[str]:
	"""What the feed's item lacks to be shown at its best, as codes (warning_label)."""
	from webshop.webshop.utils.renditions import picture_size

	warnings = []
	if entry.get("identifier_exists") == "no":
		warnings.append("no_identifier")
	if not entry.get("brand"):
		warnings.append("no_brand")
	description = (entry.get("description") or "").strip()
	if len(description) < SHORT_DESCRIPTION or description == (entry.get("title") or "").strip():
		warnings.append("short_description")
	if len(doc.get("web_item_name") or "") > MAX_TITLE:
		warnings.append("title_cut")
	if not entry.get("additional_image_link"):
		warnings.append("one_picture")
	size = picture_size(first_picture) if first_picture else None
	if size and min(size) < GOOD_PICTURE:
		warnings.append("small_picture")
	if not entry.get("google_product_category"):
		warnings.append("no_category")
	return warnings


def warning_label(code: str) -> str:
	"""What would make the listing better, as the report says it."""
	return {
		"no_identifier": _("no GTIN or MPN: Google shows a branded product less often without one"),
		"no_brand": _("no brand"),
		"short_description": _("a description under {0} characters").format(SHORT_DESCRIPTION),
		"title_cut": _("a name longer than {0} characters, cut in the feed").format(MAX_TITLE),
		"one_picture": _("a single picture: add other views"),
		"small_picture": _("a main picture under {0} px").format(GOOD_PICTURE),
		"no_category": _("no Google product category on its item group"),
	}.get(code, code)


# ---------------------------------------------------------------------------------------------
# The sites


def feed_sites() -> list[frappe._dict]:
	"""Every site a feed is written for: each Website Profile with a domain, or the instance's
	single site. A professional-only site, or one that hides its prices from visitors, has none:
	Google Shopping serves the public, and Google's crawler sees the visitor's page."""
	sites = []
	try:
		from neoffice_theme.website_profiles import get_profiles_map

		profiles = {profile["name"]: profile for profile in (get_profiles_map() or {}).values()}
	except Exception:
		profiles = {}
	for profile in profiles.values():
		if not profile.get("primary_domain"):
			continue
		sites.append(frappe._dict(key=site_key(profile["name"]), profile=profile))
	if not sites:
		sites.append(frappe._dict(key="default", profile=None))
	return sites


def site_key(name: str) -> str:
	"""A Website Profile's name as a file name: lowercase letters, digits and underscores, so no
	name can lead the feed's path out of its folder (frappe.scrub keeps "/" and "..")."""
	return re.sub(r"[^a-z0-9_]+", "_", frappe.scrub(name)).strip("_") or "site"


@contextmanager
def serving(site):
	"""Compute as if a visitor with no account browsed `site`: its profile, its price list.

	In a job, a test or the console only. frappe.set_user rewrites the session object it runs in
	(its sid becomes the user's name, its data is emptied), and in a web request that object is the
	live session of whoever made the request, written back to the cache when the request ends."""
	if getattr(frappe.local, "session_obj", None):
		raise RuntimeError("seo.feeds.google.serving() switches the user: never inside a web request")
	saved = (
		getattr(frappe.local, "website_profile", None),
		getattr(frappe.local, "website_profile_doc", None),
		frappe.session.user,
	)
	profile = site.profile
	frappe.local.website_profile = profile["name"] if profile else None
	frappe.local.website_profile_doc = profile
	# the guard above keeps both switches out of web requests
	frappe.set_user("Guest")  # nosemgrep: frappe-semgrep-rules.rules.security.frappe-setuser
	try:
		yield
	finally:
		frappe.local.website_profile, frappe.local.website_profile_doc = saved[0], saved[1]
		frappe.set_user(saved[2])  # nosemgrep: frappe-semgrep-rules.rules.security.frappe-setuser


def site_refusal(settings) -> str | None:
	"""Why this site has no feed at all, or None."""
	from webshop.webshop.multi_site import site_is_business_only

	if not settings.get("enabled"):
		return _("the shopping cart is disabled")
	if not settings.get("show_price") or settings.get("hide_price_for_guest"):
		return _("prices are hidden from visitors")
	if site_is_business_only():
		return _("the site serves business accounts only")
	return None


# ---------------------------------------------------------------------------------------------
# The items


def feed_candidates() -> list[str]:
	"""Published Website Items of this site that are still for sale (a sold used unit left the
	catalogue), in a stable order."""
	from webshop.webshop.multi_site import excluded_item_names

	excluded = set(excluded_item_names() or [])
	names = frappe.get_all(
		"Website Item", filters={"published": 1, "sold": 0}, pluck="name", order_by="item_code asc"
	)
	return [name for name in names if name not in excluded]


def excluded_groups() -> set[str]:
	"""Item groups the merchant keeps out of the feed, with every group below them (a case on the
	parent covers the subtree: airsoft replicas and all their parts)."""
	if not frappe.get_meta("Item Group").has_field("exclude_from_google_shopping"):
		return set()
	roots = frappe.get_all(
		"Item Group", filters={"exclude_from_google_shopping": 1}, fields=["lft", "rgt"]
	)
	groups = set()
	for root in roots:
		groups.update(
			frappe.get_all(
				"Item Group", filters={"lft": (">=", root.lft), "rgt": ("<=", root.rgt)}, pluck="name"
			)
		)
	return groups


def google_category(item_group: str | None) -> str:
	"""The Google product category of the group, or of its nearest ancestor that has one."""
	if not item_group or not frappe.get_meta("Item Group").has_field("google_product_category"):
		return ""
	bounds = frappe.db.get_value("Item Group", item_group, ["lft", "rgt"], as_dict=True)
	if not bounds:
		return ""
	rows = frappe.get_all(
		"Item Group",
		filters={"lft": ("<=", bounds.lft), "rgt": (">=", bounds.rgt), "google_product_category": ("is", "set")},
		fields=["google_product_category"],
		order_by="lft desc",
		limit=1,
	)
	return (rows[0].google_product_category or "").strip() if rows else ""


def attribute_map(settings) -> dict[str, str]:
	"""Item attribute name (lower case) → Google attribute: the common names, then the shop's."""
	mapping = {name: google for google, names in ATTRIBUTE_NAMES.items() for name in names}
	for line in (settings.get("google_feed_attribute_map") or "").splitlines():
		name, _sep, google = line.partition("=")
		name, google = name.strip().lower(), google.strip().lower()
		if name and google in ATTRIBUTE_NAMES:
			mapping[name] = google
	return mapping


def is_service(item_code: str) -> bool:
	return bool(
		frappe.db.exists("DocType", "Booking Profile")
		and frappe.db.get_value("Booking Profile", {"item": item_code, "enabled": 1}, "name")
	)


def item_entry(doc, settings, excluded, mapping) -> tuple[dict | None, str | None]:
	"""The feed's item for a Website Item, or the reason it has none."""
	from frappe.website.doctype.website_slideshow.website_slideshow import get_slideshow

	from webshop.webshop.multi_site import site_url
	from webshop.webshop.seo.availability import schema_availability
	from webshop.webshop.seo.facts import (
		absolute_url,
		category_path,
		gallery_images,
		offer_facts,
		product_identifiers,
	)
	from webshop.webshop.seo.text import html_to_text
	from webshop.webshop.shopping_cart.product_info import get_product_info_for_website
	from webshop.webshop.utils.used_items import is_second_hand

	if doc.get("has_variants"):
		return None, "model"
	if doc.get("is_gift_card"):
		return None, "gift_card"
	if is_service(doc.item_code):
		return None, "service"
	if is_second_hand(doc.get("item_condition")) and not cint(settings.get("google_feed_include_second_hand")):
		return None, "second_hand_off"
	if cint(doc.get("exclude_from_google_shopping")) or doc.item_group in excluded:
		return None, "excluded"
	if len(doc.item_code) > MAX_ID:
		return None, "id_too_long"

	url = site_url(doc.route)
	context = frappe._dict(shopping_cart=get_product_info_for_website(doc.item_code, skip_quotation_creation=True))
	if doc.slideshow:
		context.update(get_slideshow(doc))
	availability = schema_availability(doc.item_code, context.shopping_cart.cart_settings)
	offer = offer_facts(doc, context, url, availability)
	if not offer:
		return None, "no_price"
	images = [absolute_url(image) for image in gallery_images(doc, context)]
	if not images:
		return None, "no_image"

	entry = {
		"id": doc.item_code,
		"title": (doc.web_item_name or doc.item_code)[:MAX_TITLE],
		"description": html_to_text(doc.web_long_description or doc.description or "", MAX_DESCRIPTION)
		or doc.web_item_name,
		"link": url,
		"image_link": images[0],
		"additional_image_link": images[1 : 1 + MAX_ADDITIONAL_IMAGES],
		"availability": AVAILABILITY.get(availability, "out_of_stock"),
		"condition": CONDITION.get(doc.get("item_condition") or "New", "new"),
	}
	# A description Nora proposed and the merchant kept is declared as such: Merchant Center asks
	# that text made with generative AI come as structured_description, marked
	# trained_algorithmic_media (#691 lot 6). Only when it IS the description sent: a product
	# without one sends its name, which nobody generated.
	if doc.get("description_ai_assisted") and html_to_text(doc.web_long_description or "", 1):
		entry["structured_description"] = {
			"digital_source_type": "trained_algorithmic_media",
			"content": entry["description"],
		}
	# The page's struck price is `price` and what the buyer pays is `sale_price` (Google).
	if offer.struck_price:
		entry["price"] = money(offer.struck_price, offer.currency)
		entry["sale_price"] = money(offer.price, offer.currency)
		if offer.valid_from and offer.valid_until:
			entry["sale_price_effective_date"] = f"{offer.valid_from}/{offer.valid_until}"
	else:
		entry["price"] = money(offer.price, offer.currency)
	if doc.brand:
		entry["brand"] = doc.brand
	identifiers = product_identifiers(doc.item_code)
	gtin = next((value for key, value in identifiers.items() if key.startswith("gtin")), None)
	if gtin:
		entry["gtin"] = gtin
	if identifiers.get("mpn"):
		entry["mpn"] = identifiers["mpn"]
	if not gtin and not identifiers.get("mpn"):
		entry["identifier_exists"] = "no"
	if doc.get("variant_of"):
		entry["item_group_id"] = doc.variant_of
	entry.update(variant_attributes(doc.item_code, mapping))
	product_type = category_path(doc.item_group)
	if product_type:
		entry["product_type"] = product_type[:MAX_PRODUCT_TYPE]
	category = google_category(doc.item_group)
	if category:
		entry["google_product_category"] = category
	weight = shipping_weight(doc.item_code)
	if weight:
		entry["shipping_weight"] = weight
	return entry, None


def money(amount, currency) -> str:
	return f"{flt(amount, 2):.2f} {currency}"


def variant_attributes(item_code: str, mapping: dict) -> dict:
	found = {}
	for row in frappe.get_all(
		"Item Variant Attribute", filters={"parent": item_code}, fields=["attribute", "attribute_value"]
	):
		google = mapping.get((row.attribute or "").strip().lower())
		if google and row.attribute_value and google not in found:
			found[google] = str(row.attribute_value)[:100]
	return found


def shipping_weight(item_code: str) -> str | None:
	weight, unit = frappe.db.get_value("Item", item_code, ["weight_per_unit", "weight_uom"]) or (0, None)
	unit = WEIGHT_UNITS.get((unit or "").strip().lower())
	return f"{flt(weight, 3):g} {unit}" if flt(weight) > 0 and unit else None


# ---------------------------------------------------------------------------------------------
# The file


def build_feed(site) -> tuple[str | None, frappe._dict]:
	"""The XML of a site's feed and its report: sent, and left out by reason."""
	from webshop.webshop.doctype.webshop_settings.webshop_settings import get_shopping_cart_settings
	from webshop.webshop.multi_site import site_url
	from webshop.webshop.seo.site import shop_name

	with serving(site):
		settings = get_shopping_cart_settings()
		report = frappe._dict(site=site.key, url=site_url("/" + FEED_ROUTE), sent=0, left_out={}, refusal=None)
		refusal = site_refusal(settings)
		if refusal:
			report.refusal = refusal
			return None, report
		excluded = excluded_groups()
		mapping = attribute_map(settings)
		entries = []
		for name in feed_candidates():
			doc = frappe.get_cached_doc("Website Item", name)
			try:
				entry, reason = item_entry(doc, settings, excluded, mapping)
			except Exception:
				frappe.log_error(f"Google feed: item {doc.item_code} failed", frappe.get_traceback())
				entry, reason = None, "error"
			if entry:
				entries.append(entry)
			else:
				report.left_out[reason] = report.left_out.get(reason, 0) + 1
		report.sent = len(entries)
		title = shop_name() or site_url("/")
		return render_xml(entries, title, site_url("/")), report


def render_xml(entries: list[dict], title: str, link: str) -> str:
	lines = [
		'<?xml version="1.0" encoding="UTF-8"?>',
		f'<rss version="2.0" xmlns:g="{GOOGLE_NAMESPACE}">',
		"<channel>",
		f"<title>{escape(title)}</title>",
		f"<link>{escape(link)}</link>",
		f"<description>{escape(title)}</description>",
	]
	for entry in entries:
		lines.append("<item>")
		for key, value in entry.items():
			for single in value if isinstance(value, list) else [value]:
				if isinstance(single, dict):
					# a group of sub-attributes (structured_description)
					inner = "".join(f"<g:{k}>{escape(str(v))}</g:{k}>" for k, v in single.items())
					lines.append(f"<g:{key}>{inner}</g:{key}>")
				else:
					lines.append(f"<g:{key}>{escape(str(single))}</g:{key}>")
		lines.append("</item>")
	lines += ["</channel>", "</rss>", ""]
	return "\n".join(lines)


def feed_path(site_key: str) -> str:
	return frappe.get_site_path("private", "feeds", f"google-{site_key}.xml")


def write_feed(site) -> frappe._dict:
	xml, report = build_feed(site)
	path = feed_path(site.key)
	if xml is None:
		if os.path.exists(path):
			os.remove(path)
		return report
	os.makedirs(os.path.dirname(path), exist_ok=True)
	partial = f"{path}.partial"
	# the path is feed_path(): private/feeds/google-<site_key>.xml, no caller-given part
	with open(partial, "w", encoding="utf-8") as handle:  # nosemgrep: frappe-semgrep-rules.rules.security.frappe-security-file-traversal
		handle.write(xml)
	os.replace(partial, path)
	return report


def generate_feeds(notify: str | None = None):
	"""Every site's feed: the nightly job, and the job the button of Webshop Settings queues,
	which then tells the user who pressed it (`notify`) that the report is there."""
	settings = frappe.get_single("Webshop Settings")
	if not cint(settings.get("enable_google_feed")):
		return []
	# The report is read by a person, in their language: a worker starts in English whatever the
	# site speaks (the button's report came back in English on osiris, 2026-09-24).
	previous_lang = frappe.local.lang
	frappe.set_user_lang(notify or frappe.session.user)
	try:
		reports = []
		for site in feed_sites():
			try:
				reports.append(write_feed(site))
			except Exception:
				frappe.log_error(f"Google feed: site {site.key} failed", frappe.get_traceback())
		report = describe(reports, settings)
	finally:
		frappe.local.lang = previous_lang
	frappe.db.set_single_value(
		"Webshop Settings",
		{"google_feed_generated_on": now_datetime(), "google_feed_report": report},
		update_modified=False,
	)
	if notify:
		frappe.publish_realtime(FEED_DONE_EVENT, report, user=notify, after_commit=True)
	return reports


def describe(reports, settings) -> str:
	"""The report shown in Webshop Settings: per site, the address, what went and what did not."""
	lines = []
	for report in reports:
		lines.append(f"{report.url}?token={settings.google_feed_token}")
		if report.refusal:
			lines.append("  " + _("No feed: {0}").format(report.refusal))
			continue
		lines.append("  " + _("{0} products sent").format(report.sent))
		for reason, count in sorted(report.left_out.items(), key=lambda pair: -pair[1]):
			lines.append("  " + _("{0} left out: {1}").format(count, reason_label(reason)))
	return "\n".join(lines)


@frappe.whitelist()
def generate_now():
	"""Webshop Settings' button. A worker writes the feeds, never this request: pricing as a
	visitor switches the user (serving), which would spoil the session of whoever pressed it."""
	frappe.only_for(("System Manager", "Website Manager"))
	frappe.enqueue(
		"webshop.webshop.seo.feeds.google.generate_feeds",
		queue="long",
		job_id="webshop-google-feed",
		deduplicate=True,
		notify=frappe.session.user,
	)


# ---------------------------------------------------------------------------------------------
# The route


class FeedRenderer(BaseRenderer):
	"""/feeds/google.xml?token=…: the file the nightly job wrote for the site being served.
	Without the feed switched on, the right token and a file, the address does not exist."""

	def can_render(self):
		return self.path == FEED_ROUTE

	def render(self):
		settings = frappe.get_cached_doc("Webshop Settings")
		token = settings.get("google_feed_token") or ""
		sent = str(frappe.form_dict.get("token") or "")
		if not cint(settings.get("enable_google_feed")) or not token or not hmac.compare_digest(sent.encode(), token.encode()):
			return Response(status=404)
		site = next(
			(site for site in feed_sites() if not site.profile or site.profile["name"] == getattr(frappe.local, "website_profile", None)),
			None,
		)
		path = feed_path(site.key) if site else None
		if not path or not os.path.exists(path):
			return Response(status=404)
		# the path is feed_path() of the site being served: nothing in the request names it
		with open(path, "rb") as handle:  # nosemgrep: frappe-semgrep-rules.rules.security.frappe-security-file-traversal
			response = Response(handle.read(), mimetype="application/xml")
		response.charset = "utf-8"
		response.headers["Cache-Control"] = "private, max-age=3600"
		response.headers["X-Robots-Tag"] = "noindex"
		return response
