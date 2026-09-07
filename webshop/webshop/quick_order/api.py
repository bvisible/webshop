# //// Neoffice — added file (the quick order, no upstream equivalent).
"""The quick order: forty lines in a few minutes, at the keyboard.

Open to whoever may fill a cart on this site — a signed-in customer of any
group, and an anonymous visitor where the shop allows a guest cart — because
nothing in it is professional but the pace. Identity and tariff come from the
session and from the site being browsed, never from the browser; every dict
returned names its fields explicitly, so a purchase price or a valuation has
no way out. The cart is written through the same rule as "add to cart" —
`validate_cart_line` — once for the whole batch.

The matrix is the portal counterpart of neoffice_theme's `get_variant_matrix`,
which a Website User cannot call (it needs the desk's read permission on Item,
and answers 403 — correctly). This one starts from a Website Item published on
this site, prices at the site's tariff and counts stock by the shop's own rule.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, flt, fmt_money, getdate, nowdate

from webshop.webshop.multi_site import (
	effective_price_list,
	excluded_item_names,
	require_login_to_buy,
	site_is_business_only,
)
from webshop.webshop.shopping_cart.cart import (
	_get_cart_quotation,
	# //// Neoffice — added _set_price_list import (6696be727a "feat(quick-order): le prix du client, et la commande en Excel"): the grid now follows the cart's own price-list resolution
	_set_price_list,
	apply_cart_settings,
	available_cart_qty,
	get_party,
	# //// Neoffice — removed is_b2b_customer_group import (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): the reseller-only gate is gone, so this import is unused
	is_gift_card_item,
	set_cart_count,
)
from webshop.webshop.utils.product import get_web_items_qty_in_stock
from webshop.webshop.variant_selector.item_variants_cache import ItemVariantsCacheManager

MAX_LINES = 200
SEARCH_LIMIT = 10
SEARCH_LIMIT_MAX = 25
PAGE_ROUTE = "/quick-order"


def cart_settings():
	return frappe.get_cached_doc("Webshop Settings")


# ---------------------------------------------------------------------------
# who may be here: whoever may fill a cart on this site
# ---------------------------------------------------------------------------


# //// Neoffice — guest_allowed()/require_shopper()/may_use_quick_order() replace is_reseller()/require_reseller() (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): the page and its endpoints now serve any signed-in customer plus an anonymous visitor where the shop allows a guest cart, not resellers only.
def guest_allowed(settings=None):
	"""An anonymous visitor may use the page where the shop lets them fill a cart."""
	if site_is_business_only():
		return False
	return bool(cint((settings or cart_settings()).get("enable_guest_cart")))


# //// Neoffice — require_shopper() replaces require_reseller() (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): admits any signed-in customer, and a guest where the shop allows it
def require_shopper():
	"""The party of the session, or a PermissionError. Never trusts an argument.

	Signed in: the customer behind the account. Anonymous: the shop's guest
	customer, on a site that sells to visitors. The same rule as the cart.
	"""
	# //// Neoffice — added the guest branch (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): an anonymous visitor is admitted here where the shop allows a guest cart, instead of always being refused.
	if frappe.session.user == "Guest":
		if not guest_allowed():
			frappe.throw(_("Connectez-vous pour utiliser la commande rapide."), frappe.PermissionError)
		party = get_party()
		if not party:
			frappe.throw(_("Connectez-vous pour utiliser la commande rapide."), frappe.PermissionError)
		return party
	party = get_party()
	if not party:
		frappe.throw(_("Aucun compte client n'est rattaché à votre utilisateur."), frappe.PermissionError)
	# //// Neoffice — removed the reseller-only check (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): any signed-in customer is now admitted, not resellers only
	return party


# //// Neoffice — added may_use_quick_order() (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): lets templates/links check the new gate without raising
def may_use_quick_order():
	"""True when require_shopper() would let the session in — for the links."""
	try:
		require_shopper()
		return True
	except frappe.PermissionError:
		frappe.clear_last_message()
		return False


# ---------------------------------------------------------------------------
# what is sellable here
# ---------------------------------------------------------------------------

WEBSITE_ITEM_FIELDS = [
	"name",
	"item_code",
	"web_item_name",
	"website_image",
	"route",
	"has_variants",
	"variant_of",
	"website_warehouse",
]


def sellable_website_item(item_code):
	"""The published Website Item of item_code, visible on this site — or None."""
	row = frappe.db.get_value(
		"Website Item", {"item_code": item_code, "published": 1}, WEBSITE_ITEM_FIELDS, as_dict=True
	)
	if not row:
		return None
	if row.name in excluded_item_names():
		return None
	return row


def resolve(code):
	"""What a scanned or typed code designates on this site, or None.

	A barcode first (`Item Barcode`), then an item code — a variant's or a simple
	item's. The item, or the model it is a variant of, must be published here.
	"""
	code = (code or "").strip()
	if not code:
		return None
	item_code = frappe.db.get_value("Item Barcode", {"barcode": code}, "parent")
	if not item_code and frappe.db.exists("Item", code):
		item_code = code
	if not item_code:
		return None
	item = frappe.db.get_value(
		"Item", item_code, ["name", "item_name", "variant_of", "has_variants", "disabled"], as_dict=True
	)
	if not item or item.disabled:
		return None
	template = item.variant_of or (item.name if item.has_variants else None)
	website_item = sellable_website_item(template or item.name)
	if not website_item:
		return None
	attrs = {}
	if item.variant_of:
		attrs = {
			row.attribute: row.attribute_value
			for row in frappe.get_all(
				"Item Variant Attribute", filters={"parent": item.name}, fields=["attribute", "attribute_value"]
			)
		}
	return frappe._dict(
		item_code=item.name,
		item_name=item.item_name,
		template=template,
		attrs=attrs,
		website_item=website_item,
	)


def _card(website_item):
	"""One search suggestion. Only what the list shows.

	A variant published on its own (some shops give a colour its own page) is
	still a cell of its model's grid: it comes back as a `variant` pointing at
	the template, never as a lone item.
	"""
	has_variants = cint(website_item.has_variants)
	card = {
		"kind": "template" if has_variants else "item",
		"item_code": website_item.item_code,
		"name": website_item.web_item_name,
		"image": website_item.website_image,
		"route": website_item.route,
		"variant_count": frappe.db.count("Item", {"variant_of": website_item.item_code, "disabled": 0}) if has_variants else 0,
	}
	if website_item.get("variant_of") and sellable_website_item(website_item.variant_of):
		card["kind"] = "variant"
		card["template"] = website_item.variant_of
		card["attrs"] = {
			row.attribute: row.attribute_value
			for row in frappe.get_all(
				"Item Variant Attribute",
				filters={"parent": website_item.item_code},
				fields=["attribute", "attribute_value"],
			)
		}
	return card


# //// Neoffice — allow_guest=True (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): an anonymous visitor may call this now; require_shopper() below still enforces the site's own rule
@frappe.whitelist(allow_guest=True)
def search_references(query, limit=SEARCH_LIMIT):
	"""Suggestions for the search bar: published items of this site, by code, name or barcode.

	An exact match on a barcode or a variant's code comes first, as a `variant`
	pointing at its model, so Enter on a scanned code opens the right cell.
	"""
	# //// Neoffice — require_shopper() replaces require_reseller() (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille")
	require_shopper()
	query = (query or "").strip()
	if len(query) < 2:
		return []
	limit = min(cint(limit) or SEARCH_LIMIT, SEARCH_LIMIT_MAX)

	results, seen = [], set()
	exact = resolve(query)
	if exact:
		# //// Neoffice — the suggestion for a model typed by its exact code now carries variant_count again (6696be727a "feat(quick-order): le prix du client, et la commande en Excel")
		if exact.attrs:
			results.append(
				{
					"kind": "variant",
					"item_code": exact.item_code,
					"name": exact.item_name,
					"template": exact.template,
					"attrs": exact.attrs,
					"image": exact.website_item.website_image,
					"route": exact.website_item.route,
					"variant_count": 0,
				}
			)
		else:
			# the model itself, or a simple item: its card, variant count included
			results.append(_card(exact.website_item))
		seen.add(exact.website_item.item_code)

	like = "%" + query.replace(" ", "%") + "%"
	filters = {"published": 1}
	excluded = excluded_item_names()
	if excluded:
		filters["name"] = ["not in", excluded]
	rows = frappe.get_all(
		"Website Item",
		filters=filters,
		or_filters=[["item_code", "like", like], ["web_item_name", "like", like], ["item_name", "like", like]],
		fields=WEBSITE_ITEM_FIELDS,
		order_by="web_item_name asc",
		limit_page_length=limit,
	)
	for row in rows:
		if row.item_code in seen:
			continue
		seen.add(row.item_code)
		results.append(_card(row))
	return results[:limit]


# //// Neoffice — allow_guest=True (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): same gate change as search_references
@frappe.whitelist(allow_guest=True)
def resolve_code(code):
	"""A scanned code, resolved on this site — `{unknown: true}` when it is not sold here."""
	# //// Neoffice — require_shopper() replaces require_reseller() (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille")
	require_shopper()
	found = resolve(code)
	if not found:
		return {"unknown": True, "code": (code or "").strip()[:140]}
	return {
		"item_code": found.item_code,
		"item_name": found.item_name,
		"template": found.template,
		"attrs": found.attrs,
		"route": found.website_item.route,
	}


# ---------------------------------------------------------------------------
# the matrix of one model
# ---------------------------------------------------------------------------


def _sort_values(values):
	"""The trade's order for sizes when neoffice_theme is there (XS → S → M → L,
	board lengths numerically); numbers sorted, else the master's order, without it."""
	try:
		from neoffice_theme.stock import _smart_sort_values
	except ImportError:
		_smart_sort_values = None
	if _smart_sort_values:
		return _smart_sort_values(values)
	try:
		return sorted(values, key=lambda v: float(str(v).replace(",", ".")))
	except (TypeError, ValueError):
		return values


