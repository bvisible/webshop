# //// Neoffice — added file (cross-sell offers, no upstream equivalent).
"""What the shop shows of a Cross Sell Offer, and the click that accepts it.

An offer matches when one of the items at hand (the product page, the cart)
is its trigger. The shop shows the offered item with the advantage the offer
promises; accepting it adds the item to the cart and ERPNext's own pricing
engine applies the generated Pricing Rule (doctype/cross_sell_offer).
"""

import json

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, nowdate

PLACEMENT_FLAG = {
	"product": "show_on_product_page",
	"cart": "show_in_cart",
	"checkout": "show_at_checkout",
}
DEFAULT_LIMIT = {"product": 3, "cart": 3, "checkout": 1}


def relation_headline(relation, trigger_name):
	wording = {
		"Consumable": _("The consumable for your {0}"),
		"Accessory": _("Goes well with {0}"),
		"Protection or Service": _("Protect your {0}"),
		"Upgrade": _("Go further than {0}"),
	}
	text = wording.get(relation)
	return text.format(trigger_name) if text and trigger_name else _("Complete your order")


def _parse_codes(item_codes):
	if isinstance(item_codes, str):
		try:
			item_codes = json.loads(item_codes or "[]")
		except ValueError:
			item_codes = [item_codes]
	return [c for c in (item_codes or []) if c]


def _open_cart():
	"""The session's open cart, without ever creating one."""
	from webshop.webshop.shopping_cart.cart import get_party

	filters = {"order_type": "Shopping Cart", "docstatus": 0}
	if frappe.session.user == "Guest":
		request = getattr(frappe.local, "request", None)
		guest_session_id = request.cookies.get("guest_session_id") if request else None
		if not guest_session_id:
			return None
		filters["guest_session_id"] = guest_session_id
	else:
		party = get_party()
		if not party:
			return None
		filters.update({"party_name": party.name, "contact_email": frappe.session.user})

	name = frappe.db.get_value("Quotation", filters, "name", order_by="modified desc")
	return frappe.get_doc("Quotation", name) if name else None


def cart_item_codes(cart=None):
	cart = cart or _open_cart()
	return [row.item_code for row in (cart.items if cart else []) if row.item_code]


def _customer():
	if frappe.session.user == "Guest":
		return None
	from webshop.webshop.shopping_cart.cart import get_party

	party = get_party()
	return party if party and getattr(party, "doctype", "Customer") == "Customer" else None


def _bought_recently(customer, item_code, days):
	since = add_days(nowdate(), -cint(days))
	return bool(
		frappe.db.sql(
			"""select 1 from `tabSales Order Item` soi
			join `tabSales Order` so on so.name = soi.parent
			where so.docstatus = 1 and so.customer = %s and soi.item_code = %s
			  and so.transaction_date >= %s limit 1""",
			(customer, item_code, since),
		)
	)


def _group_and_children(item_group):
	"""The group and everything under it (nested set)."""
	bounds = frappe.db.get_value("Item Group", item_group, ["lft", "rgt"], as_dict=True)
	if not bounds:
		return {item_group}
	return set(
		frappe.get_all(
			"Item Group", filters={"lft": (">=", bounds.lft), "rgt": ("<=", bounds.rgt)}, pluck="name"
		)
	)


def matching_offers(item_codes, cart_codes=None, customer=None, placement="cart"):
	"""The offers whose trigger is among `item_codes`, in priority order.

	`cart_codes` is what the cart holds (an offer already in the cart is
	hidden when it asks to be); `customer` is the Customer document of the
	visitor when signed in (customer group, recent purchases).
	"""
	flag = PLACEMENT_FLAG.get(placement)
	if not flag or not item_codes:
		return []

	item_codes = list(dict.fromkeys(item_codes))
	cart_codes = set(cart_codes or [])
	today = getdate(nowdate())
	items = {
		d.name: d
		for d in frappe.get_all(
			"Item", filters={"name": ("in", item_codes)}, fields=["name", "item_name", "item_group", "brand"]
		)
	}

	offers = frappe.get_all(
		"Cross Sell Offer",
		filters={"enabled": 1, flag: 1},
		fields=["*"],
		order_by="priority desc, modified desc",
	)

	matched, seen_offer_items = [], set()
	for offer in offers:
		if offer.valid_from and getdate(offer.valid_from) > today:
			continue
		if offer.valid_upto and getdate(offer.valid_upto) < today:
			continue
		if offer.offer_item in seen_offer_items or offer.offer_item in item_codes:
			continue
		if offer.skip_if_in_cart and offer.offer_item in cart_codes:
			continue
		if offer.only_customer_group and (not customer or customer.customer_group != offer.only_customer_group):
			continue
		if offer.skip_if_purchased_within_days and customer:
			if _bought_recently(customer.name, offer.offer_item, offer.skip_if_purchased_within_days):
				continue

		trigger = None
		if offer.trigger_type == "Item" and offer.trigger_item in items:
			trigger = items[offer.trigger_item]
		elif offer.trigger_type == "Item Group":
			trigger = next((d for d in items.values() if d.item_group in _group_and_children(offer.trigger_item_group)), None)
		elif offer.trigger_type == "Brand":
			trigger = next((d for d in items.values() if d.brand == offer.trigger_brand), None)
		if not trigger:
			continue

		offer.trigger_item_code = trigger.name
		offer.trigger_item_name = trigger.item_name
		seen_offer_items.add(offer.offer_item)
		matched.append(offer)
	return matched


