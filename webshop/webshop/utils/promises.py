# //// Neoffice — added file (no upstream equivalent).
"""The shop's promises: what a customer is told before buying.

Free delivery from an amount, the delivery time, the return period, one free line —
set once on Webshop Settings (Store tab), overridable per site on the Website
Profile. The product page prints them under the buy button; nothing is invented
when a field is empty, and an empty set prints nothing at all.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

PROMISE_FIELDS = ("free_shipping_from", "delivery_delay", "return_days", "promise_note")


def shopping_promises(settings=None):
	"""The promise lines, in reading order: [{key, icon, text}, ...]."""
	if settings is None:
		from webshop.webshop.doctype.webshop_settings.webshop_settings import get_shopping_cart_settings

		settings = get_shopping_cart_settings()
	get = settings.get if hasattr(settings, "get") else lambda key, default=None: getattr(settings, key, default)

	promises = []
	threshold = flt(get("free_shipping_from"))
	if threshold > 0:
		from webshop.webshop.utils.utils import webshop_fmt_money

		amount = webshop_fmt_money(threshold, currency=_price_list_currency(get("price_list")))
		promises.append({"key": "shipping", "icon": "truck", "text": _("Free delivery from {0}").format(amount)})
	delay = (get("delivery_delay") or "").strip()
	if delay:
		promises.append({"key": "delay", "icon": "clock", "text": _("Delivered in {0}").format(delay)})
	days = cint(get("return_days"))
	if days > 0:
		promises.append({"key": "returns", "icon": "return", "text": _("{0}-day returns").format(days)})
	note = (get("promise_note") or "").strip()
	if note:
		promises.append({"key": "note", "icon": "check", "text": note})
	return promises


def _price_list_currency(price_list):
	currency = price_list and frappe.get_cached_value("Price List", price_list, "currency")
	return currency or frappe.defaults.get_global_default("currency")