def _ordered_values(attribute, used):
	"""The values of one attribute actually used by the variants, in display order."""
	ordered = frappe.get_all(
		"Item Attribute Value",
		filters={"parent": attribute, "attribute_value": ["in", list(used) or [""]]},
		order_by="idx asc",
		pluck="attribute_value",
	)
	ordered += [value for value in used if value not in ordered]
	return _sort_values(ordered)


# //// Neoffice — customer_price_list() now takes party, and _list_rates() reads the struck price straight from Item Price (cf339c1c40 "fix(quick-order): le prix barré vient d'Item Price, la liste du client reçoit le client"): _set_price_list() used to resolve the session a second time to find the customer, which crashed for a guest with no cart, and upstream get_price() only formats `mrp`, it never returns the raw figure
def customer_price_list(settings, party):
	"""The list the cart will price this party at: the site's, else the customer's
	own (or their group's), else the shop's default — `_set_price_list`, the cart's
	rule, handed the party so it never resolves the session a second time."""
	stand_in = frappe._dict(party_name=party.get("name")) if party else None
	return _set_price_list(settings, stand_in) or effective_price_list()


def _list_rates(item_codes, price_list):
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


# //// Neoffice — reworded (cf339c1c40 "fix(quick-order): le prix barré vient d'Item Price, la liste du client reçoit le client"): the list_price/mrp handling this docstring used to describe moved out to _list_rates()/_prices()
def _price_of(item_code, price_list, party, settings, warehouse=None):
	"""What the product page shows for one item: the list rate with the shop's
	pricing rules applied — the figure the cart will carry. None without a price."""
	from erpnext.utilities.product import get_price

	customer_group = (party.get("customer_group") if party else None) or settings.default_customer_group
	kwargs = {"party": party if party and party.get("doctype") == "Customer" else None}
	try:
		price = get_price(item_code, price_list, customer_group, settings.company, warehouse=warehouse, **kwargs)
	except TypeError:
		# stock ERPNext: get_price knows no warehouse keyword
		price = get_price(item_code, price_list, customer_group, settings.company, **kwargs)
	if not price or price.get("price_list_rate") is None:
		return None
	# //// Neoffice — no longer reads price.get("mrp") here (cf339c1c40 "fix(quick-order): le prix barré vient d'Item Price, la liste du client reçoit le client"): upstream get_price() only returns a formatted mrp string, never the raw value, so the struck list price is now read from Item Price by _list_rates()
	return {"price": flt(price.get("price_list_rate")), "formatted_price": price.get("formatted_price") or ""}


