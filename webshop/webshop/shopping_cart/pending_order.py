# //// Neoffice — added file (no upstream equivalent). The order a card payment is raised on.
"""The order a payment request is raised on while the cart is still a cart.

Upstream ERPNext (v15.12x) no longer lets a Payment Request be raised on a Quotation: only on a Sales Order,
a Purchase Order, an invoice or Fees. Our checkout raised it on the cart's quotation, and made the order only
once the gateway had confirmed the money: no order exists until the payment is certain. Both hold here.

The request is raised on a PLACEHOLDER order: a draft Sales Order named `PENDING-<quotation>` (so it takes no
number of the order series, and a cart has at most one), built from the cart by the same mapping ERPNext uses
for the real order. A draft is not an order: nobody can ship it, invoice it, reserve stock for it or be told
about it (the shop's notifications and hooks fire on submit). When the gateway confirms, the REAL order is
made exactly as before (`place_order` / `handle_payment_success`), the request moves to it (it always did),
and the placeholder is dropped. A payment that never comes leaves the cart untouched: the placeholder is
released with the unpaid requests, when the cart is emptied, or by `release_stale` after HOLD_HOURS.

Everywhere the shop used to read "the request points at a Sales Order" as "the order exists", it now asks
`confirmed_order`: the order the request ends on, once it is a real (submitted) one.
"""

import frappe
from frappe import _
from frappe.model.mapper import get_mapped_doc
from frappe.utils import add_to_date, flt, now_datetime, today

from webshop.webshop.shopping_cart.shop_rights import shop_rights

PLACEHOLDER_PREFIX = "PENDING-"
# How long a payment may take before the shop gives the placeholder back, and with it the requests that moved no
# money. A card session or a TWINT code lasts minutes, but a hosted payment page stays valid for hours (a gateway
# answering after the request was deleted leaves money with no record in the ERP): a day, the longest of them.
# Money that did arrive keeps its documents whatever this says.
HOLD_HOURS = 24
# A request in one of these states moved no money; the others (Paid, Completed...) did.
UNPAID_STATUSES = ("Draft", "Failed", "Initiated", "Requested")
# Attempts at a gateway that may still turn into money: `failed` is not final for every gateway (a late
# confirmation moves it to `succeeded`), `processing` and `requires_action` are waiting for the buyer or the bank.
LIVE_INTENTS = ("requires_action", "processing", "failed")
# Intents that ARE money.
MONEY_INTENTS = ("succeeded", "refunded")


def placeholder_name(quotation_name):
	return f"{PLACEHOLDER_PREFIX}{quotation_name}"


def is_placeholder(sales_order_name):
	# case-insensitive: the database finds `pending-qtn-1` as it finds `PENDING-QTN-1`, and so must this
	return bool(sales_order_name) and str(sales_order_name).upper().startswith(PLACEHOLDER_PREFIX)


def quotation_of(placeholder):
	"""The cart a placeholder stands for (its name carries it)."""
	return str(placeholder)[len(PLACEHOLDER_PREFIX) :]


def confirmed_order(payment_request):
	"""The real order a payment request ends on, or None.

	`payment_request` is a document or a row with `reference_doctype` and `reference_name`. A request that points
	at the placeholder, or at a cancelled order, has no order yet."""
	if payment_request.get("reference_doctype") != "Sales Order" or not payment_request.get("reference_name"):
		return None
	name = payment_request.get("reference_name")
	if is_placeholder(name):
		return None
	return name if frappe.db.get_value("Sales Order", name, "docstatus") == 1 else None


def carrier_for(quotation):
	"""The placeholder a payment request for this cart is raised on: made, kept, or made again when the cart changed."""
	if quotation.get("quotation_to") != "Customer":
		frappe.throw(_("This cart cannot be paid online."))
	name = placeholder_name(quotation.name)
	existing = frappe.db.exists("Sales Order", name)
	if existing:
		if is_of_this_cart(name, quotation) and is_current(name, quotation):
			# The customer is still here: the hold starts over.
			touch(name)
			return name
		if not release(quotation.name):
			# Money is on its way for the old content: it concludes that one, a new request waits.
			frappe.throw(_("A payment for this cart is being processed. Please wait a moment."))
	return _make(quotation, name)


def touch(placeholder):
	"""The customer is still here: the hold of the placeholder starts over."""
	frappe.db.set_value("Sales Order", placeholder, "modified", now_datetime(), update_modified=False)


def is_of_this_cart(placeholder, quotation):
	"""Frappe gives the number of a deleted cart back when it was the last one: a new cart can then carry the name
	of a cart that is gone, whose placeholder a payment left behind. A placeholder made BEFORE the cart is not its."""
	made = frappe.db.get_value("Sales Order", placeholder, "creation")
	return bool(made) and made >= quotation.creation


