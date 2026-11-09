# //// Neoffice — added file (no upstream equivalent). Supplier procurement
# //// pilot of the multi-warehouse feature: when a Sales Order is submitted
# //// (from the shop or typed at the desk), its lines sourced from a supplier
# //// warehouse feed a draft Purchase Order of their own per supplier, or a
# //// Material Request, with sales_order/sales_order_item posted on every line
# //// so ERPNext natively tracks ordered_qty, over-ordering, and — with stock
# //// reservation enabled — reserves the received goods for the customer order
# //// at Purchase Receipt submit. An invoice typed without an order does the
# //// same for its supplier lines (no order line to link: its Reference says
# //// which invoice). Never blocks the customer document: any failure is
# //// logged and the merchant can order manually.
# ////
# //// One purchase order per customer document since 2026-11-09: stacking
# //// every order into the supplier's open draft mixed customers, and an old
# //// forgotten draft got received with the new lines. The drafts of one
# //// supplier are merged by hand when the shop wants a single order
# //// (neoffice_theme purchase_order_merge), which keeps every line's link.

import frappe
from frappe import _
from frappe.utils import cint, flt, nowdate

from webshop.webshop.multi_warehouse.delays import expected_receipt_date
from webshop.webshop.multi_warehouse.sources import (
	get_primary_warehouse,
	get_settings,
	get_source_map,
	is_enabled,
)

PO_MARKER_FIELD = "neo_webshop_generated"
# The customer order or invoice a purchase order was made for (patch
# add_purchase_order_reference_field); joined by commas once drafts are merged.
REFERENCE_FIELD = "neo_source_reference"


def process_sales_order(doc, method=None):
	"""doc_events hook: Sales Order on_submit, for a shop order or a desk order."""
	try:
		settings = _procurement_settings()
		if not settings:
			return
		_process(doc, settings, linked=True)
	except Exception:
		# The customer has already paid: procurement must never break the
		# order. Log and let the merchant purchase manually.
		frappe.log_error(
			"Webshop supplier procurement failed",
			f"Sales Order {doc.name}\n{frappe.get_traceback()}",
		)


def process_sales_invoice(doc, method=None):
	"""doc_events hook: Sales Invoice on_submit, for the lines no order came before.

	A line that comes from a Sales Order or a Delivery Note was procured (or not)
	when that document was; only what was typed straight on the invoice is left.
	"""
	try:
		settings = _procurement_settings()
		if not settings:
			return
		if cint(doc.get("is_return")) or cint(doc.get("is_consolidated")):
			return
		if _invoice_already_procured(doc.name):
			return
		_process(doc, settings, linked=False)
	except Exception:
		frappe.log_error(
			"Webshop supplier procurement failed",
			f"Sales Invoice {doc.name}\n{frappe.get_traceback()}",
		)


def _procurement_settings():
	settings = get_settings()
	if not is_enabled(settings):
		return None
	if not cint(settings.get("enable_supplier_procurement")):
		return None
	return settings


def _came_before(item):
	"""An invoice line made from an order or a delivery note."""
	return bool(
		item.get("sales_order")
		or item.get("so_detail")
		or item.get("delivery_note")
		or item.get("dn_detail")
	)


def _process(doc, settings, linked):
	source_map = get_source_map(settings)
	grouped = {}

	for item in doc.get("items") or []:
		if not linked and _came_before(item):
			continue
		row = source_map.get(item.get("warehouse"))
		if not row or not cint(row.is_supplier_source):
			continue
		if flt(item.qty) <= 0:
			continue
		if linked and _already_procured(item.name, settings):
			continue

		supplier = row.supplier or _default_supplier(item.item_code, doc.company)
		if not supplier:
			frappe.log_error(
				"Webshop procurement: no supplier for item",
				f"{doc.doctype} {doc.name}, item {item.item_code}, "
				f"warehouse {item.warehouse}: set a Supplier on the warehouse "
				"source in Webshop Settings or a default supplier on the item.",
			)
			continue

		grouped.setdefault(supplier, []).append((item, row))

	if not grouped:
		return

	if (settings.get("procurement_mode") or "Purchase Order") == "Material Request":
		_make_material_request(doc, grouped, linked)
	else:
		for supplier, lines in grouped.items():
			_make_purchase_order(doc, supplier, lines, linked)


def _already_procured(sales_order_item, settings):
	"""A non-cancelled purchase document line already covers this SO line."""
	if frappe.db.exists(
		"Purchase Order Item",
		{"sales_order_item": sales_order_item, "docstatus": ["<", 2]},
	):
		return True
	return bool(
		frappe.db.exists(
			"Material Request Item",
			{"sales_order_item": sales_order_item, "docstatus": ["<", 2]},
		)
	)