# //// Neoffice — docstring now explains the split with _list_rates() (cf339c1c40 "fix(quick-order): le prix barré vient d'Item Price, la liste du client reçoit le client")
def _prices(item_codes, price_list, party, settings, warehouse=None):
	"""{item_code: price dict} for every variant priced on price_list.

	The struck list price comes from Item Price itself: the fork's get_price
	names it `mrp`, upstream's only formats it, so neither is relied upon.
	"""
	if not price_list or not item_codes:
		return {}
	# //// Neoffice — fetches the struck price separately (cf339c1c40 "fix(quick-order): le prix barré vient d'Item Price, la liste du client reçoit le client"): _price_of()/get_price() no longer carries it, since upstream's mrp is only a formatted string
	currency = _currency(price_list)
	list_rates = _list_rates(item_codes, price_list)
	prices = {}
	for code in item_codes:
		priced = _price_of(code, price_list, party, settings, warehouse)
		# //// Neoffice — list_price now set here from _list_rates(), not from _price_of()'s former mrp field (cf339c1c40 "fix(quick-order): le prix barré vient d'Item Price, la liste du client reçoit le client")
		if not priced:
			continue
		priced["list_price"] = None
		priced["formatted_list_price"] = None
		list_rate = list_rates.get(code)
		if list_rate is not None and flt(list_rate) != priced["price"]:
			priced["list_price"] = flt(list_rate)
			priced["formatted_list_price"] = fmt_money(list_rate, currency=currency)
		prices[code] = priced
	return prices


