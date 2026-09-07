# //// Neoffice — added file (the reseller's quick order, no upstream equivalent).
"""The reseller's quick order: forty lines in a few minutes, at the keyboard.

Everything here answers a signed-in reseller and nobody else. Identity and
tariff come from the session and from the site being browsed, never from the
browser; every dict returned names its fields explicitly, so a purchase price
or a valuation has no way out. The cart is written through the same rule as
"add to cart" — `validate_cart_line` — once for the whole batch.

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
	apply_cart_settings,
	available_cart_qty,
	get_party,
	is_b2b_customer_group,
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
# who may be here
# ---------------------------------------------------------------------------


def is_reseller(party=None, settings=None):
	"""A professional account.

	On a site reserved for business accounts every admitted account is one; on
	any other site, a customer whose group is one of the shop's B2B groups.
	"""
	if not party:
		return False
	if site_is_business_only():
		return True
	group = party.get("customer_group") or frappe.db.get_value("Customer", party.get("name"), "customer_group")
	return is_b2b_customer_group(group, settings or cart_settings())


def require_reseller():
	"""The party of the session, or a PermissionError. Never trusts an argument."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Connectez-vous pour accéder à la commande rapide."), frappe.PermissionError)
	party = get_party()
	if not party:
		frappe.throw(_("Aucun compte client n'est rattaché à votre utilisateur."), frappe.PermissionError)
	if not is_reseller(party):
		frappe.throw(_("La commande rapide est réservée aux comptes professionnels."), frappe.PermissionError)
	return party


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


@frappe.whitelist()
def search_references(query, limit=SEARCH_LIMIT):
	"""Suggestions for the search bar: published items of this site, by code, name or barcode.

	An exact match on a barcode or a variant's code comes first, as a `variant`
	pointing at its model, so Enter on a scanned code opens the right cell.
	"""
	require_reseller()
	query = (query or "").strip()
	if len(query) < 2:
		return []
	limit = min(cint(limit) or SEARCH_LIMIT, SEARCH_LIMIT_MAX)

	results, seen = [], set()
	exact = resolve(query)
	if exact:
		results.append(
			{
				"kind": "variant" if exact.attrs else _card(exact.website_item)["kind"],
				"item_code": exact.item_code,
				"name": exact.item_name,
				"template": exact.template,
				"attrs": exact.attrs,
				"image": exact.website_item.website_image,
				"route": exact.website_item.route,
				"variant_count": 0,
			}
		)
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


@frappe.whitelist()
def resolve_code(code):
	"""A scanned code, resolved on this site — `{unknown: true}` when it is not sold here."""
	require_reseller()
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


def _prices(item_codes, price_list):
	"""{item_code: rate} on price_list, valid today; the stock UOM's row when several."""
	if not price_list or not item_codes:
		return {}
	today = getdate(nowdate())
	rows = frappe.get_all(
		"Item Price",
		filters={"item_code": ["in", item_codes], "price_list": price_list, "selling": 1},
		fields=["item_code", "price_list_rate", "uom", "valid_from", "valid_upto"],
		order_by="valid_from desc",
	)
	stock_uoms = dict(frappe.get_all("Item", filters={"name": ["in", item_codes]}, fields=["name", "stock_uom"], as_list=True))
	prices = {}
	for row in rows:
		if row.valid_from and getdate(row.valid_from) > today:
			continue
		if row.valid_upto and getdate(row.valid_upto) < today:
			continue
		if row.uom and row.uom != stock_uoms.get(row.item_code):
			continue
		prices.setdefault(row.item_code, flt(row.price_list_rate))
	return prices


