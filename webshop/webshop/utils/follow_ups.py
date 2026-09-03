# //// Neoffice — added file (purchase follow-ups, no upstream equivalent).
"""The emails a customer receives after a purchase, per product.

A Purchase Follow-up says "after a purchase of X, this email N days later,
then that one". Submitting an order (or a direct invoice) enrols the
customer once per flow and item: a Purchase Follow-up Entry, with the date
of its next email. A daily job sends what is due, logs each email on the
entry and as a Communication on the Customer (the customer's timeline shows
every relaunch), then schedules the next step. The customer can unsubscribe
from every mail: Frappe's own Email Unsubscribe, checked before each send.

Why not Frappe's Notification "Days After": one notification per (delay ×
product), the exact day only (a missed run is lost), no log, no stop rule.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, getdate, now_datetime, nowdate, get_url

SECOND_HAND_CONDITIONS = ("Second-hand", "Refurbished")
TOO_OLD_DAYS = 14  # a step due more than two weeks ago is not sent late


# --- enrolment -----------------------------------------------------------


def enroll_from_sales_order(doc, method=None):
	if doc.docstatus == 1:
		_enroll(doc, is_website=doc.get("order_type") == "Shopping Cart")


def enroll_from_sales_invoice(doc, method=None):
	if doc.docstatus != 1:
		return
	if doc.get("is_return"):
		stop_for_return(doc)
		return
	if any(row.get("sales_order") for row in doc.items):
		return  # the order enrolled the customer already
	_enroll(doc, is_website=False)


def on_cancel(doc, method=None):
	stop_entries(doc.doctype, doc.name, _("Cancelled"))


def stop_for_return(invoice):
	if not invoice.get("return_against"):
		return
	sources = {("Sales Invoice", invoice.return_against)}
	for order in frappe.get_all(
		"Sales Invoice Item", filters={"parent": invoice.return_against}, pluck="sales_order", distinct=True
	):
		if order:
			sources.add(("Sales Order", order))
	for doctype, name in sources:
		stop_entries(doctype, name, _("Returned"), only_flows_stopping_on_return=True)


def stop_entries(source_doctype, source_name, reason, only_flows_stopping_on_return=False):
	entries = frappe.get_all(
		"Purchase Follow-up Entry",
		filters={"source_doctype": source_doctype, "source_name": source_name, "status": "Scheduled"},
		fields=["name", "flow"],
	)
	for entry in entries:
		if only_flows_stopping_on_return and not frappe.db.get_value("Purchase Follow-up", entry.flow, "stop_on_return"):
			continue
		frappe.db.set_value(
			"Purchase Follow-up Entry", entry.name, {"status": "Stopped", "stop_reason": reason}, update_modified=False
		)


def customer_email(doc):
	email = doc.get("contact_email")
	if not email and doc.get("customer"):
		email = frappe.db.get_value("Customer", doc.customer, "email_id")
	return email if email and "@" in email else None


def item_facts(item_code):
	fields = ["name", "item_name", "item_group", "brand"]
	for optional in ("item_condition", "replenishment_days"):
		if frappe.db.has_column("Item", optional):
			fields.append(optional)
	return frappe.db.get_value("Item", item_code, fields, as_dict=True)


def flow_matches(flow, item, is_website, customer_group):
	if flow.only_website_orders and not is_website:
		return False
	if flow.only_customer_group and flow.only_customer_group != customer_group:
		return False
	kind = flow.trigger_type
	if kind == "All Purchases":
		return True
	if kind == "Item":
		return flow.trigger_item == item.name
	if kind == "Item Group":
		from webshop.webshop.utils.cross_sell import _group_and_children

		return item.item_group in _group_and_children(flow.trigger_item_group)
	if kind == "Brand":
		return bool(item.brand) and item.brand == flow.trigger_brand
	if kind == "Second-hand Units":
		return item.get("item_condition") in SECOND_HAND_CONDITIONS
	return False


def step_date(purchase_date, step, item):
	"""When a step goes out, or None when the item cannot say (no cycle)."""
	if step.use_item_cycle:
		days = cint(item.get("replenishment_days"))
		if not days:
			return None
		return add_days(purchase_date, int(round(days * 0.8)))
	return add_days(purchase_date, cint(step.days_after))


def _enroll(doc, is_website):
	email = customer_email(doc)
	if not email or not doc.get("customer"):
		return
	flows = [
		frappe.get_cached_doc("Purchase Follow-up", name)
		for name in frappe.get_all("Purchase Follow-up", filters={"enabled": 1}, pluck="name")
	]
	if not flows:
		return

	customer_group = frappe.db.get_value("Customer", doc.customer, "customer_group")
	purchase_date = getdate(doc.get("transaction_date") or doc.get("posting_date") or nowdate())
	seen = set()
	for row in doc.items:
		if not row.item_code or row.item_code in seen or row.get("is_free_item"):
			continue
		seen.add(row.item_code)
		item = item_facts(row.item_code)
		if not item:
			continue
		for flow in flows:
			if not flow_matches(flow, item, is_website, customer_group):
				continue
			if frappe.db.exists(
				"Purchase Follow-up Entry",
				{"flow": flow.name, "source_name": doc.name, "item_code": row.item_code},
			):
				continue
			first = flow.steps[0] if flow.steps else None
			send_on = step_date(purchase_date, first, item) if first else None
			if not send_on:
				continue
			frappe.get_doc(
				{
					"doctype": "Purchase Follow-up Entry",
					"flow": flow.name,
					"customer": doc.customer,
					"email": email,
					"source_doctype": doc.doctype,
					"source_name": doc.name,
					"item_code": row.item_code,
					"purchase_date": purchase_date,
					"next_step": 1,
					"next_send_on": send_on,
					"status": "Scheduled",
				}
			).insert(ignore_permissions=True)
			frappe.db.set_value(
				"Purchase Follow-up", flow.name, "enrolled", cint(flow.enrolled) + 1, update_modified=False
			)
			flow.enrolled = cint(flow.enrolled) + 1


# --- sending -------------------------------------------------------------


def send_due_follow_ups():
	"""Daily: every entry whose next email is due today or earlier."""
	today = getdate(nowdate())
	due = frappe.get_all(
		"Purchase Follow-up Entry",
		filters={"status": "Scheduled", "next_send_on": ("<=", today)},
		pluck="name",
		order_by="next_send_on asc",
	)
	sent = 0
	for name in due:
		try:
			if process_entry(frappe.get_doc("Purchase Follow-up Entry", name), today):
				sent += 1
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error("Purchase follow-up failed", f"{name}\n{frappe.get_traceback()}")
	return sent


def unsubscribed(email, customer=None):
	if frappe.db.exists("Email Unsubscribe", {"email": email, "global_unsubscribe": 1}):
		return True
	return bool(
		customer
		and frappe.db.exists(
			"Email Unsubscribe", {"email": email, "reference_doctype": "Customer", "reference_name": customer}
		)
	)


def reordered_since(entry):
	return bool(
		frappe.db.exists(
			"Sales Order",
			{
				"customer": entry.customer,
				"docstatus": 1,
				"transaction_date": (">", entry.purchase_date),
				"name": ("!=", entry.source_name),
			},
		)
	)


def process_entry(entry, today=None):
	"""Send the entry's next step if it is due; returns True when a mail went out."""
	today = today or getdate(nowdate())
	flow = frappe.get_doc("Purchase Follow-up", entry.flow)
	if not flow.enabled:
		return False  # stays scheduled: the flow may be switched on again
	steps = flow.steps
	if cint(entry.next_step) > len(steps):
		_finish(entry, "Completed")
		return False
	step = steps[cint(entry.next_step) - 1]

	if unsubscribed(entry.email, entry.customer):
		_finish(entry, "Stopped", _("Unsubscribed"))
		return False
	if step.stop_if_reordered and reordered_since(entry):
		_finish(entry, "Stopped", _("Ordered again"))
		return False

	outcome, communication = "Skipped (too old)", None
	if getdate(entry.next_send_on) >= add_days(today, -TOO_OLD_DAYS):
		communication = send_step(entry, flow, step)
		outcome = "Sent"
	entry.append(
		"log",
		{
			"step": entry.next_step,
			"label": step.label,
			"sent_on": now_datetime(),
			"communication": communication,
			"outcome": outcome,
		},
	)
	_schedule_next(entry, flow, steps)
	entry.flags.ignore_permissions = True
	entry.save()
	return outcome == "Sent"


