# //// Neoffice — added file (no upstream equivalent). A page whose address changes leaves a
# //// permanent redirect behind it.
"""Changing the route of a product or a category used to turn the old address into a 404.

Frappe keeps no history of routes (`WebsiteGenerator.on_update` only drops the old route from
the search index), so every bookmark, every link from another site and the page Google had
indexed died at the first rename. The old route now goes to Website Settings' route redirects
as a 301, which Frappe's path resolver already serves (`path_resolver.resolve_redirect`).

The rows are written directly rather than through `WebsiteSettings.save()`: that save
validates the whole document (home page, menus…), and a site with one stale setting would
then refuse to save a product because of it. A redirect that cannot be written is logged,
never raised: saving the product matters more.
"""

import re

import frappe

PARENT = "Website Settings"
FIELD = "route_redirects"
CHILD = "Website Route Redirect"


def remember_old_route(doc, method=None):
	"""doc_events hook (Website Item, Item Group, on_update): redirect the route it just left."""
	before = doc.get_doc_before_save()
	if not before:
		return
	old_route = (before.get("route") or "").strip("/ ")
	new_route = (doc.get("route") or "").strip("/ ")
	if not old_route or not new_route or old_route == new_route:
		return
	try:
		add_route_redirect(old_route, new_route)
	except Exception:
		frappe.log_error("Route redirect not recorded", frappe.get_traceback())


def add_route_redirect(old_route, new_route):
	"""A 301 from `old_route` to `new_route`, with no chain and no loop left behind."""
	old_route, new_route = old_route.strip("/ "), new_route.strip("/ ")
	# Frappe matches a source as a regular expression (`re.match(source + "$", path)`).
	source = re.escape(old_route)
	target = "/" + new_route
	rows = frappe.get_all(
		CHILD,
		filters={"parent": PARENT, "parenttype": PARENT, "parentfield": FIELD},
		fields=["name", "source", "target", "idx"],
	)
	for row in rows:
		row_source = (row.source or "").strip("/ ")
		# The page comes back to an address it used to have: that redirect would now loop.
		if row_source in (re.escape(new_route), new_route):
			frappe.db.delete(CHILD, {"name": row.name})
		# Whatever led to the old address leads straight to the new one: no chain.
		elif (row.target or "").strip("/ ") == old_route:
			frappe.db.set_value(CHILD, row.name, "target", target, update_modified=False)
	if not any((row.source or "").strip("/ ") == source for row in rows):
		frappe.get_doc(
			{
				"doctype": CHILD,
				"parent": PARENT,
				"parenttype": PARENT,
				"parentfield": FIELD,
				"idx": max([row.idx or 0 for row in rows] or [0]) + 1,
				"source": source,
				"target": target,
				"redirect_http_status": "301",
			}
		).db_insert()
	# Frappe remembers every redirect decision it took, per path: forget them.
	frappe.cache.delete_key("website_redirects")
