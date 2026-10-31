# //// Neoffice — added file (no upstream equivalent).
"""The markups of their own a reseller set, read from their profile, and checked against what the shop carries.

`markup.py` is pure; this module is what reaches the database: the rows of the profile, the item groups above
a product, and whether a name on a rule is something the shop has (a rule that names nothing would sit in the
profile and never apply, and the reseller would believe a category was marked up).
"""

import frappe

from webshop.webshop.catalogue import markup, selection

RULE_FIELDS = ["rule_type", "target", "markup_percent"]


def stored(customer):
	"""The rows of the customer's profile, in the order they were written."""
	if not customer:
		return []
	return [
		{"rule_type": row.rule_type, "target": row.target, "markup_percent": float(row.markup_percent or 0)}
		for row in frappe.get_all(
			"Reseller Markup Rule",
			filters={"parent": customer, "parenttype": "Reseller Catalogue Profile", "parentfield": "markup_rules"},
			fields=RULE_FIELDS,
			order_by="idx asc",
		)
	]


def group_chain():
	"""A function group -> the group and the ones above it, nearest first (one query, remembered)."""
	parents = dict(frappe.get_all("Item Group", fields=["name", "parent_item_group"], as_list=True))
	remembered = {}

	def chain(group):
		if not group:
			return []
		if group not in remembered:
			names, current = [], group
			while current and current not in names:
				names.append(current)
				current = parents.get(current)
			remembered[group] = names
		return remembered[group]

	return chain


def load(customer, default):
	"""The markups of `customer`: their rules, and `default` (the catalogue's own markup) for what no rule names."""
	rules = stored(customer)
	chain_of = group_chain() if any(rule["rule_type"] == "Item Group" for rule in rules) else None
	return markup.Markups(rules, float(default or 0), chain_of)


def unknown_target(rules):
	"""The index of the first rule whose name the shop does not carry, or None.

	A product is carried when a catalogue could hold it (published, visible on this site)."""
	for index, rule in enumerate(rules or ()):
		kind, target = rule["rule_type"], rule["target"]
		if kind == "Item Group":
			known = frappe.db.exists("Item Group", target)
		elif kind == "Brand":
			known = frappe.db.exists("Brand", target)
		else:
			known = frappe.db.exists("Website Item", {**selection.scope(), "item_code": target})
		if not known:
			return index
	return None
