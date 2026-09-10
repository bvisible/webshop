# //// Neoffice — added file (no upstream equivalent).
"""Checking out without a payment gateway.

Two ways a business buys that no PSP is involved in:

**Transfer before shipping** — the order is placed and *waits*. A Payment Request
is raised on it, carrying the amount and a structured reference, and that is what
the shopper pays against; nothing ships and **no invoice is issued** until the
money arrives. ERPNext's own `Payment Request.set_as_paid()` then books the
payment and raises the invoice, whether a human presses it or a bank statement
matches it.

**On account** — the order is placed and shipped like any other, and invoiced on
the terms the shopper's group was offered.

Both are configured on the payment method row (`settlement`), so a shop decides
per customer group who pays in advance and who buys on account. Neither path
touches `create_payment_request`: there is no gateway to call, and no redirect to
wait for.
"""

import frappe
from frappe import _
from frappe.utils import flt

from webshop.webshop.utils.payment_methods import customer_group_of, row_for_gateway

OFFLINE = ("Transfer before shipping", "On account")


def _order_already_placed(token):
	"""The order this token already produced, if it did.

	The shopper double-clicks, the connection retries, the phone wakes the tab up:
	without this, each of those is another order.
	"""
	return frappe.cache().get_value(f"webshop_offline_order_{token}") if token else None


def _remember(token, sales_order):
	if token:
		frappe.cache().set_value(f"webshop_offline_order_{token}", sales_order, expires_in_sec=86400)


def raise_payment_request(sales_order, row):
	"""The demand to pay, raised on the order itself.

	Deliberately **not** an invoice. The shop has not shipped yet, and an invoice
	issued now would put the VAT on a sale that has not happened. A Payment Request
	is ERPNext's document for exactly this, and it is the one thing here that
	carries a payment status of its own: Requested → Paid, with `outstanding_amount`
	along the way. `set_as_paid()` creates the Payment Entry **and** the invoice, so
	the invoice arrives when the money does.
	"""
	order = frappe.get_doc("Sales Order", sales_order)
	existing = frappe.db.get_value(
		"Payment Request",
		{"reference_doctype": "Sales Order", "reference_name": sales_order, "docstatus": ["<", 2]},
		"name",
	)
	if existing:
		return existing

	request = frappe.get_doc(
		{
			"doctype": "Payment Request",
			"payment_request_type": "Inward",
			"transaction_date": order.transaction_date,
			"reference_doctype": "Sales Order",
			"reference_name": sales_order,
			"party_type": "Customer",
			"party": order.customer,
			"grand_total": flt(order.rounded_total or order.grand_total),
			"currency": order.currency,
			"mode_of_payment": row.get("mode_of_payment") or None,
			# //// The shopper pays from the shop, not from a gateway page: the e-mail
			# //// ERPNext would send on its own says "pay online" and links a gateway
			# //// that does not exist here. The shop sends its own confirmation.
			"payment_channel": "",
			"subject": _("Order {0}").format(sales_order),
		}
	)
	request.flags.ignore_permissions = True
	request.insert(ignore_permissions=True)
	request.submit()
	return request.name


@frappe.whitelist()
def place_offline_order(payment_gateway_account, idempotency_token=None):
	"""Place the cart's order and settle it outside any gateway.

	Returns where to send the shopper. Refuses a method this customer is not
	offered — the tile is hidden for them, and hiding a tile is not a permission.
	"""
	from webshop.webshop.shopping_cart.cart import _get_cart_quotation, place_order

	already = _order_already_placed(idempotency_token)
	if already:
		return {"status": "success", "sales_order": already, "redirect_to": _thank_you(already)}

	quotation = _get_cart_quotation()
	if not quotation or not quotation.get("items"):
		frappe.throw(_("Cart is empty"))

	settings = frappe.get_cached_doc("Webshop Settings")
	row = row_for_gateway(payment_gateway_account, settings, customer_group_of(quotation))
	if not row:
		frappe.throw(_("This payment method is not available for your account."))
	settlement = row.get("settlement") or "Online"
	if settlement not in OFFLINE:
		frappe.throw(_("This payment method is settled online."))

	# The terms the shopper's group was offered travel with the order, and from
	# there to the invoice.
	if row.get("payment_terms_template"):
		quotation.payment_terms_template = row.payment_terms_template
		quotation.flags.ignore_permissions = True
		quotation.save(ignore_permissions=True)

	sales_order = place_order()
	if not sales_order:
		frappe.throw(_("Error creating order"))
	_remember(idempotency_token, sales_order)

	payment_request = None
	if settlement == "Transfer before shipping":
		# //// Neoffice — the order must not ship before the money is in. ERPNext has
		# //// no "awaiting payment" status of its own on a Sales Order, so it is put
		# //// On Hold and the Payment Request carries the real state.
		frappe.db.set_value("Sales Order", sales_order, "status", "On Hold")
		payment_request = raise_payment_request(sales_order, row)

	# //// Neoffice — no explicit commit: Frappe commits a successful POST on its own,
	# //// and a commit here would escape a test's rollback (CLAUDE.md).
	return {
		"status": "success",
		"sales_order": sales_order,
		"payment_request": payment_request,
		"redirect_to": _thank_you(sales_order),
	}


def _thank_you(sales_order):
	return f"/thank_you?sales_order={sales_order}"