def _invoice_already_procured(invoice_name):
	"""A non-cancelled purchase order names this invoice in its Reference.

	Merged drafts join their references with commas, so the name is looked
	for as one of the parts, never as a substring of a longer number.
	"""
	if not frappe.get_meta("Purchase Order").has_field(REFERENCE_FIELD):
		return False
	for reference in frappe.get_all(
		"Purchase Order",
		filters={
			"docstatus": ["<", 2],
			REFERENCE_FIELD: ["like", f"%{invoice_name}%"],
		},
		pluck=REFERENCE_FIELD,
	):
		if invoice_name in [part.strip() for part in (reference or "").split(",")]:
			return True
	return False


def _default_supplier(item_code, company):
	return frappe.db.get_value(
		"Item Default",
		{"parent": item_code, "company": company},
		"default_supplier",
	) or frappe.db.get_value(
		"Item Default", {"parent": item_code}, "default_supplier"
	)


def _receiving_warehouse(item, row):
	return (
		row.get("receiving_warehouse")
		or get_primary_warehouse(item.item_code)
		or item.get("warehouse")
	)


def _line_payload(doc, item, row, linked):
	payload = {
		"item_code": item.item_code,
		"qty": flt(item.stock_qty) or flt(item.qty),
		"uom": item.get("stock_uom")
		or frappe.db.get_value("Item", item.item_code, "stock_uom"),
		"conversion_factor": 1,
		"warehouse": _receiving_warehouse(item, row),
		"schedule_date": expected_receipt_date(row),
	}
	if linked:
		# The Sales Order line: ERPNext follows ordered_qty and reserves the
		# received goods for this customer order through it.
		payload["sales_order"] = doc.name
		payload["sales_order_item"] = item.name
	return payload


def _make_purchase_order(doc, supplier, lines, linked):
	"""A new draft Purchase Order for this customer document and supplier."""
	po = frappe.new_doc("Purchase Order")
	po.supplier = supplier
	po.company = doc.company
	po.transaction_date = nowdate()
	if po.meta.has_field(PO_MARKER_FIELD):
		po.set(PO_MARKER_FIELD, 1)
	if po.meta.has_field(REFERENCE_FIELD):
		po.set(REFERENCE_FIELD, doc.name)

	for item, row in lines:
		po.append("items", _line_payload(doc, item, row, linked))

	po.flags.ignore_permissions = True
	po.flags.ignore_mandatory = True
	po.insert()
	# Draft on purpose: the merchant reviews, completes and submits.

	doc.add_comment(
		"Info",
		_("Supplier order prepared: {0} for {1}").format(po.name, supplier),
	)


def notify_sales_orders_on_receipt(doc, method=None):
	"""doc_events hook: Purchase Receipt on_submit.

	Native ERPNext already reserves the received goods for the customer order
	(Stock Settings: enable_stock_reservation + auto_reserve_stock_for_sales_
	order_on_purchase). What it does not do is tell the seller side: this
	writes one timeline comment per linked Sales Order, so whoever opens the
	customer order sees the supplier goods arrived.
	"""
	try:
		settings = get_settings()
		if not is_enabled(settings) or not cint(
			settings.get("enable_supplier_procurement")
		):
			return
		if doc.get("is_return"):
			return

		by_sales_order = {}
		for item in doc.get("items") or []:
			if not item.get("sales_order"):
				continue
			by_sales_order.setdefault(item.sales_order, []).append(item)

		for sales_order, items in by_sales_order.items():
			if frappe.db.get_value("Sales Order", sales_order, "docstatus") != 1:
				continue
			lines = ", ".join(
				f"{frappe.format_value(flt(d.get('received_qty') or d.qty), {'fieldtype': 'Float'})} × {d.item_code}"
				for d in items
			)
			frappe.get_doc("Sales Order", sales_order).add_comment(
				"Info",
				_("Supplier goods received ({0}): {1}").format(doc.name, lines),
			)
	except Exception:
		frappe.log_error(
			"Webshop procurement: receipt notification failed",
			f"Purchase Receipt {doc.name}\n{frappe.get_traceback()}",
		)


def _make_material_request(doc, grouped, linked):
	"""One submitted Material Request (type Purchase) for the whole document.

	Submitted so the native PO consolidation ("Get Items From ▸ Material
	Request") can pick it up — it only lists submitted requests.
	"""
	mr = frappe.new_doc("Material Request")
	mr.material_request_type = "Purchase"
	mr.company = doc.company
	mr.transaction_date = nowdate()

	for lines in grouped.values():
		for item, row in lines:
			mr.append("items", _line_payload(doc, item, row, linked))

	mr.flags.ignore_permissions = True
	mr.save()
	mr.submit()

	doc.add_comment(
		"Info",
		_("Material Request prepared: {0}").format(mr.name),
	)
