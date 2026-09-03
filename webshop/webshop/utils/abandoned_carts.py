# //// Neoffice — added file (abandoned carts, no upstream equivalent).
"""Remind a signed-in customer of the cart they left behind.

The cart is already a Quotation with the customer's email; this only reads
it. Every hour: the carts untouched for longer than each configured delay
get their next email (Webshop Settings: delays, template, and from which
email a single-use coupon is offered). What was sent is an Abandoned Cart
Reminder and a Communication on the Customer; an order placed from the cart
marks the reminders converted.
"""

import random
import string

import frappe
from frappe import _
from frappe.utils import add_days, add_to_date, cint, flt, get_url, getdate, now_datetime, nowdate

MAX_CART_AGE_DAYS = 30


def parse_delays(text):
	delays = sorted({cint(x) for x in (text or "").split(",") if cint(x) > 0})
	return delays or [1, 24, 72]


def send_abandoned_cart_reminders():
	"""Hourly."""
	from webshop.webshop.utils.follow_ups import unsubscribed

	settings = frappe.get_cached_doc("Webshop Settings")
	if not settings.get("enable_abandoned_cart_emails") or not settings.get("abandoned_cart_template"):
		return 0
	delays = parse_delays(settings.abandoned_cart_delays)
	now = now_datetime()
	guest_customer = settings.get("guest_customer")

	carts = frappe.db.sql(
		"""select q.name, q.party_name, q.contact_email, q.modified, q.grand_total
		from `tabQuotation` q
		where q.order_type = 'Shopping Cart' and q.docstatus = 0 and q.status = 'Draft'
		  and ifnull(q.party_name, '') != '' and ifnull(q.contact_email, '') like '%%@%%'
		  and q.modified <= %(latest)s and q.modified >= %(oldest)s
		  and exists (select 1 from `tabQuotation Item` qi where qi.parent = q.name)""",
		{
			"latest": add_to_date(now, hours=-delays[0]),
			"oldest": add_days(now, -MAX_CART_AGE_DAYS),
		},
		as_dict=True,
	)
	sent = 0
	for cart in carts:
		if guest_customer and cart.party_name == guest_customer:
			continue
		reminders = frappe.get_all(
			"Abandoned Cart Reminder",
			filters={"quotation": cart.name},
			fields=["step", "sent_on", "coupon_code"],
			order_by="step asc",
		)
		step = (max(r.step for r in reminders) if reminders else 0) + 1
		if step > len(delays):
			continue
		if add_to_date(cart.modified, hours=delays[step - 1]) > now:
			continue
		if reminders and reminders[-1].sent_on and reminders[-1].sent_on > cart.modified:
			# the previous email is more recent than the cart's last change: space them
			if add_to_date(reminders[-1].sent_on, hours=delays[step - 1] - delays[step - 2]) > now:
				continue
		if unsubscribed(cart.contact_email, cart.party_name):
			continue
		frappe.db.savepoint("abandoned_cart")
		try:
			send_reminder(cart, step, settings, delays, previous_coupon=next((r.coupon_code for r in reminders if r.coupon_code), None))
			frappe.db.release_savepoint("abandoned_cart")
			sent += 1
		except Exception:
			frappe.db.rollback(save_point="abandoned_cart")
			frappe.log_error("Abandoned cart reminder failed", f"{cart.name}\n{frappe.get_traceback()}")
	return sent


