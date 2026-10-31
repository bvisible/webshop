# //// Neoffice — added file (no upstream equivalent).
"""What a catalogue holds: the products a reseller picked, as this site shows them.

A selection is three short lists: item groups (a group brings its sub-groups), brands, and single
products by item code. A product is in when any of the three says so. Whatever the lists name, the
answer is limited to what the shop shows a visitor (`catalogue_scope.visible_item_filters`: published,
not sold, visible on this site), so a selection can name a product the shop does not offer and get
nothing for it — it never widens what a reseller can see.

The selection is what a browser sends: it is cleaned before anything reads it (lists of short plain
texts, bounded), and nothing in it is a price.
"""

import json

import frappe

from webshop.webshop.product_data_engine.catalogue_scope import visible_item_filters

KEYS = ("item_groups", "brands", "items")
MAX_ENTRIES = 300  # per list: a reseller who ticks more than that wants a category, not 300 names
MAX_NAME = 140  # the longest name Frappe stores for an item group, a brand or an item code
MAX_PRODUCTS = 1500
SEARCH_MIN = 2
SEARCH_LIMIT = 15

FIELDS = [
	"name",
	"item_code",
	"web_item_name",
	"item_name",
	"brand",
	"item_group",
	"website_image",
	"short_description",
	"has_variants",
	"variant_of",
	"route",
]


def scope():
	"""The Website Item filters of what a catalogue may hold: what the shop shows a visitor, gift cards left out
	(the buyer of a gift card picks its amount: a reseller has no price to print for it)."""
	filters = visible_item_filters()
	if frappe.get_meta("Website Item").has_field("is_gift_card"):
		filters["is_gift_card"] = 0
	return filters


class SelectionRefused(ValueError):
	"""A selection that cannot be read; `reason` is one of the short codes `refusals.selection_message` words."""

	def __init__(self, reason):
		super().__init__(reason)
		self.reason = reason


def clean_selection(raw):
	"""The selection as {"item_groups": [...], "brands": [...], "items": [...]}, or SelectionRefused.

	Accepts the dict or its JSON text. Unknown keys are dropped; an entry is a non-empty text of at most
	MAX_NAME characters; a repeated entry counts once; at least one entry is required."""
	if isinstance(raw, str):
		try:
			raw = json.loads(raw)
		except ValueError:
			raise SelectionRefused("not_a_selection") from None
	if not isinstance(raw, dict):
		raise SelectionRefused("not_a_selection")
	clean = {}
	for key in KEYS:
		values = raw.get(key) or []
		if not isinstance(values, (list, tuple)):
			raise SelectionRefused("not_a_list")
		entries = []
		for value in values:
			if not isinstance(value, str):
				raise SelectionRefused("not_text")
			value = value.strip()
			if not value:
				continue
			if len(value) > MAX_NAME:
				raise SelectionRefused("too_long")
			if value not in entries:
				entries.append(value)
		if len(entries) > MAX_ENTRIES:
			raise SelectionRefused("too_many")
		clean[key] = entries
	if not any(clean.values()):
		raise SelectionRefused("empty")
	return clean


def _group_names(groups):
	"""The groups and everything under them (item groups are a tree: a category holds its sub-categories)."""
	if not groups:
		return []
	names = set()
	for row in frappe.get_all("Item Group", filters={"name": ("in", groups)}, fields=["lft", "rgt"]):
		names.update(
			frappe.get_all("Item Group", filters={"lft": (">=", row.lft), "rgt": ("<=", row.rgt)}, pluck="name")
		)
	return sorted(names)


def _either(selection):
	"""The `or_filters` a clean selection stands for, or None when none of its lists names anything real."""
	either = []
	groups = _group_names(selection["item_groups"])
	if groups:
		either.append(["item_group", "in", groups])
	if selection["brands"]:
		either.append(["brand", "in", selection["brands"]])
	if selection["items"]:
		either.append(["item_code", "in", selection["items"]])
	return either or None


def product_rows(selection, limit=MAX_PRODUCTS + 1):
	"""The Website Items a clean selection holds, in the order a catalogue prints them: by item group, then name.

	`limit` defaults to one above the cap, so a caller can tell "exactly the cap" from "more than the cap"."""
	either = _either(selection)
	if not either:
		return []
	return frappe.get_all(
		"Website Item",
		filters=scope(),
		or_filters=either,
		fields=FIELDS,
		order_by="item_group asc, web_item_name asc, item_code asc",
		limit=limit,
	)


def count_products(selection):
	"""How many products a clean selection holds, counted up to one above the cap."""
	either = _either(selection)
	if not either:
		return 0
	return len(
		frappe.get_all(
			"Website Item", filters=scope(), or_filters=either, pluck="name", limit=MAX_PRODUCTS + 1
		)
	)


def _carried():
	"""{item group: how many products its whole subtree carries}, for every group that carries any.

	A group counts what its sub-groups hold, not only what sits directly in it: ticking a category brings its
	sub-categories (`_group_names`), so the figure beside it is theirs together."""
	direct = {
		row.item_group: row.total
		for row in frappe.get_all(
			"Website Item", fields=["item_group", "count(name) as total"], filters=scope(), group_by="item_group"
		)
		if row.item_group
	}
	if not direct:
		return {}, []
	rows = frappe.get_all(
		"Item Group", filters={"name": ("in", list(direct))}, fields=["name", "lft"]
	)
	edges = [(row.lft, direct[row.name]) for row in rows]
	groups = frappe.get_all("Item Group", fields=["name", "lft", "rgt"], order_by="lft asc")
	carried = {}
	ordered = []
	for group in groups:
		total = sum(count for lft, count in edges if group.lft <= lft <= group.rgt)
		if total:
			carried[group.name] = total
			ordered.append(group)
	return carried, ordered


def choices():
	"""What the page offers to tick: the item groups of the shop with the products they carry (in tree order,
	each with its depth), and the brands with theirs."""
	carried, ordered = _carried()
	groups, open_ends = [], []
	for row in ordered:
		while open_ends and open_ends[-1] < row.lft:
			open_ends.pop()
		groups.append({"name": row.name, "count": carried[row.name], "depth": len(open_ends)})
		open_ends.append(row.rgt)
	brands = [
		{"name": row.brand, "count": row.total}
		for row in frappe.get_all(
			"Website Item",
			fields=["brand", "count(name) as total"],
			filters={**scope(), "brand": ["is", "set"]},
			group_by="brand",
			order_by="brand asc",
		)
	]
	return {"groups": groups, "brands": brands}


def search(text):
	"""Products whose name, reference or brand contains `text` (at least two characters), for the picker."""
	text = (text or "").strip() if isinstance(text, str) else ""
	if len(text) < SEARCH_MIN or len(text) > MAX_NAME:
		return []
	like = f"%{text}%"
	rows = frappe.get_all(
		"Website Item",
		filters=scope(),
		or_filters=[["web_item_name", "like", like], ["item_code", "like", like], ["brand", "like", like]],
		fields=["item_code", "web_item_name", "brand"],
		order_by="web_item_name asc",
		limit=SEARCH_LIMIT,
	)
	return [
		{"item_code": row.item_code, "name": row.web_item_name, "brand": row.brand or ""} for row in rows
	]