# //// Neoffice — extended _stock's docstring and added the get_web_item_qty_in_stock fallback below for an item with no own website warehouse (42c10358d1 "fix(quick-order): produits simples tarifés par le serveur, steppers, plein écran")
def _stock(item_codes, website_item, settings):
	"""{item_code: available qty or None} by the shop's rule.

	Multi-warehouse sources when the feature is on; otherwise the template's
	website warehouse in one bulk query for the variants that share it, and the
	canonical per-item resolver (Website Item, then its template) for anything
	without one — a simple item rarely carries its own website warehouse, and
	that is what left its stock unknown. None = not a stock item (unlimited).
	"""
	from webshop.webshop.multi_warehouse import sources as mw_sources
	# //// Neoffice — added get_web_item_qty_in_stock import, used by the per-item fallback below (42c10358d1 "fix(quick-order): produits simples tarifés par le serveur, steppers, plein écran")
	from webshop.webshop.utils.product import get_web_item_qty_in_stock

	stock = {}
	remaining = list(item_codes)
	if mw_sources.is_enabled(settings):
		for code in item_codes:
			aggregate = mw_sources.get_aggregate_stock(code, settings)
			if aggregate is not None:
				stock[code] = flt(aggregate.stock_qty)
				remaining.remove(code)
	if not remaining:
		return stock
	stock_items = set(frappe.get_all("Item", filters={"name": ["in", remaining], "is_stock_item": 1}, pluck="name"))
	warehouse = website_item.website_warehouse or settings.get("default_warehouse")
	bulk = get_web_items_qty_in_stock([c for c in remaining if c in stock_items], warehouse) if warehouse else {}
	# //// Neoffice — added the per-item fallback below: a simple item without its own website warehouse used to be left out of `bulk` and reported no stock (42c10358d1 "fix(quick-order): produits simples tarifés par le serveur, steppers, plein écran")
	for code in remaining:
		if code not in stock_items:
			stock[code] = None
		elif code in bulk:
			stock[code] = flt(bulk[code])
		else:
			# no site warehouse on this item: the canonical rule resolves one from
			# the Website Item (or its template) exactly as the card and the page do
			stock[code] = flt(get_web_item_qty_in_stock(code, "website_warehouse").stock_qty)
	return stock


# //// Neoffice — added _currency() and switched get_matrix to allow_guest=True (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): a shared currency lookup (also used by add_lines and page_context below), and the matrix endpoint now admits an anonymous visitor via require_shopper()'s guest branch
def _currency(price_list):
	return (
		frappe.db.get_value("Price List", price_list, "currency") if price_list else None
	) or frappe.defaults.get_global_default("currency")


# //// Neoffice — added _simple_matrix: a simple item (no variants) used to stay stuck on "price on request" / "on order" because it never went through this pricing/stock path (42c10358d1 "fix(quick-order): produits simples tarifés par le serveur, steppers, plein écran")
def _simple_matrix(item_code, website_item, party):
	"""One published item with no variants, as a single-cell grid — priced and
	stocked by the same rules as a template's cells."""
	settings = cart_settings()
	price_list = customer_price_list(settings, party)
	currency = _currency(price_list)
	item = frappe.db.get_value("Item", item_code, ["item_name", "stock_uom"], as_dict=True) or frappe._dict()
	priced = _prices([item_code], price_list, party, settings, website_item.website_warehouse).get(item_code, {})
	stock = _stock([item_code], website_item, settings).get(item_code)
	return {
		"template": {
			"item_code": website_item.item_code,
			"name": website_item.web_item_name,
			"image": website_item.website_image,
			"route": website_item.route,
		},
		"attributes": [],
		"variants": [
			{
				"item_code": item_code,
				"item_name": item.get("item_name") or website_item.web_item_name,
				"attrs": {},
				"price": priced.get("price"),
				"formatted_price": priced.get("formatted_price") or None,
				"list_price": priced.get("list_price"),
				"formatted_list_price": priced.get("formatted_list_price") or None,
				"stock": stock,
				"uom": item.get("stock_uom"),
			}
		],
		"currency": currency,
		"simple": True,
	}


