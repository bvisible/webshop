# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import json

import frappe
from frappe.utils import cint, cstr
from webshop.webshop.shopping_cart.product_info import set_product_info_for_website
from webshop.webshop.doctype.override_doctype.item_group import get_item_for_list_in_html

no_cache = 1


# //// Neoffice — _ imported for the page title (9953f79418, 2026-08-26).
from frappe import _


def get_context(context):
	# //// Neoffice — themes print context.title as the visible page heading
	# //// and as the last breadcrumb, and Frappe defaults it to the route
	# //// name — untranslated. A French shop read "product-search" on screen while
	# //// its browser tab said the translated title.
	context.title = _("Product Search")
	context.show_search = True


@frappe.whitelist(allow_guest=True)
def get_product_list(search=None, start=0, limit=12):
	data = get_product_data(search, start, limit)

	for item in data:
		set_product_info_for_website(item)

	return [get_item_for_list_in_html(r) for r in data]


def get_product_data(search=None, start=0, limit=12):
	# limit = 12 because we show 12 items in the grid view
	# base query
	query = """
		SELECT
			web_item_name, item_name, item_code, brand, route,
			website_image, thumbnail, item_group,
			description, web_long_description as website_description,
			website_warehouse, ranking
		FROM `tabWebsite Item`
		WHERE published = 1
		"""

	# //// Neoffice multi-site: scope the grid search to the current site
	from webshop.webshop.multi_site import site_sql_condition

	query += site_sql_condition("`tabWebsite Item`")

	# search term condition
	if search:
		# //// Neoffice — upstream searches name, web name, brand and long description. An exact
		# //// item_code wins outright (a buyer pasting a reference), and otherwise the item
		# //// code, the item group and the short description are searched too — the fields the
		# //// AJAX dropdown already searched, so the two disagreed (87cde0532f, 2025-06-24;
		# //// e5c9f74cf0, 2025-12-15).
		# First check if search term matches an exact item_code
		exact_match = frappe.db.exists("Website Item", {"item_code": cstr(search), "published": 1})
		if exact_match:
			query += """ and item_code = %(exact_search)s"""
			search_params = {"exact_search": cstr(search)}
		else:
			query += """ and (item_name like %(search)s
					or web_item_name like %(search)s
					or item_code like %(search)s
					or brand like %(search)s
					or item_group like %(search)s
					or description like %(search)s
					or web_long_description like %(search)s)"""
			search_params = {"search": "%" + cstr(search) + "%"}
	else:
		search_params = {}

	# order by
	query += """ ORDER BY ranking desc, modified desc limit %s offset %s""" % (
		cint(limit),
		cint(start),
	)

	# //// Neoffice — the parameters follow the branch chosen above.
	return frappe.db.sql(query, search_params, as_dict=1)  # nosemgrep


@frappe.whitelist(allow_guest=True)
def search(query):
	product_results = product_search(query)
	category_results = get_category_suggestions(query)

	return {
		"product_results": product_results.get("results") or [],
		"category_results": category_results.get("results") or [],
	}


@frappe.whitelist(allow_guest=True)
def product_search(query, limit=10, fuzzy_search=True):
	# //// Neoffice — RediSearch is REMOVED from this fork (tracker #223): it was
	# //// disabled in 2025-12-15 (c54680b459 / e580d79023) because its autocomplete
	# //// only indexed product names — narrower than what this dropdown must find —
	# //// and the index had to be rebuilt after every clear-cache. No fleet bench
	# //// carried an index any more (measured 2026-09-05). Upstream still ships the
	# //// feature, so these files conflict at the next merge: take OURS, the module
	# //// is gone. `from_redisearch` stays in the payload — no front end in this repo
	# //// reads it, but an instance's own script might, and the key costs nothing.
	"""Search products with priority: name > item_code > description.

	Uses SQL search for comprehensive results across all fields.
	RediSearch autocomplete is limited to product names only.
	"""
	# //// Neoffice — always False, kept for the payload contract (see above).
	search_results = {"from_redisearch": False, "results": []}

	if not query:
		return search_results

	# //// Neoffice — the query is trimmed before use.
	query = cstr(query).strip()
	if not query:
		return search_results

	# //// Neoffice — the SQL search replaces the RediSearch query (see above).
	# Use comprehensive SQL search for better results
	# This searches in: web_item_name, item_name, item_code, brand, item_group, description
	# with proper ordering (name matches first, then item_code, then description)
	search_pattern = f"%{query}%"

	# //// Neoffice multi-site: scope the live search to the current site
	from webshop.webshop.multi_site import site_sql_condition

	site_condition = site_sql_condition("`tabWebsite Item`")

	# //// Neoffice — one statement with a CASE that ranks the match: name first, then item
	# //// code, then description, so the dropdown offers the obvious answer first
	# //// (bfbe33fc4d, 2025-12-15). The site condition scopes it to the website profile
	# //// being browsed (8a593a948a, 2026-07-08).
	sql_query = """
		SELECT
			web_item_name, item_name, item_code, brand, route,
			website_image, thumbnail, item_group, description,
			web_long_description as website_description,
			website_warehouse, ranking,
			CASE
				WHEN web_item_name LIKE %(search)s THEN 1
				WHEN item_name LIKE %(search)s THEN 2
				WHEN item_code LIKE %(search)s THEN 3
				WHEN brand LIKE %(search)s THEN 4
				WHEN item_group LIKE %(search)s THEN 5
				WHEN description LIKE %(search)s THEN 6
				WHEN web_long_description LIKE %(search)s THEN 7
				ELSE 8
			END as match_priority
		FROM `tabWebsite Item`
		WHERE published = 1
		{site_condition}
		AND (
			web_item_name LIKE %(search)s
			OR item_name LIKE %(search)s
			OR item_code LIKE %(search)s
			OR brand LIKE %(search)s
			OR item_group LIKE %(search)s
			OR description LIKE %(search)s
			OR web_long_description LIKE %(search)s
		)
		ORDER BY match_priority ASC, ranking DESC, modified DESC
		LIMIT %(limit)s
	""".format(site_condition=site_condition)

	# //// Neoffice — the ordering is done by SQL now (see above).
	results = frappe.db.sql(sql_query, {
		"search": search_pattern,
		"limit": cint(limit)
	}, as_dict=1)

	# //// Neoffice — match_priority is an internal column; it never leaves the endpoint.
	# Remove the match_priority field from results (internal use only)
	for r in results:
		r.pop("match_priority", None)

	# //// Neoffice — the SQL rows are returned as-is; upstream re-sorted the RediSearch
	# //// documents by ranking in Python, which the ORDER BY above now does.
	search_results["results"] = results
	return search_results


def clean_up_query(query):
	return "".join(c for c in query if c.isalnum() or c.isspace())


@frappe.whitelist(allow_guest=True)
def get_category_suggestions(query):
	search_results = {"results": []}

	# //// Neoffice — RediSearch is gone from this fork (tracker #223): the module was
	# //// disabled since 2025-12-15 and no fleet site carried an index (measured
	# //// 2026-09-05, FT._LIST on every bench). This is the branch that always ran.
	categories = frappe.db.get_all(
		"Item Group",
		filters={"name": ["like", "%{0}%".format(query)], "show_in_website": 1},
		fields=["name", "route"],
	)
	search_results["results"] = categories
	return search_results
