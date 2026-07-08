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


def site_sql_condition(alias: str = "wi") -> str:
	"""SQL fragment (starting with " AND ...") scoping a Website Item alias to
	the current site. Empty string when filtering is inactive."""
	if not is_active():
		return ""
	profile = frappe.db.escape(get_current_profile_name())
	return (
		f" AND (NOT EXISTS (SELECT 1 FROM `tabWebsite Item Site` nws"
		f" WHERE nws.parenttype = 'Website Item' AND nws.parent = {alias}.name)"
		f" OR EXISTS (SELECT 1 FROM `tabWebsite Item Site` nws"
		f" WHERE nws.parenttype = 'Website Item' AND nws.parent = {alias}.name"
		f" AND nws.website_profile = {profile}))"
	)