def _stock(item_codes, website_item, settings):
	"""{item_code: available qty or None} by the shop's rule — sources when the
	multi-warehouse feature is on, the model's website warehouse otherwise."""
	from webshop.webshop.multi_warehouse import sources as mw_sources

	stock = {}
	remaining = list(item_codes)
	if mw_sources.is_enabled(settings):
		for code in item_codes:
			aggregate = mw_sources.get_aggregate_stock(code, settings)
			if aggregate is not None:
				stock[code] = flt(aggregate.stock_qty)
				remaining.remove(code)
	if remaining:
		warehouse = website_item.website_warehouse or settings.get("default_warehouse")
		bulk = get_web_items_qty_in_stock(remaining, warehouse) if warehouse else {}
		stock_items = set(frappe.get_all("Item", filters={"name": ["in", remaining], "is_stock_item": 1}, pluck="name"))
		for code in remaining:
			stock[code] = flt(bulk.get(code, 0)) if code in stock_items else None
	return stock


@frappe.whitelist()
def get_matrix(template):
	"""Everything the grid of one model needs, cadré par le site, in one call."""
	require_reseller()
	website_item = sellable_website_item(template)
	if not website_item or not cint(frappe.db.get_value("Item", template, "has_variants")):
		frappe.throw(_("Ce modèle n'est pas disponible sur cette boutique."), frappe.DoesNotExistError)

	attributes = frappe.get_all(
		"Item Variant Attribute", filters={"parent": template}, fields=["attribute"], order_by="idx asc", pluck="attribute"
	)
	attrs_by_variant = {}
	for item_code, attribute, value in ItemVariantsCacheManager(template).get_item_variants_data() or []:
		attrs_by_variant.setdefault(item_code, {})[attribute] = value
	codes = list(attrs_by_variant)

	settings = cart_settings()
	price_list = effective_price_list()
	currency = (
		frappe.db.get_value("Price List", price_list, "currency") if price_list else None
	) or frappe.defaults.get_global_default("currency")

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
	prices = _prices(codes, price_list)
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
		price = prices.get(code)
		out["variants"].append(
			{
				"item_code": code,
				"item_name": item.item_name,
				"attrs": attrs_by_variant[code],
				"price": price,
				"formatted_price": fmt_money(price, currency=currency) if price is not None else None,
				"stock": stock.get(code),
				"uom": item.stock_uom,
			}
		)
	return out


# ---------------------------------------------------------------------------
# the batch into the cart
# ---------------------------------------------------------------------------


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


@frappe.whitelist(methods=["POST"])
def add_lines(lines):
	"""The whole entry into the cart at once: one read, one save.

	Every line goes through the rule of "add to cart". What the shop cannot
	serve is capped to what it can, and named; what it cannot sell at all is
	refused, and named. The valid lines are never held back by a refused one.
	"""
	from webshop.webshop.multi_warehouse import sources as mw_sources

	party = require_reseller()
	require_login_to_buy()
	wanted = _parse_lines(lines)
	settings = cart_settings()
	multi_enabled = mw_sources.is_enabled(settings)
	quotation = _get_cart_quotation(party)
	if not quotation:
		frappe.throw(_("Impossible d'ouvrir un panier pour ce compte."))

	def existing_row(item_code, warehouse):
		for row in quotation.get("items") or []:
			if row.item_code != item_code:
				continue
			if not multi_enabled or (row.warehouse or None) == (warehouse or None):
				return row
		return None

	added, refused, capped = [], [], []
	for (item_code, warehouse), qty in wanted.items():
		if not resolve(item_code):
			refused.append({"item_code": item_code, "qty": qty, "reason": _("Cet article n'est pas disponible sur cette boutique.")})
			continue
		if is_gift_card_item(item_code):
			refused.append({"item_code": item_code, "qty": qty, "reason": _("Les cartes cadeaux ne passent pas par la commande rapide.")})
			continue

		if multi_enabled:
			allowed = mw_sources.get_allowed_warehouses(item_code, settings)
			if warehouse and allowed and warehouse not in allowed:
				refused.append({"item_code": item_code, "qty": qty, "reason": _("Source de stock invalide pour {0}").format(item_code)})
				continue
			if not warehouse:
				row = existing_row(item_code, None) or next((r for r in quotation.get("items") or [] if r.item_code == item_code), None)
				warehouse = (row.warehouse if row else None) or mw_sources.resolve_target_warehouse(item_code, qty, settings)
		else:
			warehouse = frappe.get_cached_value("Website Item", {"item_code": item_code}, "website_warehouse")

		row = existing_row(item_code, warehouse)
		existing_qty = flt(row.qty) if row else 0
		limit = available_cart_qty(item_code, warehouse, settings, multi_enabled)
		if limit.available is not None:
			room = flt(limit.available) - existing_qty
			if room <= 0:
				refused.append({"item_code": item_code, "qty": qty, "reason": _("Épuisé : {0} déjà au panier, rien de plus disponible.").format(int(existing_qty))})
				continue
			if qty > room:
				capped.append({"item_code": item_code, "asked": qty, "kept": int(room), "available": int(limit.available)})
				qty = int(room)

		if row:
			row.qty = flt(row.qty) + qty
			row.warehouse = warehouse
		else:
			quotation.append("items", {"doctype": "Quotation Item", "item_code": item_code, "qty": qty, "warehouse": warehouse})
		added.append({"item_code": item_code, "qty": qty})

	if added:
		quotation.flags.ignore_permissions = True
		quotation.flags.ignore_mandatory = True
		apply_cart_settings(party, quotation)
		quotation.payment_schedule = []
		quotation.save(ignore_version=True)
		set_cart_count(quotation)

	total_qty = sum(flt(row.qty) for row in quotation.get("items") or [])
	return {
		"added": added,
		"capped": capped,
		"refused": refused,
		"cart": {
			"qty": total_qty,
			"total": flt(quotation.grand_total),
			"formatted_total": fmt_money(flt(quotation.grand_total), currency=quotation.currency),
			"url": "/cart",
		},
	}


