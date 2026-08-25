# //// Neoffice — added file (no upstream equivalent). Core resolution of the
# //// multi-warehouse feature: which stock sources a Website Item exposes,
# //// where each quantity is read from (real Bin or a synced Item field), and
# //// which source a cart line should target. Everything is gated on
# //// Webshop Settings.enable_multi_warehouse so that the feature switched off
# //// leaves the historical single-warehouse behaviour untouched.

import frappe
from frappe import _
from frappe.utils import cint, flt

from webshop.webshop.multi_warehouse.delays import (
	estimate_delivery_date,
	estimate_lead_days,
)

MODE_AUTO = "Auto"
MODE_CUSTOM = "Custom"
MODE_OFF = "Off"


def get_settings():
	return frappe.get_cached_doc("Webshop Settings")


def is_enabled(settings=None):
	settings = settings or get_settings()
	return bool(cint(settings.get("enable_multi_warehouse")) and settings.get("warehouse_sources"))


def get_source_rows(settings=None):
	settings = settings or get_settings()
	return settings.get("warehouse_sources") or []


def get_source_map(settings=None):
	"""{warehouse: source row} for every configured source."""
	return {row.warehouse: row for row in get_source_rows(settings)}


def get_source_for_warehouse(warehouse, settings=None):
	if not warehouse:
		return None
	return get_source_map(settings).get(warehouse)


def get_source_label(warehouse, settings=None):
	"""Shopper-facing label of a warehouse, falling back to its name."""
	row = get_source_for_warehouse(warehouse, settings)
	if row and row.display_label:
		return row.display_label
	if warehouse:
		return frappe.get_cached_value("Warehouse", warehouse, "warehouse_name") or warehouse
	return None


def get_primary_warehouse(item_code):
	"""The item's own website_warehouse, template fallback for variants.

	Same resolution as webshop.webshop.utils.product.get_web_item_qty_in_stock.
	"""
	warehouse = frappe.db.get_value(
		"Website Item", {"item_code": item_code}, "website_warehouse"
	)
	if warehouse:
		return warehouse

	template = frappe.db.get_value("Item", item_code, "variant_of")
	if template and template != item_code:
		return frappe.db.get_value(
			"Website Item", {"item_code": template}, "website_warehouse"
		)
	return None


def get_source_qty(item_code, source_row):
	"""Available quantity of one source for one item.

	Warehouse Bin reuses the historical stock computation (expired batches and
	POS reservations included). Item Field reads a numeric field on Item — no
	Bin, no valued stock.
	"""
	if source_row.get("stock_basis") == "Item Field":
		fieldname = source_row.get("stock_field")
		if not fieldname or not frappe.get_meta("Item").has_field(fieldname):
			return 0.0
		return flt(frappe.db.get_value("Item", item_code, fieldname) or 0)

	from webshop.webshop.utils.product import get_web_item_qty_in_stock

	return flt(
		get_web_item_qty_in_stock(
			item_code, "website_warehouse", warehouse=source_row.warehouse
		).stock_qty
	)


def _get_item_mode_and_custom(item_code):
	"""(mode, [custom warehouses]) of the Website Item owning item_code."""
	website_item = frappe.db.get_value(
		"Website Item",
		{"item_code": item_code},
		["name", "warehouse_sources_mode"],
		as_dict=True,
	)
	if not website_item:
		# Variant without its own Website Item: follow the template's mode.
		template = frappe.db.get_value("Item", item_code, "variant_of")
		if template and template != item_code:
			return _get_item_mode_and_custom(template)
		return MODE_AUTO, []

	mode = website_item.warehouse_sources_mode or MODE_AUTO
	custom = []
	if mode == MODE_CUSTOM:
		custom = [
			d.warehouse
			for d in frappe.get_cached_doc("Website Item", website_item.name).get(
				"additional_warehouse_sources"
			)
			or []
		]
	return mode, custom