@frappe.whitelist(allow_guest=True)
def get_matrix(template):
	"""Everything the grid of one model needs, scoped to the site, in one call."""
	# //// Neoffice — party is now kept, to price each variant for this customer's group/party (6696be727a "feat(quick-order): le prix du client, et la commande en Excel")
	party = require_shopper()
	website_item = sellable_website_item(template)
	if not website_item:
		frappe.throw(_("Ce modèle n'est pas disponible sur cette boutique."), frappe.DoesNotExistError)

	# //// Neoffice — a simple item is priced by the server too: it comes back as a
	# //// one-cell grid, not a client-side placeholder that never fetched its price
	# //// (which showed "Prix sur demande" / "Sur commande" for a priced item).
	if not cint(frappe.db.get_value("Item", template, "has_variants")):
		return _simple_matrix(template, website_item, party)

	attributes = frappe.get_all(
		"Item Variant Attribute", filters={"parent": template}, fields=["attribute"], order_by="idx asc", pluck="attribute"
	)
	attrs_by_variant = {}
	for item_code, attribute, value in ItemVariantsCacheManager(template).get_item_variants_data() or []:
		attrs_by_variant.setdefault(item_code, {})[attribute] = value
	codes = list(attrs_by_variant)

	settings = cart_settings()
	# //// Neoffice — party now passed in, instead of customer_price_list() resolving the session itself (cf339c1c40 "fix(quick-order): le prix barré vient d'Item Price, la liste du client reçoit le client")
	price_list = customer_price_list(settings, party)
	currency = _currency(price_list)

	out = {
		"template": {
			"item_code": website_item.item_code,
			"name": website_item.web_item_name,
			"image": website_item.website_image,
			"route": website_item.route,
		},
		"attributes": [],
		"variants": [],
		"currency": currency,
	}
	if not codes:
		return out

	items = {
		row.name: row
		for row in frappe.get_all(
			"Item", filters={"name": ["in", codes]}, fields=["name", "item_name", "image", "stock_uom"]
		)
	}
	# //// Neoffice — prices computed per party/customer-group instead of a flat site price (6696be727a "feat(quick-order): le prix du client, et la commande en Excel")
	prices = _prices(codes, price_list, party, settings, website_item.website_warehouse)
	stock = _stock(codes, website_item, settings)

	used = {attribute: set() for attribute in attributes}
	for attrs in attrs_by_variant.values():
		for attribute, value in attrs.items():
			if attribute in used:
				used[attribute].add(value)
	out["attributes"] = [{"attribute": a, "values": _ordered_values(a, used[a])} for a in attributes]

	for code in codes:
		item = items.get(code)
		if not item:
			continue
		# //// Neoffice — priced per customer instead of read off a flat site price map (6696be727a "feat(quick-order): le prix du client, et la commande en Excel")
		priced = prices.get(code) or {}
		out["variants"].append(
			{
				"item_code": code,
				"item_name": item.item_name,
				"attrs": attrs_by_variant[code],
				# //// Neoffice — list_price/formatted_list_price added, so the grid can show the rule's struck-through price like the product page (6696be727a "feat(quick-order): le prix du client, et la commande en Excel")
				"price": priced.get("price"),
				"formatted_price": priced.get("formatted_price") or None,
				"list_price": priced.get("list_price"),
				"formatted_list_price": priced.get("formatted_list_price") or None,
				"stock": stock.get(code),
				"uom": item.stock_uom,
			}
		)
	return out


# ---------------------------------------------------------------------------
# the batch into the cart
# ---------------------------------------------------------------------------


def _save_on_behalf(quotation, party):
	"""Price and save the customer's own cart with the shop's rights.

	Upstream ERPNext version-15 checks, inside the quotation's validate, the read
	permission on Item (`get_item_details`) and on the receivable Account
	(`get_party_account`) — permissions a portal customer never holds. Measured
	on the CI's stock site: PermissionError twice; the fleet's fork has neither
	check yet (neoffice-maintenance#277). The document stays the customer's:
	owner and modified_by are put back once saved.
	"""
	user = frappe.session.user
	was_new = quotation.is_new()
	frappe.set_user("Administrator")
	try:
		apply_cart_settings(party, quotation)
		quotation.payment_schedule = []
		quotation.save(ignore_version=True)
	finally:
		frappe.set_user(user)
	stamp = {"modified_by": user}
	if was_new:
		stamp["owner"] = user
	frappe.db.set_value("Quotation", quotation.name, stamp, update_modified=False)
	quotation.update(stamp)