def send_reminder(cart, step, settings, delays, previous_coupon=None):
	from webshop.webshop.utils.follow_ups import send_customer_email
	from webshop.webshop.utils.utils import format_currency_value

	quotation = frappe.get_doc("Quotation", cart.name)
	coupon = previous_coupon
	incentive_step = cint(settings.get("abandoned_cart_incentive_step"))
	if not coupon and incentive_step and step >= incentive_step:
		coupon = create_coupon(
			quotation.party_name,
			flt(settings.get("abandoned_cart_discount_percentage")) or 10,
			cint(settings.get("abandoned_cart_coupon_validity_days")) or 7,
			quotation.currency,
		)

	cart_url = get_url("/cart" + (f"?coupon={coupon}" if coupon else ""))
	context = {
		"doc": quotation,
		"customer_name": quotation.customer_name or "",
		"cart_items": [
			{
				"item_name": row.item_name,
				"qty": flt(row.qty),
				"amount": format_currency_value(row.amount, currency=quotation.currency),
			}
			for row in quotation.items
		],
		"cart_total": format_currency_value(quotation.grand_total, currency=quotation.currency),
		"cart_url": cart_url,
		"coupon_code": coupon,
		"coupon_valid_until": frappe.format_value(
			frappe.db.get_value("Coupon Code", coupon, "valid_upto"), {"fieldtype": "Date"}
		)
		if coupon
		else None,
		"discount_percentage": flt(settings.get("abandoned_cart_discount_percentage")) or 10,
		"step": step,
		"shop_url": get_url("/"),
		"shop_name": frappe.db.get_single_value("Website Settings", "app_name") or "",
	}
	template = frappe.get_doc("Email Template", settings.abandoned_cart_template)
	subject = frappe.render_template(template.subject, context)
	message = frappe.render_template(template.response_, context)
	communication = send_customer_email(quotation.party_name, cart.contact_email, subject, message)

	frappe.get_doc(
		{
			"doctype": "Abandoned Cart Reminder",
			"quotation": quotation.name,
			"customer": quotation.party_name,
			"email": cart.contact_email,
			"step": step,
			"sent_on": now_datetime(),
			"cart_total": quotation.grand_total,
			"coupon_code": coupon,
			"pricing_rule": frappe.db.get_value("Coupon Code", coupon, "pricing_rule") if coupon else None,
			"communication": communication,
		}
	).insert(ignore_permissions=True)
	return communication


def create_coupon(customer, percentage, valid_days, currency):
	"""A single-use coupon for this customer: a Pricing Rule on the whole cart.

	Letters only: Coupon Code derives its code from the name and drops the
	digits, so a name with digits would not be the code the customer types.
	"""
	code = "".join(random.choices(string.ascii_uppercase, k=8))
	while frappe.db.exists("Coupon Code", code):
		code = "".join(random.choices(string.ascii_uppercase, k=8))
	rule = frappe.get_doc(
		{
			"doctype": "Pricing Rule",
			"title": f"Cart reminder {code}",
			"apply_on": "Transaction",
			"price_or_product_discount": "Price",
			"rate_or_discount": "Discount Percentage",
			"discount_percentage": percentage,
			"apply_discount_on": "Grand Total",
			"selling": 1,
			"coupon_code_based": 1,
			"currency": currency,
			"valid_from": nowdate(),
			"valid_upto": add_days(nowdate(), valid_days),
		}
	)
	rule.flags.ignore_permissions = True
	rule.insert()
	coupon = frappe.get_doc(
		{
			"doctype": "Coupon Code",
			"coupon_name": code,
			"coupon_type": "Promotional",
			"customer": customer,
			"pricing_rule": rule.name,
			"valid_from": nowdate(),
			"valid_upto": add_days(nowdate(), valid_days),
			"maximum_use": 1,
		}
	)
	coupon.flags.ignore_permissions = True
	coupon.insert()
	return coupon.name


def mark_converted(doc, method=None):
	"""Sales Order submitted from a cart: its reminders did their job."""
	quotations = {row.get("prevdoc_docname") for row in doc.items if row.get("prevdoc_docname")}
	for quotation in quotations:
		for name in frappe.get_all(
			"Abandoned Cart Reminder", filters={"quotation": quotation, "converted": 0}, pluck="name"
		):
			frappe.db.set_value(
				"Abandoned Cart Reminder",
				name,
				{"converted": 1, "converted_order": doc.name},
				update_modified=False,
			)
