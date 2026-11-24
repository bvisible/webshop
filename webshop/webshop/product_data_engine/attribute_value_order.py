# //// Neoffice — added file (no upstream equivalent): the order of the values of an attribute facet (neoffice-maintenance#3344).
"""The order of the values an attribute facet offers.

Upstream hands them back in the order the database returns the variants' rows, which is not the same from one request to
the next. The fork first sorted them alphabetically: stable, but "L, M, S, XL" and "10, 12, 8" are not the order a shop of
clothes or of shoes wants. The order is now the one the merchant gave the values on the Item Attribute (the rows of its
form, `Item Attribute Value.idx`). A value the attribute does not list (one removed since, or a numeric attribute that holds a
range and no row) follows, in a natural order: the digits are compared as numbers, the rest without regard to case.

It stays ONE fixed order whatever the database returns, which is what the alphabetical sort protected. Nothing here knows a
size or a colour: the shop's own order is read, and the natural order only compares characters.
"""

import re

import frappe
from frappe.utils import cstr

_DIGITS = re.compile(r"(\d+)")


def listed_positions(attributes):
	"""{attribute: {value: position}}: the rows of each Item Attribute, in the order of its form, for these attributes, in
	one query. An attribute that has no row (a range of numbers, an attribute that does not exist) is not in the answer."""
	if not attributes:
		return {}
	rows = frappe.get_all(
		"Item Attribute Value",
		filters={"parent": ["in", list(attributes)], "parenttype": "Item Attribute"},
		fields=["parent", "attribute_value", "idx"],
		order_by="idx asc",
		limit_page_length=0,
	)
	positions = {}
	for row in rows:
		positions.setdefault(row.parent, {}).setdefault(row.attribute_value, row.idx)
	return positions


def natural_key(value):
	"""A key that sorts "8" before "10" and "Size 8" before "Size 10", and a word without regard to case: the text is cut
	into its runs of digits (compared as numbers) and the rest (compared in lower case)."""
	key = []
	for index, part in enumerate(_DIGITS.split(cstr(value))):
		if index % 2:  # the runs the pattern caught: decimal digits, int() reads every one
			key.append((0, int(part), ""))
		elif part:
			key.append((1, 0, part.lower()))
	return key


def order_values(values, positions=None):
	"""`values` in the order the attribute lists them, then the ones it does not, in natural order.

	`positions` is `listed_positions()[attribute]`. A value is found by what it says, or, failing that, without regard to
	case. Two values that tie keep a fixed order (their text), so the answer never depends on the order they come in.
	"""
	positions = positions or {}
	lowered = {cstr(value).lower(): place for value, place in positions.items()}

	def key(value):
		place = positions.get(value)
		if place is None:
			place = lowered.get(cstr(value).lower())
		if place is not None:
			return (0, place, ()), cstr(value)
		return (1, 0, natural_key(value)), cstr(value)

	return sorted(values, key=key)
