"""Multi-site filtering for Website Items (Neoffice).

A Website Item can be scoped to specific websites through the
``neo_website_profiles`` child table (doctype "Website Item Site", shipped by
neoffice_theme). Convention: NO rows = the item is visible on ALL sites, so
nothing changes for existing catalogs.

Fleet-safety contract: every helper degrades to a no-op (empty condition /
empty list) when no Website Profile is resolved for the request or when the
child table does not exist on the site.
"""

import frappe

CHILD_TABLE = "Website Item Site"


def get_current_profile_name() -> str | None:
	return getattr(frappe.local, "website_profile", None)


def effective_price_list(fallback: str | None = None) -> str | None:
	"""Price list to use for the site currently being browsed.

	The resolved Website Profile wins; otherwise the caller's fallback, or the
	Webshop Settings default. Returns None when nothing is configured.

	Every place that shows a price to a shopper must go through this. Reading
	``Webshop Settings.price_list`` directly is how the B2B domain ended up
	listing 199.00 in the catalogue while search, carousels and the cart all
	quoted 549.00 — the same item, the same page, three different prices.
	"""
	profile = getattr(frappe.local, "website_profile_doc", None)
	if profile and profile.get("price_list"):
		return profile["price_list"]
	if fallback:
		return fallback
	return frappe.db.get_single_value("Webshop Settings", "price_list")


def site_url(path: str = "") -> str:
	"""Absolute URL on the current site's domain. Falls back to frappe's
	get_url when no Website Profile is resolved (fleet default)."""
	if path and path.startswith(("http://", "https://")):
		return path
	profile = getattr(frappe.local, "website_profile_doc", None)
	if profile and profile.get("primary_domain"):
		clean = (path or "").lstrip("/")
		base = f"https://{profile['primary_domain']}"
		return f"{base}/{clean}" if clean else base
	from frappe.utils import get_url
	return get_url(path)


def _table_exists() -> bool:
	try:
		return frappe.db.table_exists(CHILD_TABLE)
	except Exception:
		return False


def is_active() -> bool:
	"""Site filtering is active when a profile is resolved AND the table exists."""
	return bool(get_current_profile_name()) and _table_exists()


def excluded_item_names() -> list[str]:
	"""Website Item names restricted to OTHER sites (hidden on the current one).

	Small by construction: only items with an explicit site restriction appear
	here. Meant for ORM paths — ``filters.append(["name", "not in", ...])``.
	"""
	if not is_active():
		return []
	profile = get_current_profile_name()
	return frappe.db.sql_list(
		"""
		SELECT wis.parent
		FROM `tabWebsite Item Site` wis
		WHERE wis.parenttype = 'Website Item'
		GROUP BY wis.parent
		HAVING SUM(wis.website_profile = %s) = 0
		""",
		(profile,),
	)


def site_sql_predicate(alias: str = "wi") -> str:
	"""Bare SQL predicate "(...)" scoping a Website Item alias to the current
	site — for hand-built condition lists. Empty string when inactive."""
	if not is_active():
		return ""
	profile = frappe.db.escape(get_current_profile_name())
	return (
		f"(NOT EXISTS (SELECT 1 FROM `tabWebsite Item Site` nws"
		f" WHERE nws.parenttype = 'Website Item' AND nws.parent = {alias}.name)"
		f" OR EXISTS (SELECT 1 FROM `tabWebsite Item Site` nws"
		f" WHERE nws.parenttype = 'Website Item' AND nws.parent = {alias}.name"
		f" AND nws.website_profile = {profile}))"
	)


def site_sql_condition(alias: str = "wi") -> str:
	"""SQL fragment (starting with " AND ...") scoping a Website Item alias to
	the current site. Empty string when filtering is inactive."""
	predicate = site_sql_predicate(alias)
	return f" AND {predicate}" if predicate else ""


@frappe.whitelist()
def get_active_website_profiles() -> list[dict]:
	"""Sites available for the publish dialog. Empty when multi-site is off
	(no Website Profile doctype or no enabled profile) — callers then keep
	the single-site behavior untouched."""
	try:
		if not frappe.db.exists("DocType", "Website Profile"):
			return []
		return frappe.get_all(
			"Website Profile",
			filters={"enabled": 1},
			fields=["name", "title", "is_default"],
			order_by="is_default desc, title asc",
		)
	except Exception:
		return []


@frappe.whitelist()
def set_website_item_sites(website_item: str, sites=None):
	"""Replace the Website Item's site rows. Empty/None = visible on ALL
	sites (the base behavior)."""
	import json

	if isinstance(sites, str):
		sites = json.loads(sites or "[]")
	doc = frappe.get_doc("Website Item", website_item)
	if not hasattr(doc, "neo_website_profiles"):
		return
	doc.set("neo_website_profiles", [])
	for site in sites or []:
		doc.append("neo_website_profiles", {"website_profile": site})
	doc.save()