def _signature(doc):
	"""What a cart is for a payment: its lines and its discount. Prices follow the price list and are not compared:
	the amount to pay is the quotation's at the moment the request is raised."""
	lines = sorted((row.item_code, flt(row.qty, 3)) for row in doc.get("items") or [])
	return (tuple(lines), flt(doc.get("discount_amount"), 2))


def is_current(placeholder, quotation):
	order = frappe.get_doc("Sales Order", placeholder)
	return order.docstatus == 0 and _signature(order) == _signature(quotation)


def _make(quotation, name):
	order = _map(quotation)
	order.order_type = "Shopping Cart"
	# The dates of the day: an order is made now, not on the day the cart was started (upstream refuses a payment
	# due before its posting date).
	order.transaction_date = today()
	order.delivery_date = today()
	for row in order.get("payment_schedule") or []:
		if row.due_date and str(row.due_date) < today():
			row.due_date = today()
	if quotation.get("discount_amount"):
		order.apply_discount_on = quotation.get("apply_discount_on") or "Grand Total"
		order.discount_amount = quotation.discount_amount
	order.flags.ignore_permissions = True
	user = frappe.session.user
	try:
		with shop_rights():
			order.insert(ignore_permissions=True, set_name=name)
	except frappe.DuplicateEntryError:
		# Two clicks on the same cart: the other call made it.
		frappe.clear_messages()
		return name
	if user != "Administrator":
		# The cart is the customer's; so is the order that stands for it.
		frappe.db.set_value(
			"Sales Order", name, {"owner": user, "modified_by": user}, update_modified=False
		)
	return name


def _map(quotation):
	"""Quotation -> Sales Order, as ERPNext maps it for the real order (selling/doctype/quotation/quotation.py,
	`_make_sales_order`), but from a quotation that is still the cart: upstream's mapping refuses anything but a
	submitted one, and submitting the cart is what must wait for the money."""
	from erpnext.selling.doctype.quotation.quotation import _make_customer

	customer = _make_customer(quotation.name, True)

	def set_missing_values(source, target):
		if customer:
			target.customer = customer.name
			target.customer_name = customer.customer_name
			if not target.get("sales_team"):
				for row in customer.get("sales_team") or []:
					target.append(
						"sales_team",
						{
							"sales_person": row.sales_person,
							"allocated_percentage": row.allocated_percentage or None,
							"commission_rate": row.commission_rate,
						},
					)
		if source.referral_sales_partner:
			target.sales_partner = source.referral_sales_partner
			target.commission_rate = frappe.get_value(
				"Sales Partner", source.referral_sales_partner, "commission_rate"
			)
		target.flags.ignore_permissions = True
		target.run_method("set_missing_values")
		target.run_method("calculate_taxes_and_totals")

	def update_item(source, target, source_parent):
		target.qty = source.qty
		target.stock_qty = flt(target.qty) * flt(source.conversion_factor)

	with shop_rights():
		return get_mapped_doc(
			"Quotation",
			quotation.name,
			{
				"Quotation": {"doctype": "Sales Order", "validation": {"docstatus": ["=", 0]}},
				"Quotation Item": {
					"doctype": "Sales Order Item",
					"field_map": {"parent": "prevdoc_docname", "name": "quotation_item"},
					"postprocess": update_item,
					"condition": lambda row: not row.is_alternative,
				},
				"Sales Taxes and Charges": {"doctype": "Sales Taxes and Charges", "reset_value": True},
				"Sales Team": {"doctype": "Sales Team", "add_if_empty": True},
				"Payment Schedule": {"doctype": "Payment Schedule", "add_if_empty": True},
			},
			None,
			set_missing_values,
			ignore_permissions=True,
		)


def release(quotation_name):
	"""Give a cart's placeholder back, with the unpaid requests raised on it. Returns whether it is gone.

	Money keeps its documents: a request that was paid, or one whose gateway attempt succeeded, stays, and so
	does the placeholder it points at."""
	from webshop.webshop.shopping_cart.cart import _release_unsuccessful_payment_requests

	name = placeholder_name(quotation_name)
	if not frappe.db.exists("Sales Order", name):
		return True
	_release_unsuccessful_payment_requests(name, reference_doctype="Sales Order")
	# A request that is left, not cancelled, moved money (Paid, Completed): it keeps its order. A cancelled one is
	# a released attempt, which Frappe does not count as a link when the order is deleted.
	if frappe.db.exists(
		"Payment Request", {"reference_doctype": "Sales Order", "reference_name": name, "docstatus": ["<", 2]}
	):
		return False
	return drop(name)