def advantage(offer, price):
	"""(offer price, label) for a list price, the way the pricing rule will do it."""
	price = flt(price)
	if offer.discount_type == "Percentage":
		return flt(price * (1 - flt(offer.discount_percentage) / 100), 2), f"-{flt(offer.discount_percentage):g} %"
	if offer.discount_type == "Amount":
		return max(flt(price - flt(offer.discount_amount), 2), 0), None
	if offer.discount_type == "Free":
		return 0, _("Free")
	return price, None


def describe(offer):
	"""The offered item as the shop shows it, or None when it cannot be sold now."""
	from webshop.webshop.multi_site import excluded_item_names
	from webshop.webshop.shopping_cart.product_info import get_product_info_for_website
	from webshop.webshop.utils.utils import format_currency_value

	page = frappe.db.get_value(
		"Website Item",
		{"item_code": offer.offer_item, "published": 1},
		["name", "route", "web_item_name", "website_image", "thumbnail"],
		as_dict=True,
	)
	if not page or page.name in excluded_item_names():
		return None

	info = get_product_info_for_website(offer.offer_item, skip_quotation_creation=True)
	product_info = info.get("product_info") or {}
	price = product_info.get("price") or {}
	list_rate = flt(price.get("price_list_rate"))
	if not list_rate:
		return None

	settings = info.get("cart_settings") or frappe.get_cached_doc("Webshop Settings")
	in_stock = product_info.get("in_stock")
	if in_stock == 0 and not settings.get("allow_items_not_in_stock"):
		return None

	currency = price.get("currency")
	offer_price, label = advantage(offer, list_rate)
	if offer.discount_type == "Amount":
		label = "-" + format_currency_value(flt(offer.discount_amount), currency=currency)

	return {
		"name": offer.name,
		"headline": offer.headline or relation_headline(offer.relation, offer.trigger_item_name),
		"description": offer.description or "",
		"relation": offer.relation,
		"trigger_item_code": offer.trigger_item_code,
		"item_code": offer.offer_item,
		"web_item_name": page.web_item_name,
		"route": page.route,
		"image": page.thumbnail or page.website_image or "",
		"qty": flt(offer.offer_qty) or 1,
		"currency": currency,
		"price": list_rate,
		"formatted_price": format_currency_value(list_rate, currency=currency),
		"offer_price": offer_price,
		"formatted_offer_price": format_currency_value(offer_price, currency=currency),
		"advantage": label,
		"has_advantage": offer.discount_type != "None",
		"labels": {
			"add": _("Add"),
			"add_both": _("Add both"),
			"yes_add": _("Yes, add {0}").format(page.web_item_name),
			"instead_of": _("instead of {0}").format(format_currency_value(list_rate, currency=currency)),
			"added": _("Added to your cart"),
			"removed": _("Removed from your cart"),
			"title": _("Recommended with this item") if offer.get("_placement") == "product" else _("Complete your order"),
		},
	}


@frappe.whitelist(allow_guest=True)
def get_offers(placement, item_codes=None, limit=None):
	"""Offers for a placement: 'product' (the item viewed), 'cart', 'checkout'."""
	placement = placement if placement in PLACEMENT_FLAG else "cart"
	cart = _open_cart()
	cart_codes = cart_item_codes(cart)
	codes = _parse_codes(item_codes) if placement == "product" else cart_codes
	if not codes:
		return []

	customer = _customer()
	limit = cint(limit) or DEFAULT_LIMIT[placement]
	out = []
	for offer in matching_offers(codes, cart_codes=cart_codes, customer=customer, placement=placement):
		offer._placement = placement
		shown = describe(offer)
		if shown:
			shown["placement"] = placement
			out.append(shown)
		if len(out) >= limit:
			break

	if out:
		frappe.db.sql(
			"update `tabCross Sell Offer` set impressions = impressions + 1 where name in %(names)s",
			{"names": [o["name"] for o in out]},
		)
	return out


@frappe.whitelist(allow_guest=True)
def accept_offer(offer, with_trigger=0, remove=0):
	"""Put the offered item in the cart (or take it out again).

	`with_trigger`: also add the trigger item when it is not in the cart yet,
	for the product page where nothing has been added so far. The pricing
	rule generated from the offer does the pricing.
	"""
	from webshop.webshop.shopping_cart.cart import _get_cart_quotation, update_cart

	doc = frappe.get_doc("Cross Sell Offer", offer)
	today = getdate(nowdate())
	if not doc.enabled or (doc.valid_from and getdate(doc.valid_from) > today) or (
		doc.valid_upto and getdate(doc.valid_upto) < today
	):
		frappe.throw(_("This offer is no longer available."))

	if cint(remove):
		update_cart(doc.offer_item, 0)
	else:
		cart_codes = cart_item_codes()
		if cint(with_trigger) and doc.trigger_type == "Item" and doc.trigger_item not in cart_codes:
			update_cart(doc.trigger_item, 1, add_qty=True)
		update_cart(doc.offer_item, flt(doc.offer_qty) or 1, add_qty=True)
		frappe.db.sql(
			"update `tabCross Sell Offer` set acceptances = acceptances + 1 where name = %s", doc.name
		)

	quotation = _get_cart_quotation()
	line = next((d for d in quotation.items if d.item_code == doc.offer_item), None) if quotation else None
	return {
		"cart": quotation.name if quotation else None,
		"total_qty": quotation.total_qty if quotation else 0,
		"grand_total": quotation.grand_total if quotation else 0,
		"offer_item": doc.offer_item,
		"rate": line.rate if line else None,
		"discount_percentage": line.discount_percentage if line else None,
	}
