# //// Neoffice — added file (no upstream equivalent)
"""The shop's door to the theme's localized content (multilingual lot 1, neoffice-maintenance#2029).

Translations of the shop's data (product names and texts) live in the theme (`neoffice_theme.localized`),
which also decides the language of the request. The shop calls this façade only: without the theme, or
on a site that enabled no additional language, every function is a no-op and the page is the source's.

A failure of the translation layer costs the translation, never the page.
"""

import frappe


def _engine():
	try:
		from neoffice_theme import localized
	except ImportError:
		return None
	return localized


def content_language():
	"""The additional language of this request, or None for the site's own."""
	engine = _engine()
	if engine is None:
		return None
	try:
		return engine.content_language()
	except Exception:  # noqa: BLE001 — see the module docstring
		frappe.log_error("Localized content: language resolution failed", frappe.get_traceback())
		return None


def cache_suffix():
	"""Append to the key of any cache that holds localized text. Empty in the site's own language."""
	lang = content_language()
	return f":{lang}" if lang else ""


def localize_rows(doctype, rows, fieldnames, name_field="name"):
	"""Replace, in place, the listed fields of each row by their translation when there is one to show."""
	engine = _engine()
	if engine is None or not rows:
		return rows
	try:
		return engine.localize_rows(doctype, rows, fieldnames, name_field)
	except Exception:  # noqa: BLE001 — see the module docstring
		frappe.log_error("Localized content: bulk read failed", frappe.get_traceback())
		return rows


def localize_value(doctype, name, fieldname, default=None):
	engine = _engine()
	if engine is None:
		return default
	try:
		return engine.localize_value(doctype, name, fieldname, default)
	except Exception:  # noqa: BLE001 — see the module docstring
		frappe.log_error("Localized content: read failed", frappe.get_traceback())
		return default


def localize_items(rows, fieldnames=("web_item_name", "short_description")):
	"""Like localize_rows, for rows that name a Website Item by its item code (recommendations, carousels)."""
	if not rows or content_language() is None:
		return rows
	codes = [r.get("item_code") for r in rows if r.get("item_code")]
	if not codes:
		return rows
	names = dict(frappe.get_all("Website Item", filters={"item_code": ["in", codes]}, fields=["item_code", "name"], as_list=True))
	for row in rows:
		row["_website_item"] = names.get(row.get("item_code"))
	try:
		localize_rows("Website Item", rows, list(fieldnames), name_field="_website_item")
	finally:
		for row in rows:
			row.pop("_website_item", None)
	return rows
