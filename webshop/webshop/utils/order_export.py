# //// Neoffice — added file (the order as a spreadsheet, no upstream equivalent).
"""The customer's order as an .xlsx, for their own systems.

One sheet, import-friendly: a bold header row, one row per line with the
item's code, name, variant attributes, barcode, quantity, unit, unit price and
amount, then a summary block — order number, date, customer, status, currency,
totals. Whoever may read the order on the portal may download it: the same
permission as the order page, nothing more.
"""

import frappe
from frappe import _
from frappe.utils import flt, formatdate
from frappe.utils.xlsxutils import build_xlsx_response

EXPORTABLE = ("Sales Order", "Sales Invoice", "Quotation")


@frappe.whitelist()
def download_order_xlsx(doctype, name):
	"""GET /api/method/…download_order_xlsx?doctype=Sales%20Order&name=… → a file."""
	if doctype not in EXPORTABLE:
		frappe.throw(_("Not Permitted"), frappe.PermissionError)
	doc = frappe.get_doc(doctype, name)
	if not frappe.has_website_permission(doc):
		frappe.throw(_("Not Permitted"), frappe.PermissionError)
	build_xlsx_response(order_rows(doc), name)


def order_rows(doc):
	"""The rows of the sheet, header first."""
	codes = [row.item_code for row in doc.items]
	attributes = frappe.get_all(
		"Item Variant Attribute",
		filters={"parent": ["in", codes]},
		fields=["parent", "attribute", "attribute_value"],
		order_by="idx asc",
	)
	attrs, attribute_names = {}, []
	for row in attributes:
		attrs.setdefault(row.parent, {})[row.attribute] = row.attribute_value
		if row.attribute not in attribute_names:
			attribute_names.append(row.attribute)
	barcodes = {}
	for row in frappe.get_all(
		"Item Barcode", filters={"parent": ["in", codes]}, fields=["parent", "barcode"], order_by="idx asc"
	):
		barcodes.setdefault(row.parent, row.barcode)

	columns = [
		_("Item Code"),
		_("Item Name"),
		*[_(name) for name in attribute_names],
		_("Barcode"),
		_("Quantity"),
		_("UOM"),
		_("Rate"),
		_("Amount"),
	]
	lines = []
	for row in doc.items:
		variant = attrs.get(row.item_code, {})
		lines.append(
			[
				row.item_code,
				row.item_name,
				*[variant.get(name, "") for name in attribute_names],
				barcodes.get(row.item_code, ""),
				flt(row.qty),
				row.uom or row.get("stock_uom") or "",
				flt(row.rate),
				flt(row.amount),
			]
		)

	date = doc.get("transaction_date") or doc.get("posting_date")
	pad = [""] * (len(columns) - 2)
	summary = [
		[],
		[_("Order"), doc.name, *pad],
		[_("Date"), formatdate(date) if date else "", *pad],
		[_("Customer"), doc.get("customer_name") or doc.get("party_name") or "", *pad],
		[_("Status"), _(doc.get("status")) if doc.get("status") else "", *pad],
		[_("Currency"), doc.get("currency") or "", *pad],
		[_("Net Total"), flt(doc.get("net_total")), *pad],
		[_("Total Taxes and Charges"), flt(doc.get("total_taxes_and_charges")), *pad],
		[_("Grand Total"), flt(doc.get("grand_total")), *pad],
	]
	return [columns, *lines, *summary]
