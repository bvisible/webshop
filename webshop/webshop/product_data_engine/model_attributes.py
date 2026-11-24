# //// Neoffice — added file (no upstream equivalent): the attribute filters of a shop that lists MODELS (neoffice-maintenance#3337).
"""Attribute filters for a shop that lists one card per MODEL.

Upstream reads a size or a colour off the item that carries the card (the `Item Variant Attribute` rows of a Website
Item's own item), which holds for a shop where every variant has its card. A shop can list the model only: one card per
model, its sizes and colours on variants that have no card. Switched on, the facet then offered nothing of the sizes
(it read the model's own rows, which carry no value) and a tick found nothing.

For such a shop, a variant of a listed model that has no card of its own counts as part of the model's card:

- the facet offers the values of the live variants of the listed models (`variant_attribute_values`);
- a tick finds the models that have a live variant carrying EVERY ticked value, the same variant
  (`models_matching_attributes`), so that "M" and "red" find the models that sell a red M, not a model that has an M
  and, elsewhere, a red.

A variant that is disabled is not offered, and a variant that has a card of its own (published or not) is a card of
its own: the direct lookup finds it as it always did, and the model is not listed twice for it, so a shop that carries
both its models and its variants lists what it listed.

When the shop shows only what is in stock, or the visitor ticked "in stock", a variant counts only if it can be
bought: a non-stock item, a card on backorder, a card without a shop warehouse (nothing to read: neoffice_theme leaves
such a card alone), or stock beyond what is reserved in the card's warehouse (the sub-warehouses of a group included).
That is one SQL condition (`VARIANT_IN_STOCK`), not a call per variant: a shop has thousands of variants. It reads the
bins as `build_stock_filters` and `get_web_item_qty_in_stock` do; the multi-warehouse sources, the expired batches and
the point-of-sale invoices not yet consolidated, which only the per-item computation of a card sees, are not in it.

The same condition tells whether a MODEL is in stock (`MODEL_IN_STOCK`: some live variant of it can be bought), because a
model's own item never holds stock: the "only what is in stock" box of the sidebar reads it (neoffice-maintenance#3343).

A shop that hides its variants (`hide_variants`) never reaches this: its attribute facets are refused by Webshop
Settings, the two settings being exclusive (`validate_attribute_filters`).

Every text here is a constant of this file and every value a named parameter: nothing a visitor sends is in a statement.
"""

import frappe
from frappe.utils import cint, cstr

# neoffice_theme (stock.SHOW_ONLY_IN_STOCK) adds this switch to Webshop Settings and takes a card off the shop when its
# stock is used up. A site without the theme has no such field: it reads as off.
SHOW_ONLY_IN_STOCK = "neo_show_only_in_stock"

# a variant `v` that has no card of its own: a Website Item of its own is a card, found by the direct lookup
# (a NOT IN over an uncorrelated list, which MariaDB materialises once: the Website Item has no index on its item code, and
# a correlated NOT EXISTS read the whole table for each variant; a null in the list would make every NOT IN unknown)
NO_CARD_OF_ITS_OWN = "v.name NOT IN (SELECT item_code FROM `tabWebsite Item` WHERE item_code IS NOT NULL)"

# a variant `v` of the card `wi` that a visitor can buy
VARIANT_IN_STOCK = """(
	IFNULL(v.is_stock_item, 0) = 0
	OR IFNULL(wi.on_backorder, 0) = 1
	OR IFNULL(wi.website_warehouse, '') = ''
	OR EXISTS (
		SELECT 1 FROM `tabBin` b
		WHERE b.item_code = v.name
		AND b.actual_qty - b.reserved_qty > 0
		AND (
			b.warehouse = wi.website_warehouse
			OR b.warehouse IN (
				SELECT w.name FROM `tabWarehouse` w
				INNER JOIN `tabWarehouse` root ON root.name = wi.website_warehouse
				WHERE w.lft > root.lft AND w.rgt < root.rgt
			)
		)
	)
)"""