def _finish(entry, status, reason=None):
	entry.status = status
	entry.stop_reason = reason
	entry.flags.ignore_permissions = True
	entry.save()


def _schedule_next(entry, flow, steps):
	next_step = cint(entry.next_step) + 1
	item = item_facts(entry.item_code) or frappe._dict()
	while next_step <= len(steps):
		send_on = step_date(getdate(entry.purchase_date), steps[next_step - 1], item)
		if send_on:
			entry.next_step = next_step
			entry.next_send_on = send_on
			return
		next_step += 1  # this step cannot be dated for this item: skip it
	entry.next_step = next_step
	entry.status = "Completed"


def outgoing_sender():
	return (
		frappe.db.get_value("Email Account", {"default_outgoing": 1, "enable_outgoing": 1}, "email_id")
		or frappe.db.get_single_value("Website Settings", "email")
		or "noreply@example.com"
	)


def build_context(entry, flow):
	from webshop.webshop.utils.cross_sell import describe, matching_offers
	from webshop.webshop.utils.used_items import is_second_hand, warranty_months

	customer = frappe.db.get_value(
		"Customer", entry.customer, ["customer_name", "customer_group"], as_dict=True
	) or frappe._dict()
	item = frappe.db.get_value("Item", entry.item_code, ["item_name", "warranty_period"], as_dict=True) or frappe._dict()
	facts = item_facts(entry.item_code) or frappe._dict()
	page = frappe.db.get_value(
		"Website Item", {"item_code": entry.item_code, "published": 1}, ["route", "website_image"], as_dict=True
	)
	product_url = get_url("/" + page.route) if page else get_url("/all-products")
	offers = []
	for offer in matching_offers([entry.item_code], placement="product")[:3]:
		shown = describe(offer)
		if shown:
			shown["url"] = get_url("/" + shown["route"])
			if shown.get("image"):
				shown["image"] = get_url(shown["image"])
			offers.append(shown)
	shop_name = frappe.db.get_single_value("Website Settings", "app_name") or ""
	return {
		"doc": entry,
		"entry": entry,
		"flow": flow,
		"customer_name": customer.get("customer_name") or "",
		"item_code": entry.item_code,
		"item_name": item.get("item_name") or entry.item_code,
		"is_second_hand": is_second_hand(facts.get("item_condition")),
		"warranty_months": warranty_months(item.get("warranty_period")),
		"purchase_date": frappe.format_value(entry.purchase_date, {"fieldtype": "Date"}),
		"order": entry.source_name,
		"product_url": product_url,
		"product_image": get_url(page.website_image) if page and page.website_image else None,
		"review_url": product_url + "#write-review",
		"reorder_url": get_url(f"/cart?add={entry.item_code}&qty=1"),
		"shop_url": get_url("/"),
		"shop_name": shop_name,
		"offers": offers,
	}