def _parse_lines(lines):
	if isinstance(lines, str):
		lines = json.loads(lines or "[]")
	if not isinstance(lines, list):
		frappe.throw(_("Les lignes sont invalides."))
	if len(lines) > MAX_LINES:
		frappe.throw(_("Au plus {0} lignes par envoi.").format(MAX_LINES))
	wanted = {}
	for line in lines:
		if not isinstance(line, dict):
			continue
		item_code = (line.get("item_code") or "").strip()
		qty = cint(line.get("qty"))
		warehouse = (line.get("warehouse") or "").strip() or None
		if not item_code or qty <= 0:
			continue
		key = (item_code, warehouse)
		wanted[key] = wanted.get(key, 0) + qty
	return wanted


# //// Neoffice — _check_lines() no longer gates or parses (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): it used to open with require_reseller(), require_login_to_buy() and _parse_lines(lines), and load the customer's own quotation itself; the caller add_lines() now does the gate/parsing/loading (guest or signed-in) and hands this function plain wanted/rows to validate.
def _check_lines(wanted, rows, settings, multi_enabled, party, price_list):
	"""Every wanted line against the rule of "add to cart", with the cart's rows in hand.

	Returns (accepted, capped, refused): accepted = [(item_code, warehouse, qty)]
	with the source resolved and the quantity the shop can serve on top of what
	the cart already holds.
	"""
	from webshop.webshop.multi_warehouse import sources as mw_sources

	# //// Neoffice — removed the gate/parse/quotation-load lines here (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): require_reseller(), require_login_to_buy() and _parse_lines(lines) used to open this function and load the quotation directly; add_lines() now does all of that and passes plain wanted/rows in.
	# //// Neoffice — reads plain dict rows instead of quotation.get("items") (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): a guest has no quotation yet, only the plain rows add_lines() builds from the guest cart
	def existing_row(item_code, warehouse):
		for row in rows:
			if row.get("item_code") != item_code:
				continue
			if not multi_enabled or (row.get("warehouse") or None) == (warehouse or None):
				return row
		return None

	# //// Neoffice — renamed from added/refused/capped to accepted/capped/refused (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): this function now only returns what to write, it no longer writes to a quotation itself
	accepted, capped, refused = [], [], []
	for (item_code, warehouse), qty in wanted.items():
		if not resolve(item_code):
			refused.append({"item_code": item_code, "qty": qty, "reason": _("Cet article n'est pas disponible sur cette boutique.")})
			continue
		if is_gift_card_item(item_code):
			refused.append({"item_code": item_code, "qty": qty, "reason": _("Les cartes cadeaux ne passent pas par la commande rapide.")})
			continue
		# //// Neoffice — an item with no price on the customer's list is "Prix sur demande":
		# //// it must not enter the cart at 0.00. The grid disables its cell too; this is the
		# //// server guard, so a forged call cannot slip a priceless line in (2026-09-07).
		if _price_of(item_code, price_list, party, settings) is None:
			refused.append({"item_code": item_code, "qty": qty, "reason": _("Pas de tarif pour cet article sur votre liste de prix (prix sur demande).")})
			continue

		if multi_enabled:
			allowed = mw_sources.get_allowed_warehouses(item_code, settings)
			if warehouse and allowed and warehouse not in allowed:
				refused.append({"item_code": item_code, "qty": qty, "reason": _("Source de stock invalide pour {0}").format(item_code)})
				continue
			# //// Neoffice — reads plain rows (row.get(...)) instead of quotation items (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille")
			if not warehouse:
				row = existing_row(item_code, None) or next((r for r in rows if r.get("item_code") == item_code), None)
				warehouse = (row.get("warehouse") if row else None) or mw_sources.resolve_target_warehouse(item_code, qty, settings)
		else:
			warehouse = frappe.get_cached_value("Website Item", {"item_code": item_code}, "website_warehouse")

		row = existing_row(item_code, warehouse)
		# //// Neoffice — row.get("qty") instead of row.qty (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): rows is a list of plain dicts now, not quotation items
		existing_qty = flt(row.get("qty")) if row else 0
		limit = available_cart_qty(item_code, warehouse, settings, multi_enabled)
		if limit.available is not None:
			room = flt(limit.available) - existing_qty
			if room <= 0:
				refused.append({"item_code": item_code, "qty": qty, "reason": _("Épuisé : {0} déjà au panier, rien de plus disponible.").format(int(existing_qty))})
				continue
			if qty > room:
				capped.append({"item_code": item_code, "asked": qty, "kept": int(room), "available": int(limit.available)})
				qty = int(room)
		# //// Neoffice — appends the tuple instead of writing the quotation row here (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): add_lines() now applies accepted lines to a guest's plain rows or a customer's quotation, whichever the caller has
		accepted.append((item_code, warehouse, qty))
	return accepted, capped, refused


