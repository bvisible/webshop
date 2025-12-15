import frappe
from frappe.utils import flt, getdate, nowdate

from erpnext.stock.doctype.batch.batch import get_batch_qty
from erpnext.stock.doctype.warehouse.warehouse import get_child_warehouses


def get_web_item_qty_in_stock(item_code, item_warehouse_field, warehouse=None):
	in_stock, stock_qty = 0, ""
	template_item_code, is_stock_item = frappe.db.get_value(
		"Item", item_code, ["variant_of", "is_stock_item"]
	)

	if not warehouse:
		warehouse = frappe.db.get_value("Website Item", {"item_code": item_code}, item_warehouse_field)

	if not warehouse and template_item_code and template_item_code != item_code:
		warehouse = frappe.db.get_value(
			"Website Item", {"item_code": template_item_code}, item_warehouse_field
		)

	if warehouse and frappe.get_cached_value("Warehouse", warehouse, "is_group") == 1:
		warehouses = get_child_warehouses(warehouse)
	else:
		warehouses = [warehouse] if warehouse else []

	total_stock = 0.0
	if warehouses:
		for wh in warehouses:
			# Use actual_qty - reserved_qty to get available stock
			# This excludes:
			# - ordered_qty from Purchase Orders (not yet received)
			# - planned_qty from Work Orders (not yet produced)
			# And properly accounts for:
			# - Physical stock (actual_qty)
			# - Reserved for Sales Orders (reserved_qty)
			stock_qty = frappe.db.sql(
				"""
				select (S.actual_qty - S.reserved_qty) / IFNULL(C.conversion_factor, 1)
				from tabBin S
				inner join `tabItem` I on S.item_code = I.Item_code
				left join `tabUOM Conversion Detail` C on I.sales_uom = C.uom and C.parent = I.Item_code
				where S.item_code=%s and S.warehouse=%s""",
				(item_code, wh),
			)

			if stock_qty:
				qty = adjust_qty_for_expired_items(item_code, stock_qty, wh)
				# Subtract POS reserved quantities (unconsolidated POS Invoices)
				# POS reservations are not included in projected_qty
				pos_reserved = get_pos_reserved_qty(item_code, wh)
				qty = max(0, qty - pos_reserved)
				total_stock += qty

		in_stock = total_stock > 0 and 1 or 0

	return frappe._dict(
		{"in_stock": in_stock, "stock_qty": total_stock, "is_stock_item": is_stock_item}
	)


def get_pos_reserved_qty(item_code, warehouse):
	"""
	Get reserved quantity from unconsolidated POS Invoices.
	This prevents overselling when POS and webshop share the same inventory.
	"""
	try:
		from erpnext.accounts.doctype.pos_invoice.pos_invoice import (
			get_pos_reserved_qty as _get_pos_reserved_qty,
		)
		return flt(_get_pos_reserved_qty(item_code, warehouse))
	except ImportError:
		# Fallback if function not available in older ERPNext versions
		return 0.0


def adjust_qty_for_expired_items(item_code, stock_qty, warehouse):
	batches = frappe.get_all("Batch", filters=[{"item": item_code}], fields=["expiry_date", "name"])
	expired_batches = get_expired_batches(batches)
	stock_qty = [list(item) for item in stock_qty]

	for batch in expired_batches:
		if warehouse:
			stock_qty[0][0] = max(0, stock_qty[0][0] - get_batch_qty(batch, warehouse))
		else:
			stock_qty[0][0] = max(0, stock_qty[0][0] - qty_from_all_warehouses(get_batch_qty(batch)))

		if not stock_qty[0][0]:
			break

	return stock_qty[0][0] if stock_qty else 0


def get_expired_batches(batches):
	"""
	:param batches: A list of dict in the form [{'expiry_date': datetime.date(20XX, 1, 1), 'name': 'batch_id'}, ...]
	"""
	return [b.name for b in batches if b.expiry_date and b.expiry_date <= getdate(nowdate())]


def qty_from_all_warehouses(batch_info):
	"""
	:param batch_info: A list of dict in the form [{u'warehouse': u'Stores - I', u'qty': 0.8}, ...]
	"""
	qty = 0
	for batch in batch_info:
		qty = qty + batch.qty

	return qty


def get_non_stock_item_status(item_code, item_warehouse_field):
	# if item is a product bundle, check if its bundle items are in stock
	if frappe.db.exists("Product Bundle", item_code):
		items = frappe.get_doc("Product Bundle", item_code).get_all_children()
		bundle_warehouse = frappe.db.get_value(
			"Website Item", {"item_code": item_code}, item_warehouse_field
		)
		return all(
			get_web_item_qty_in_stock(d.item_code, item_warehouse_field, bundle_warehouse).in_stock
			for d in items
		)
	else:
		return 1