def get_item_warehouse_sources(item_code, settings=None, with_stock=True):
	"""Ordered list of the stock sources this item exposes on the webshop.

	Each entry: warehouse, label, is_primary, is_supplier_source, supplier,
	stock_qty, in_stock, lead_days, estimated_delivery (ISO date).
	Empty list when the feature is off or the item is not a stock item —
	callers then keep the historical single-warehouse path.
	"""
	settings = settings or get_settings()
	if not is_enabled(settings):
		return []

	if not cint(frappe.db.get_value("Item", item_code, "is_stock_item")):
		return []

	mode, custom_warehouses = _get_item_mode_and_custom(item_code)
	if mode == MODE_OFF:
		return []

	primary_warehouse = get_primary_warehouse(item_code)
	source_map = get_source_map(settings)
	sources = []

	def make_entry(warehouse, row, is_primary):
		qty = 0.0
		if with_stock:
			if row:
				qty = get_source_qty(item_code, row)
			elif warehouse:
				from webshop.webshop.utils.product import get_web_item_qty_in_stock

				qty = flt(
					get_web_item_qty_in_stock(
						item_code, "website_warehouse", warehouse=warehouse
					).stock_qty
				)
		return frappe._dict(
			{
				"warehouse": warehouse,
				"label": (row.display_label if row else None)
				or get_source_label(warehouse, settings),
				"is_primary": 1 if is_primary else 0,
				"is_supplier_source": cint(row.is_supplier_source) if row else 0,
				"supplier": row.supplier if row else None,
				"stock_qty": qty,
				"in_stock": 1 if qty > 0 else 0,
				"lead_days": estimate_lead_days(row) if row else 0,
				"estimated_delivery": str(estimate_delivery_date(row)) if row else None,
			}
		)

	# The primary source is always listed first, configured or not.
	if primary_warehouse:
		sources.append(
			make_entry(
				primary_warehouse, source_map.get(primary_warehouse), is_primary=True
			)
		)

	for row in get_source_rows(settings):
		if row.warehouse == primary_warehouse:
			continue
		if mode == MODE_CUSTOM:
			if row.warehouse not in custom_warehouses:
				continue
			sources.append(make_entry(row.warehouse, row, is_primary=False))
		else:
			# Auto mode: only sources flagged for automatic exposure, and only
			# when they actually hold stock for this item.
			if not cint(row.auto_enable_if_stock):
				continue
			entry = make_entry(row.warehouse, row, is_primary=False)
			if entry.stock_qty > 0:
				sources.append(entry)

	return sources


def get_allowed_warehouses(item_code, settings=None):
	"""Warehouses a cart line of this item may legitimately target."""
	return [s.warehouse for s in get_item_warehouse_sources(item_code, settings)]


def resolve_target_warehouse(item_code, qty, settings=None):
	"""Source auto-picked when the shopper did not choose one.

	First source (settings order, primary first) covering the full quantity —
	"switch entirely to the source that covers" rather than splitting. Falls
	back to the primary warehouse when none covers.
	"""
	settings = settings or get_settings()
	sources = get_item_warehouse_sources(item_code, settings)
	if not sources:
		return get_primary_warehouse(item_code)

	for source in sources:
		if flt(source.stock_qty) >= flt(qty):
			return source.warehouse

	return sources[0].warehouse


def get_aggregate_stock(item_code, settings=None):
	"""Stock summed over all exposed sources (grid / list badge).

	Returns the same shape as get_web_item_qty_in_stock, or None when the
	feature does not apply to this item (caller keeps the historical path).
	"""
	sources = get_item_warehouse_sources(item_code, settings)
	if not sources:
		return None

	total = sum(flt(s.stock_qty) for s in sources)
	return frappe._dict(
		{"in_stock": 1 if total > 0 else 0, "stock_qty": total, "is_stock_item": 1}
	)


def decorate_cart_line(line, settings=None):
	"""Attach shopper-facing source metadata to a Quotation/Sales Order line."""
	settings = settings or get_settings()
	row = get_source_for_warehouse(line.get("warehouse"), settings)
	line.warehouse_source_label = get_source_label(line.get("warehouse"), settings)
	if row:
		line.delivery_lead_days = estimate_lead_days(row)
		line.estimated_delivery = str(estimate_delivery_date(row))
	return line