# the card `wi` of a model, told by its variants: one live variant of it can be bought. A model's own item holds no stock
# (a bin belongs to a variant), so asking its own bin took the model off a list that shows only what is in stock whatever its
# variants held (neoffice-maintenance#3343). A variant that has a card of its own counts: the model's page sells it too.
MODEL_IN_STOCK = f"""EXISTS (
	SELECT 1 FROM `tabItem` v
	WHERE v.variant_of = wi.item_code
	AND IFNULL(v.disabled, 0) = 0
	AND {VARIANT_IN_STOCK}
)"""


def lists_models(settings):
	"""True when attribute filters may look into the variants of a listed model: a shop that hides its variants keeps
	the old exclusion (Webshop Settings refuses both)."""
	return not cint(settings.get("hide_variants"))


def shows_only_what_is_in_stock(settings):
	"""True when the shop takes a card off when its stock is used up (neoffice_theme's switch)."""
	if not frappe.get_meta("Webshop Settings").has_field(SHOW_ONLY_IN_STOCK):
		return False
	return bool(cint(settings.get(SHOW_ONLY_IN_STOCK)))


def models_among(item_codes):
	"""The item codes among `item_codes` that are models (templates): their own attribute rows hold no value a visitor
	could buy."""
	if not item_codes:
		return set()
	return set(frappe.get_all("Item", filters={"name": ["in", list(item_codes)], "has_variants": 1}, pluck="name"))


def variant_attribute_values(model_codes, attributes, only_in_stock=False):
	"""[(attribute, value)] carried by the live variants of these models, for these attributes, in one query."""
	if not model_codes or not attributes:
		return []
	stock = f"AND {VARIANT_IN_STOCK}" if only_in_stock else ""
	query = f"""
		SELECT DISTINCT iva.attribute, iva.attribute_value
		FROM `tabWebsite Item` wi
		INNER JOIN `tabItem` v ON v.variant_of = wi.item_code AND IFNULL(v.disabled, 0) = 0
		INNER JOIN `tabItem Variant Attribute` iva ON iva.parent = v.name
		WHERE wi.item_code IN %(models)s
		AND iva.attribute IN %(attributes)s
		AND IFNULL(iva.attribute_value, '') != ''
		AND {NO_CARD_OF_ITS_OWN}
		{stock}
	"""
	return frappe.db.sql(  # nosemgrep: frappe-semgrep-rules.rules.security.frappe-sql-format-injection
		query, {"models": list(model_codes), "attributes": list(attributes)}
	)


def models_matching_attributes(attributes, only_in_stock=False):
	"""The item codes of the published models that have one live variant, with no card of its own, carrying every
	ticked value.

	`attributes` is what the visitor ticked, {attribute: [values]}. An attribute with no value ticked asks nothing of
	the variants (the page never sends one).
	"""
	clauses, params = [], {}
	for index, (attribute, values) in enumerate((attributes or {}).items()):
		values = values if isinstance(values, (list, tuple, set)) else [values]
		values = [cstr(value) for value in values if value not in (None, "")]
		if not values:
			continue
		clauses.append(f"(iva.attribute = %(attribute_{index})s AND iva.attribute_value IN %(values_{index})s)")
		params[f"attribute_{index}"] = cstr(attribute)
		params[f"values_{index}"] = values
	if not clauses:
		return set()
	params["ticked"] = len(clauses)
	ticked = " OR ".join(clauses)
	stock = f"AND {VARIANT_IN_STOCK}" if only_in_stock else ""
	query = f"""
		SELECT wi.item_code
		FROM `tabWebsite Item` wi
		INNER JOIN `tabItem` v ON v.variant_of = wi.item_code AND IFNULL(v.disabled, 0) = 0
		INNER JOIN `tabItem Variant Attribute` iva ON iva.parent = v.name
		WHERE wi.published = 1
		AND ({ticked})
		AND {NO_CARD_OF_ITS_OWN}
		{stock}
		GROUP BY wi.item_code, v.name
		HAVING COUNT(DISTINCT iva.attribute) = %(ticked)s
	"""
	rows = frappe.db.sql(query, params)  # nosemgrep: frappe-semgrep-rules.rules.security.frappe-sql-format-injection
	return {row[0] for row in rows}