def drop(placeholder):
	"""Delete a placeholder nothing points at any more. False (and logged) when Frappe refuses."""
	if not is_placeholder(placeholder) or not frappe.db.exists("Sales Order", placeholder):
		return True
	if frappe.db.get_value("Sales Order", placeholder, "docstatus") != 0:
		return False
	try:
		# permanently: a placeholder is transient, and a Deleted Document row would keep the whole cart (customer and
		# address included) for ever
		frappe.delete_doc("Sales Order", placeholder, ignore_permissions=True, delete_permanently=True)
	except Exception:
		frappe.clear_messages()
		frappe.log_error("Webshop: could not delete a pending order", frappe.get_traceback())
		return False
	return True


def move_request_to(payment_request, sales_order):
	"""The request ends on the real order; the placeholder it stood on is dropped.

	The other requests raised on the same placeholder (an earlier attempt the gateway refused, a second method the
	buyer opened and left) follow it to the real order, as those raised on the quotation always stayed with the
	cart it became an order: a callback of theirs that comes late then finds an order and is not lost, and nothing
	is deleted that a gateway may still answer for. Nothing then points at the placeholder, which can go."""
	previous = payment_request.reference_name if payment_request.reference_doctype == "Sales Order" else None
	payment_request.db_set("reference_doctype", "Sales Order", update_modified=False)
	payment_request.db_set("reference_name", sales_order, update_modified=False)
	if is_placeholder(previous):
		frappe.db.set_value(
			"Payment Request",
			{"reference_doctype": "Sales Order", "reference_name": previous},
			"reference_name",
			sales_order,
			update_modified=False,
		)
		drop(previous)


def requests_of(placeholder):
	return frappe.get_all(
		"Payment Request",
		filters={"reference_doctype": "Sales Order", "reference_name": placeholder, "docstatus": ["<", 2]},
		fields=["name", "status"],
	)


def has_money(placeholder):
	"""Whether money moved on a request of this placeholder: a request that is not an unpaid one, or an intent that
	succeeded (a request of such an intent may still read Draft when its finalisation failed)."""
	requests = requests_of(placeholder)
	if any(row.status not in UNPAID_STATUSES for row in requests):
		return True
	return _intents_of(requests, MONEY_INTENTS) != []


def has_live_attempt(placeholder, since):
	"""Whether a gateway attempt of this placeholder moved after `since`: it may still answer."""
	return _intents_of(requests_of(placeholder), LIVE_INTENTS, since=since) != []


def _intents_of(requests, statuses, since=None):
	if not requests or not frappe.db.exists("DocType", "Payment Intent"):
		return []
	filters = {
		"reference_doctype": "Payment Request",
		"reference_name": ["in", [row.name for row in requests]],
		"status": ["in", statuses],
	}
	if since:
		filters["modified"] = [">", since]
	return frappe.get_all("Payment Intent", filters=filters, pluck="name")


def _note_once(placeholder, text):
	"""Say once, on the placeholder and in the Error Log, what keeps it: an hourly job must not repeat itself."""
	if frappe.db.exists(
		"Comment",
		{"reference_doctype": "Sales Order", "reference_name": placeholder, "comment_type": "Info", "content": text},
	):
		return
	frappe.get_doc("Sales Order", placeholder).add_comment("Info", text)
	frappe.log_error("Webshop: a pending order is kept", f"{placeholder}: {text}")


def amount_matches(payment_request, quotation):
	"""Whether the amount a request asked of the gateway is the amount of the cart it is concluded on. The order is
	built from the cart as it stands when the money arrives and the payment is booked against its invoice: a cart
	changed after the request was raised would order, and book, more or less than the buyer paid."""
	asked = flt(payment_request.get("grand_total"), 2)
	if asked <= 0:
		return True
	due = flt(quotation.get("rounded_total") or quotation.get("grand_total"), 2)
	return abs(asked - due) < 0.01


def refuse_submit(doc, method=None):
	"""`before_submit` of Sales Order (hooks.py): a placeholder is no order, whoever presses Submit."""
	if is_placeholder(doc.name):
		frappe.throw(_("This is the draft of a payment in progress, not an order: it cannot be submitted."))


def release_stale():
	"""Scheduled, hourly: the placeholders whose payment never came (HOLD_HOURS).

	Never one that money touched (it keeps its documents, and says so once), nor one whose gateway attempt moved
	within the hold: a hosted page or a bank may answer late, and a request deleted by then leaves money with no
	record in the ERP."""
	cutoff = add_to_date(now_datetime(), hours=-HOLD_HOURS)
	for name in frappe.get_all(
		"Sales Order",
		filters={"docstatus": 0, "name": ["like", f"{PLACEHOLDER_PREFIX}%"], "modified": ["<", cutoff]},
		pluck="name",
	):
		try:
			if has_money(name):
				_note_once(
					name,
					_("Kept: a payment moved on a request of this draft, which was not made an order. Look at its requests."),
				)
			elif not has_live_attempt(name, cutoff):
				release(quotation_of(name))
			frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit -- a scheduled job
		except Exception:
			frappe.db.rollback()
			frappe.log_error("Webshop: could not release a stale pending order", frappe.get_traceback())
