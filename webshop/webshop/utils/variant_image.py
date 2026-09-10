# //// Neoffice — added file (no upstream equivalent).
"""A variant without a picture shows its template's.

The variant of a board is the same board in another size: a reseller's import
published it without a photo, and the catalogue, the carousels and the product page
showed a letter in a grey box beside the template's photo (a reseller site,
2026-09-10). The picture is inherited at render time and never written to the
variant, so a photo added to the variant later wins and the data stays untouched.
"""

import frappe


def template_images(templates: set) -> dict:
	"""Template item_code -> its published Website Item's picture, else the Item's."""
	templates = {t for t in templates if t}
	if not templates:
		return {}
	found = {}
	for row in frappe.get_all(
		"Website Item", filters={"item_code": ["in", list(templates)]}, fields=["item_code", "website_image"]
	):
		if row.website_image:
			found[row.item_code] = row.website_image
	missing = templates - set(found)
	if missing:
		for row in frappe.get_all("Item", filters={"name": ["in", list(missing)]}, fields=["name", "image"]):
			if row.image:
				found[row.name] = row.image
	return found


def _set(row, key, value):
	if isinstance(row, dict):
		row[key] = value
	else:
		setattr(row, key, value)


def inherit_template_images(rows: list) -> list:
	"""Fill the empty website_image of every variant row from its template.

	Rows are dicts or documents carrying item_code, variant_of and website_image;
	they are updated in place and returned.
	"""
	pending = [r for r in rows if r.get("variant_of") and not r.get("website_image")]
	if not pending:
		return rows
	images = template_images({r.get("variant_of") for r in pending})
	for row in pending:
		image = images.get(row.get("variant_of"))
		if image:
			_set(row, "website_image", image)
	return rows