def send_step(entry, flow, step):
	"""Render the step's template, log it on the customer, queue the mail."""
	template = frappe.get_doc("Email Template", step.email_template)
	context = build_context(entry, flow)
	subject = frappe.render_template(template.subject, context)
	message = frappe.render_template(template.response_, context)
	communication = send_customer_email(entry.customer, entry.email, subject, message)
	frappe.db.set_value("Purchase Follow-up", flow.name, "sent", cint(flow.sent) + 1, update_modified=False)
	return communication


def send_customer_email(customer, email, subject, message):
	"""A Communication on the Customer (its timeline shows it), then the mail.

	The mail carries Frappe's unsubscribe link, scoped to the Customer: one
	click stops every follow-up and reminder for that customer.
	"""
	communication = frappe.get_doc(
		{
			"doctype": "Communication",
			"communication_type": "Communication",
			"communication_medium": "Email",
			"sent_or_received": "Sent",
			"subject": subject,
			"content": message,
			"sender": outgoing_sender(),
			"recipients": email,
			"reference_doctype": "Customer",
			"reference_name": customer,
		}
	).insert(ignore_permissions=True)
	frappe.sendmail(
		recipients=[email],
		subject=subject,
		message=message,
		reference_doctype="Customer",
		reference_name=customer,
		communication=communication.name,
		unsubscribe_message=_("Stop receiving these emails"),
	)
	return communication.name


# --- the customer's form -------------------------------------------------


def customer_dashboard(data):
	"""Follow-ups and cart reminders under the customer's connections."""
	data.setdefault("transactions", []).append(
		{"label": _("Webshop emails"), "items": ["Purchase Follow-up Entry", "Abandoned Cart Reminder"]}
	)
	return data