# ---------------------------------------------------------------------------
# the page
# ---------------------------------------------------------------------------


def labels():
	return {
		"title": _("Commande rapide"),
		"lead": _("Tapez une référence, un nom ou un code-barres : la grille du modèle s'ouvre et vous saisissez les quantités au clavier."),
		"placeholder": _("Référence, nom ou code-barres…"),
		"no_results": _("Aucun article publié ne correspond."),
		"unknown_code": _("Code inconnu sur cette boutique : {0}"),
		"searching": _("Recherche…"),
		"variants": _("{0} variantes"),
		"empty": _("Aucun modèle ouvert. Cherchez une référence pour commencer."),
		"close": _("Fermer"),
		"reset_model": _("Tout à zéro"),
		"stock": _("Stock"),
		"available": _("{0} disponibles"),
		"out_of_stock": _("Épuisé"),
		"unlimited": _("Sur commande"),
		"price_on_request": _("Prix sur demande"),
		"none": _("Pas de variante"),
		"over_stock": _("Au-delà du stock disponible"),
		"pieces": _("pièces"),
		"lines": _("lignes"),
		"total": _("Total indicatif"),
		"total_note": _("Prix du tarif. Remises et TVA sont calculées au panier."),
		"send": _("Envoyer au panier"),
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
		"shortcuts": _("Entrée : case suivante · Échap : retour à la recherche · Ctrl+Entrée : envoyer"),
		"qty": _("Qté"),
		"add": _("Ajouter"),
	}


def page_context(context):
	"""What /quick-order renders: the refusal, or the app and its configuration."""
	context.allowed = False
	context.reason = ""
	party = get_party()
	if not party:
		context.reason = _("Aucun compte client n'est rattaché à votre utilisateur.")
		return context
	if not is_reseller(party):
		context.reason = _("Cette page est réservée aux comptes professionnels.")
		return context
	price_list = effective_price_list()
	currency = (
		frappe.db.get_value("Price List", price_list, "currency") if price_list else None
	) or frappe.defaults.get_global_default("currency")
	context.allowed = True
	context.config = {
		"user": frappe.session.user,
		"customer": party.get("customer_name") or party.get("name"),
		"site": getattr(frappe.local, "website_profile", None) or frappe.local.site,
		"currency": currency,
		"lang": frappe.local.lang or "fr",
		"max_lines": MAX_LINES,
		"cart_url": "/cart",
		"labels": labels(),
	}
	return context
