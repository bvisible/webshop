# //// Neoffice — added file (no upstream equivalent): a product found by a code typed whole.
# //// neoffice-maintenance#691, plan note 20 (lot B4), 2026-09-26.
"""A product found by one of its references, typed or scanned whole: its barcode (an EAN), its
manufacturer's part number, and its supplier's reference when the shop allows it (Webshop
Settings, search_supplier_references).

A professional customer often knows a product by the reference on their supplier's list, not by
the shop's code or name. The reference only finds: it is never shown on a page and never sent to
Google (it would name the shop's supplier, and Google reserves `mpn` for the manufacturer's).
"""

import re

import frappe
from frappe.utils import cint

# Shorter than this, a code is a fragment of something else ("12", "XL")
SHORTEST = 3


def items_referenced(term: str, settings=None) -> list[str]:
	"""Item codes whose barcode, manufacturer's part number or, when the shop allows it, supplier's
	reference is exactly `term` (a barcode also without the spaces and dashes it is typed with)."""
	term = (term or "").strip()
	if len(term) < SHORTEST:
		return []
	compact = re.sub(r"[\s-]+", "", term)
	codes = set(
		frappe.get_all(
			"Item Barcode", filters={"parenttype": "Item", "barcode": ["in", sorted({term, compact})]}, pluck="parent"
		)
	)
	codes.update(frappe.get_all("Item", filters={"default_manufacturer_part_no": term}, pluck="name"))
	codes.update(frappe.get_all("Item Manufacturer", filters={"manufacturer_part_no": term}, pluck="item_code"))
	if searches_supplier_references(settings):
		codes.update(
			frappe.get_all(
				"Item Supplier", filters={"parenttype": "Item", "supplier_part_no": term}, pluck="parent"
			)
		)
	return sorted(code for code in codes if code)


def listing_codes(term: str, settings=None) -> list[str]:
	"""items_referenced, with the model of each variant: a listing that hides variants still shows
	the product."""
	codes = items_referenced(term, settings)
	if not codes:
		return []
	models = frappe.get_all(
		"Item", filters={"name": ["in", codes], "variant_of": ["is", "set"]}, pluck="variant_of"
	)
	return sorted(set(codes) | set(models))


def searches_supplier_references(settings=None) -> bool:
	if settings is None:
		from webshop.webshop.doctype.webshop_settings.webshop_settings import (
			get_shopping_cart_settings,
		)

		settings = get_shopping_cart_settings()
	return bool(cint(settings.get("search_supplier_references")))
