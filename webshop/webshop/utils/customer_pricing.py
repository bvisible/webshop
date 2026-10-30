# //// Neoffice — added file (no upstream equivalent). The customer's price, in one place.
# //// It lived in quick_order/api.py, written for the quick order; the reseller catalogue and the
# //// partner API need the very same answer, and two copies of a pricing rule are exactly how a
# //// catalogue ends up printing a price the cart will not charge. The bodies below are the quick
# //// order's, moved unchanged apart from the names (quick_order/api.py imports them under its old
# //// private names). Moved on 2026-10-30.
"""What THIS customer pays: the list their cart is priced on, the rate on it, the shop's rules on top.

Every function takes the party handed to it and never resolves the session a second time, so a job
that computes for a customer (a catalogue, a feed) and a request that serves one agree on the figure.
"""

import frappe
from frappe.utils import flt, fmt_money, getdate, nowdate

from webshop.webshop.multi_site import effective_price_list
from webshop.webshop.shopping_cart.cart import _set_price_list


# //// Neoffice — added as _currency() (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"), a shared currency lookup; moved here as currency_of() on 2026-10-30
def currency_of(price_list):
	"""The currency of a price list, else the site's default."""
	return (
		frappe.db.get_value("Price List", price_list, "currency") if price_list else None
	) or frappe.defaults.get_global_default("currency")


# //// Neoffice — customer_price_list() now takes party, and list_rates() reads the struck price straight from Item Price (cf339c1c40 "fix(quick-order): le prix barré vient d'Item Price, la liste du client reçoit le client"): _set_price_list() used to resolve the session a second time to find the customer, which crashed for a guest with no cart, and upstream get_price() only formats `mrp`, it never returns the raw figure
def customer_price_list(settings, party):
	"""The list the cart will price this party at: the site's, else the customer's
	own (or their group's), else the shop's default — `_set_price_list`, the cart's
	rule, handed the party so it never resolves the session a second time."""
	stand_in = frappe._dict(party_name=party.get("name")) if party else None
	return _set_price_list(settings, stand_in) or effective_price_list()


def list_rates(item_codes, price_list):
	"""{item_code: rate} straight from Item Price, before any rule — the struck figure."""
	today = getdate(nowdate())
	rows = frappe.get_all(
		"Item Price",
		filters={"item_code": ["in", item_codes], "price_list": price_list, "selling": 1},
		fields=["item_code", "price_list_rate", "uom", "valid_from", "valid_upto"],
		order_by="valid_from desc",
	)
	stock_uoms = dict(frappe.get_all("Item", filters={"name": ["in", item_codes]}, fields=["name", "stock_uom"], as_list=True))
	rates = {}
	for row in rows:
		if row.valid_from and getdate(row.valid_from) > today:
			continue
		if row.valid_upto and getdate(row.valid_upto) < today:
			continue
		if row.uom and row.uom != stock_uoms.get(row.item_code):
			continue
		rates.setdefault(row.item_code, flt(row.price_list_rate))
	return rates


# //// Neoffice — added file-local helper (the fallback for stock ERPNext's get_price mrp bug, see price_of): the plain Item Price rate for one item, shaped like get_price's return, used when there is a price but no pricing rule so upstream get_price cannot return one.
def raw_price(item_code, price_list):
	"""One item's Item Price rate on `price_list`, formatted — no pricing rule applied.

	The safe answer when stock ERPNext's get_price crashes on a priced item with no
	rule: no rule means no discount, so the list rate is exactly what the cart carries.
	"""
	rate = list_rates([item_code], price_list).get(item_code)
	if rate is None:
		return None
	return {"price_list_rate": rate, "formatted_price": fmt_money(rate, currency=currency_of(price_list))}


# //// Neoffice — reworded (cf339c1c40 "fix(quick-order): le prix barré vient d'Item Price, la liste du client reçoit le client"): the list_price/mrp handling this docstring used to describe moved out to list_rates()/prices_for()
def price_of(item_code, price_list, party, settings, warehouse=None):
	"""What the product page shows for one item: the list rate with the shop's
	pricing rules applied — the figure the cart will carry. None without a price."""
	from erpnext.utilities.product import get_price

	customer_group = (party.get("customer_group") if party else None) or settings.default_customer_group
	kwargs = {"party": party if party and party.get("doctype") == "Customer" else None}
	try:
		price = get_price(item_code, price_list, customer_group, settings.company, warehouse=warehouse, **kwargs)
	except TypeError:
		# stock ERPNext: get_price knows no warehouse keyword
		try:
			price = get_price(item_code, price_list, customer_group, settings.company, **kwargs)
		except UnboundLocalError:
			# //// Neoffice — stock ERPNext version-15 get_price references `mrp` before it is
			# //// assigned whenever an item HAS a price but NO pricing rule matches: `mrp` is set
			# //// only inside `if pricing_rule:`, then read two lines later in `if mrp != …`. Our
			# //// erpnext fork captures `mrp` before that block; upstream does not, so quick-order
			# //// crashed on a stock ERPNext for every priced item without a rule — the common case
			# //// (measured on the CI's fresh site). No rule means no discount, so the correct
			# //// figure is the plain Item Price rate: fall back to it rather than lose the price.
			# //// Remove this shim once the CI's ERPNext carries the fork's get_price.
			price = raw_price(item_code, price_list)
	if not price or price.get("price_list_rate") is None:
		return None
	# //// Neoffice — no longer reads price.get("mrp") here (cf339c1c40 "fix(quick-order): le prix barré vient d'Item Price, la liste du client reçoit le client"): upstream get_price() only returns a formatted mrp string, never the raw value, so the struck list price is now read from Item Price by list_rates()
	return {"price": flt(price.get("price_list_rate")), "formatted_price": price.get("formatted_price") or ""}


# //// Neoffice — docstring now explains the split with list_rates() (cf339c1c40 "fix(quick-order): le prix barré vient d'Item Price, la liste du client reçoit le client")
def prices_for(item_codes, price_list, party, settings, warehouse=None):
	"""{item_code: price dict} for every variant priced on price_list.

	The struck list price comes from Item Price itself: the fork's get_price
	names it `mrp`, upstream's only formats it, so neither is relied upon.
	"""
	if not price_list or not item_codes:
		return {}
	# //// Neoffice — fetches the struck price separately (cf339c1c40 "fix(quick-order): le prix barré vient d'Item Price, la liste du client reçoit le client"): price_of()/get_price() no longer carries it, since upstream's mrp is only a formatted string
	currency = currency_of(price_list)
	listed_rates = list_rates(item_codes, price_list)
	prices = {}
	for code in item_codes:
		priced = price_of(code, price_list, party, settings, warehouse)
		# //// Neoffice — list_price now set here from list_rates(), not from price_of()'s former mrp field (cf339c1c40 "fix(quick-order): le prix barré vient d'Item Price, la liste du client reçoit le client")
		if not priced:
			continue
		priced["list_price"] = None
		priced["formatted_list_price"] = None
		list_rate = listed_rates.get(code)
		if list_rate is not None and flt(list_rate) != priced["price"]:
			priced["list_price"] = flt(list_rate)
			priced["formatted_list_price"] = fmt_money(list_rate, currency=currency)
		prices[code] = priced
	return prices
