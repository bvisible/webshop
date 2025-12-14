# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import json

import frappe
from frappe.utils import cint, cstr
from redis.commands.search.query import Query

from webshop.webshop.redisearch_utils import (
	WEBSITE_ITEM_CATEGORY_AUTOCOMPLETE,
	WEBSITE_ITEM_INDEX,
	WEBSITE_ITEM_NAME_AUTOCOMPLETE,
	is_redisearch_enabled,
)
from webshop.webshop.shopping_cart.product_info import set_product_info_for_website
from webshop.webshop.doctype.override_doctype.item_group import get_item_for_list_in_html

no_cache = 1


def get_context(context):
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

	# search term condition
	if search:
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
					or web_long_description like %(search)s)"""
			search_params = {"search": "%" + cstr(search) + "%"}
	else:
		search_params = {}

	# order by
	query += """ ORDER BY ranking desc, modified desc limit %s offset %s""" % (
		cint(limit),
		cint(start),
	)

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
	"""Search products with priority: name > item_code > description.

	Uses SQL search for comprehensive results across all fields.
	RediSearch autocomplete is limited to product names only.
	"""
	search_results = {"from_redisearch": False, "results": []}

	if not query:
		return search_results

	query = cstr(query).strip()
	if not query:
		return search_results

	# Use comprehensive SQL search for better results
	# This searches in: web_item_name, item_name, item_code, brand, description
	# with proper ordering (name matches first, then item_code, then description)
	search_pattern = f"%{query}%"

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
				WHEN web_long_description LIKE %(search)s THEN 5
				ELSE 6
			END as match_priority
		FROM `tabWebsite Item`
		WHERE published = 1
		AND (
			web_item_name LIKE %(search)s
			OR item_name LIKE %(search)s
			OR item_code LIKE %(search)s
			OR brand LIKE %(search)s
			OR web_long_description LIKE %(search)s
		)
		ORDER BY match_priority ASC, ranking DESC, modified DESC
		LIMIT %(limit)s
	"""

	results = frappe.db.sql(sql_query, {
		"search": search_pattern,
		"limit": cint(limit)
	}, as_dict=1)

	# Remove the match_priority field from results (internal use only)
	for r in results:
		r.pop("match_priority", None)

	search_results["results"] = results
	return search_results


def clean_up_query(query):
	return "".join(c for c in query if c.isalnum() or c.isspace())


def convert_to_dict(redis_search_doc):
	return redis_search_doc.__dict__


@frappe.whitelist(allow_guest=True)
def get_category_suggestions(query):
	search_results = {"results": []}

	if not is_redisearch_enabled():
		# Redisearch module not enabled, query db
		categories = frappe.db.get_all(
			"Item Group",
			filters={"name": ["like", "%{0}%".format(query)], "show_in_website": 1},
			fields=["name", "route"],
		)
		search_results["results"] = categories
		return search_results

	if not query:
		return search_results

	ac = frappe.cache().ft()
	suggestions = ac.sugget(WEBSITE_ITEM_CATEGORY_AUTOCOMPLETE, query, num=10, with_payloads=True)

	results = [json.loads(s.payload) for s in suggestions]

	search_results["results"] = results

	return search_results