# //// Neoffice — added _guest_cart_rows()/_write_guest_cart() (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): a visitor's batch has no quotation of its own; it goes through create_guest_quotation, the guest cart's own rebuild-from-list path
def _guest_cart_rows():
	"""The guest's cart as plain rows (what create_guest_quotation rebuilds from)."""
	from webshop.webshop.shopping_cart.guest_cart import create_guest_quotation

	existing = create_guest_quotation()
	rows = []
	if existing and existing.get("quotation_id"):
		for row in frappe.get_doc("Quotation", existing["quotation_id"]).items:
			line = frappe._dict(item_code=row.item_code, qty=row.qty, warehouse=row.warehouse)
			if is_gift_card_item(row.item_code):
				line.update({"rate": row.rate, "price_list_rate": row.price_list_rate})
				if row.get("gift_card_data"):
					line["gift_card_data"] = row.gift_card_data
			rows.append(line)
	return rows


# //// Neoffice — see the block marker above: rebuilds the guest cart from its whole list
def _write_guest_cart(rows, accepted, multi_enabled):
	"""The guest cart is rebuilt from its whole list, the way update_cart does it."""
	from webshop.webshop.shopping_cart.guest_cart import create_guest_quotation

	for item_code, warehouse, qty in accepted:
		for row in rows:
			if row.item_code == item_code and (not multi_enabled or (row.warehouse or None) == (warehouse or None)):
				row.qty = flt(row.qty) + qty
				row.warehouse = warehouse
				break
		else:
			rows.append(frappe._dict(item_code=item_code, qty=qty, warehouse=warehouse))
	result = create_guest_quotation([dict(row) for row in rows])
	if not result or not result.get("success"):
		frappe.throw(_("Impossible d'ouvrir un panier pour cette session."))
	return frappe.get_doc("Quotation", result["quotation_id"])


@frappe.whitelist(allow_guest=True, methods=["POST"])
def add_lines(lines):
	# //// Neoffice — add_lines() is now allow_guest=True and branches on is_guest, writing through _guest_cart_rows()/_write_guest_cart() for a visitor or the customer's own quotation otherwise (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille")
	"""The whole entry into the cart at once: one read, one save.

	Every line goes through the rule of "add to cart". What the shop cannot
	serve is capped to what it can, and named; what it cannot sell at all is
	refused, and named. The valid lines are never held back by a refused one.
	"""
	from webshop.webshop.multi_warehouse import sources as mw_sources

	party = require_shopper()
	require_login_to_buy()
	wanted = _parse_lines(lines)
	settings = cart_settings()
	multi_enabled = mw_sources.is_enabled(settings)
	is_guest = frappe.session.user == "Guest"

	if is_guest:
		quotation, rows = None, _guest_cart_rows()
	else:
		quotation = _get_cart_quotation(party)
		if not quotation:
			frappe.throw(_("Impossible d'ouvrir un panier pour ce compte."))
		rows = quotation.get("items") or []

	accepted, capped, refused = _check_lines(wanted, rows, settings, multi_enabled, party, customer_price_list(settings, party))

	if accepted:
		if is_guest:
			quotation = _write_guest_cart(rows, accepted, multi_enabled)
		else:
			# //// Neoffice — writes the customer's own quotation from the accepted tuples (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): this used to run directly inside _check_lines' loop
			for item_code, warehouse, qty in accepted:
				row = next(
					(
						r
						for r in quotation.get("items") or []
						if r.item_code == item_code and (not multi_enabled or (r.warehouse or None) == (warehouse or None))
					),
					None,
				)
				if row:
					row.qty = flt(row.qty) + qty
					row.warehouse = warehouse
				else:
					quotation.append("items", {"doctype": "Quotation Item", "item_code": item_code, "qty": qty, "warehouse": warehouse})
			quotation.flags.ignore_permissions = True
			quotation.flags.ignore_mandatory = True
			_save_on_behalf(quotation, party)
		set_cart_count(quotation)

	# //// Neoffice — quotation may be None (a guest with nothing accepted) (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): each figure falls back instead of assuming a quotation always exists
	total_qty = sum(flt(row.qty) for row in (quotation.get("items") if quotation else None) or [])
	grand_total = flt(quotation.grand_total) if quotation else 0
	currency = quotation.currency if quotation else _currency(customer_price_list(settings, party))
	return {
		# //// Neoffice — built from the accepted tuples (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): add_lines() no longer keeps its own added list
		"added": [{"item_code": code, "qty": qty} for code, _warehouse, qty in accepted],
		"capped": capped,
		"refused": refused,
		"cart": {
			"qty": total_qty,
			# //// Neoffice — see the block marker above: falls back when there is no quotation
			"total": grand_total,
			"formatted_total": fmt_money(grand_total, currency=currency),
			"url": "/cart",
		},
	}


