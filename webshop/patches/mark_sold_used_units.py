# //// Neoffice — added file (no upstream equivalent).
"""Second-hand (2026-09-14): `sold` is set on save and kept by the stock ledger from now on;
the used units published before this field existed take their value from the stock once."""

import frappe


def execute():
	if not frappe.db.has_column("Website Item", "sold"):
		frappe.reload_doc("webshop", "doctype", "website_item")
	from webshop.webshop.utils.used_items import SECOND_HAND_CONDITIONS, refresh_sold_flag

	for name in frappe.get_all(
		"Website Item", filters={"item_condition": ("in", SECOND_HAND_CONDITIONS)}, pluck="name"
	):
		refresh_sold_flag(name)
