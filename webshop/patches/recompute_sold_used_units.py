# //// Neoffice — added file (no upstream equivalent).
"""Second-hand, second version of `sold` (2026-09-14): a unit is sold when nothing of it is
available in any warehouse, orders' reservations deducted, no longer when the shop's exposure
rule finds nothing. Every used unit is recomputed once with the new rule."""

import frappe


def execute():
	if not frappe.db.has_column("Website Item", "sold"):
		return
	from webshop.webshop.utils.used_items import SECOND_HAND_CONDITIONS, refresh_sold_flag

	for name in frappe.get_all(
		"Website Item", filters={"item_condition": ("in", SECOND_HAND_CONDITIONS)}, pluck="name"
	):
		refresh_sold_flag(name)