# ---------------------------------------------------------------------------
# the page
# ---------------------------------------------------------------------------


def labels():
	return {
		# //// Neoffice — removed "title" (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): the page title is set directly in index.py's get_context(), this label was unused
		"lead": _("Tapez une référence, un nom ou un code-barres : la grille du modèle s'ouvre et vous saisissez les quantités au clavier."),
		"fullscreen": _("Plein écran"),
		"exit_fullscreen": _("Quitter le plein écran"),
		"placeholder": _("Référence, nom ou code-barres…"),
		"no_results": _("Aucun article publié ne correspond."),
		"unknown_code": _("Code inconnu sur cette boutique : {0}"),
		"searching": _("Recherche…"),
		"variants": _("{0} variantes"),
		"empty": _("Aucun modèle ouvert. Cherchez une référence pour commencer."),
		"close": _("Fermer"),
		"reset_model": _("Tout à zéro"),
		# //// Neoffice — added (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): label of each grid's own "add to cart" button
		"add_model": _("Ajouter"),
		"stock": _("Stock"),
		"available": _("{0} disponibles"),
		"out_of_stock": _("Épuisé"),
		# //// Neoffice — "Disponible" replaces "Sur commande" for an item not tracked in stock (42c10358d1 "fix(quick-order): produits simples tarifés par le serveur, steppers, plein écran")
		"unlimited": _("Disponible"),
		"price_on_request": _("Prix sur demande"),
		"none": _("Pas de variante"),
		"over_stock": _("Au-delà du stock disponible"),
		"capped_to_stock": _("Limité au stock disponible : {0}"),
		"pieces": _("pièces"),
		"lines": _("lignes"),
		"total": _("Total indicatif"),
		"total_note": _("Prix du tarif. Remises et TVA sont calculées au panier."),
		# //// Neoffice — reworded from "Envoyer au panier" (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): now that each grid has its own "add to cart", this button sends the whole draft
		"send": _("Tout envoyer au panier"),
		"sending": _("Envoi en cours…"),
		"clear": _("Tout effacer"),
		"clear_confirm": _("Effacer toute la saisie ?"),
		"see_cart": _("Voir le panier"),
		"resume": _("Reprendre la saisie du {0} ({1} lignes, {2} pièces) ?"),
		"resume_yes": _("Reprendre"),
		"resume_no": _("Effacer"),
		"report_added": _("{0} pièces ajoutées au panier."),
		"report_capped": _("Plafonné au stock :"),
		"report_capped_line": _("{0} : {1} demandées, {2} gardées ({3} disponibles)"),
		"report_refused": _("Non ajoutées :"),
		"nothing_to_send": _("Aucune quantité saisie."),
		"error": _("La requête a échoué. Réessayez."),
		# //// Neoffice — reworded to match the renamed "send everything" shortcut (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille")
		"shortcuts": _("Entrée : case suivante · Échap : retour à la recherche · Ctrl+Entrée : tout envoyer"),
		"qty": _("Qté"),
		"add": _("Ajouter"),
	}


def page_context(context):
	"""What /quick-order renders: the refusal, or the app and its configuration."""
	context.allowed = False
	context.reason = ""
	# //// Neoffice — reads the gate through require_shopper()/try-except (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): used to call get_party() directly and refuse with is_reseller()
	try:
		party = require_shopper()
	except frappe.PermissionError:
		frappe.clear_last_message()
		context.reason = _("Aucun compte client n'est rattaché à votre utilisateur.")
		return context
	# //// Neoffice — party now passed in, instead of customer_price_list() resolving the session itself (cf339c1c40 "fix(quick-order): le prix barré vient d'Item Price, la liste du client reçoit le client")
	price_list = customer_price_list(cart_settings(), party)
	context.allowed = True
	context.config = {
		"user": frappe.session.user,
		"customer": party.get("customer_name") or party.get("name"),
		"site": getattr(frappe.local, "website_profile", None) or frappe.local.site,
		# //// Neoffice — reuses _currency() instead of repeating the lookup (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille")
		"currency": _currency(price_list),
		"lang": frappe.local.lang or "fr",
		"max_lines": MAX_LINES,
		"cart_url": "/cart",
		"labels": labels(),
	}
	return context
