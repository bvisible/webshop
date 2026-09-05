# //// Neoffice — added file (shop assistant, no upstream equivalent).
"""The assistant's toolbox — and the whole of it.

Every tool is a plain function that receives the arguments the model chose
and a context built from the request: the session user, the customer that
user resolves to (or None), the settings. Nothing the browser sends picks the
identity. Results are small dicts with an explicit list of fields: what a tool
does not name, the model never sees — there is no path from here to a
purchase price, a valuation or somebody else's document.

Descriptions and returned texts are French: the model reads them.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, escape_html, flt, fmt_money, get_url, now_datetime, strip_html

from webshop.webshop.utils import store_hours

PRODUCT_LIMIT = 8
DOCUMENT_LIMIT = 10
DESCRIPTION_CHARS = 600


class ToolRefused(Exception):
	"""Raised by a tool that cannot serve this visitor; the message is for the model."""


# ---------------------------------------------------------------------------
# context and helpers
# ---------------------------------------------------------------------------


def _require_customer(ctx):
	if not ctx.customer:
		raise ToolRefused(
			_("Le visiteur n'est pas connecté : propose-lui de se connecter à son compte pour voir ses documents.")
		)
	return ctx.customer


def _money(amount, currency):
	return fmt_money(flt(amount), currency=currency)


def _excluded_website_items():
	from webshop.webshop.multi_site import excluded_item_names

	try:
		return set(excluded_item_names() or [])
	except Exception:
		return set()


def _product_card(item, ctx, with_details=False):
	"""What the shop shows about a published item: nothing more."""
	from webshop.webshop.shopping_cart.product_info import get_product_info_for_website

	info = {}
	try:
		info = get_product_info_for_website(item.item_code, skip_quotation_creation=True).get("product_info") or {}
	except Exception:
		frappe.log_error("Shop assistant: product info failed", frappe.get_traceback())
	price = info.get("price") or {}
	card = {
		"item_code": item.item_code,
		"name": item.web_item_name,
		"url": "/" + item.route if item.route else None,
		# //// Neoffice — get_product_info_for_website prices with warehouse=, a keyword only
		# our ERPNext fork knows; on stock ERPNext it raises and this said "prix sur demande"
		# for everything. Fall back to the shop's list price (45778bc99 "fix(assistant): un
		# prix de liste en repli quand la fiche prix ne répond pas").
		"price": price.get("formatted_price")
		or price.get("formatted_price_sales_uom")
		or _list_price(item.item_code)
		or _("prix sur demande"),
		"in_stock": bool(info.get("in_stock")),
		"condition": _(item.item_condition) if item.item_condition and item.item_condition != "New" else None,
	}
	if info.get("show_stock_qty") and info.get("stock_qty") is not None:
		card["stock_qty"] = cint(info.get("stock_qty"))
	if info.get("on_backorder"):
		card["backorder"] = True
	sources = info.get("warehouse_sources") or []
	if sources:
		card["sources"] = [
			{
				"label": s.get("label"),
				"in_stock": bool(s.get("in_stock")),
				"stock_qty": cint(s.get("stock_qty")) if info.get("show_stock_qty") else None,
				"supplier": bool(s.get("is_supplier_source")),
				"delivery_days": s.get("lead_days") or None,
			}
			for s in sources
		]
	if with_details:
		card["brand"] = item.brand
		card["item_group"] = item.item_group
		text = strip_html(item.short_description or item.description or "")
		card["description"] = (text[:DESCRIPTION_CHARS] + "…") if len(text) > DESCRIPTION_CHARS else text
		card["used_units"] = _used_units(item.item_code)
	return card


# //// Neoffice — new helper (45778bc99 "fix(assistant): un prix de liste en repli quand la
# fiche prix ne répond pas"): reads a plain selling Item Price on the shop's price list,
# used only as a fallback when get_price (fork-only warehouse= kwarg) fails on standard ERPNext.
def _list_price(item_code):
	"""The shop's list price, when the full pricing path could not answer.

	`get_product_info_for_website` prices through pricing rules and the site's
	list; on an ERPNext without our fork it raises on a keyword it does not
	know. A plain Item Price is still a selling price the shop published —
	never a buying list (`selling = 1`)."""
	settings = frappe.get_cached_doc("Webshop Settings")
	price_list = settings.get("price_list") or frappe.db.get_value("Price List", {"selling": 1, "enabled": 1}, "name")
	if not price_list:
		return None
	row = frappe.db.get_value(
		"Item Price",
		{"item_code": item_code, "price_list": price_list, "selling": 1},
		["price_list_rate", "currency"],
		as_dict=True,
	)
	if not row:
		return None
	return fmt_money(flt(row.price_list_rate), currency=row.currency or frappe.db.get_value("Price List", price_list, "currency"))


def _used_units(item_code):
	from webshop.webshop.utils.used_items import get_used_units

	try:
		units = get_used_units(item_code, limit=3)
	except Exception:
		return []
	return [
		{
			"item_code": u.get("item_code"),
			"condition": _(u.get("item_condition")) if u.get("item_condition") else None,
			"grade": _(u.get("condition_grade")) if u.get("condition_grade") else None,
			"price": u.get("formatted_price"),
			"url": "/" + u.get("route") if u.get("route") else None,
		}
		for u in units
	]


WEBSITE_ITEM_FIELDS = [
	"name",
	"item_code",
	"web_item_name",
	"route",
	"item_group",
	"brand",
	"short_description",
	"description",
	"item_condition",
	"ranking",
]


def _published_items(filters=None, or_filters=None, limit=PRODUCT_LIMIT * 3):
	filters = dict(filters or {})
	filters["published"] = 1
	rows = frappe.get_all(
		"Website Item",
		filters=filters,
		or_filters=or_filters,
		fields=WEBSITE_ITEM_FIELDS,
		order_by="ranking desc, modified desc",
		limit=limit,
	)
	excluded = _excluded_website_items()
	return [r for r in rows if r.name not in excluded]


# ---------------------------------------------------------------------------
# tools everybody may use
# ---------------------------------------------------------------------------


def search_products(args, ctx):
	query = (args.get("query") or "").strip()
	limit = min(cint(args.get("limit")) or 5, PRODUCT_LIMIT)
	if len(query) < 2:
		return {"products": [], "note": _("Il faut au moins deux caractères pour chercher.")}
	like = f"%{query}%"
	or_filters = [[f, "like", like] for f in ("web_item_name", "item_code", "short_description", "description", "item_group", "brand")]
	rows = _published_items(or_filters=or_filters)
	if not rows:
		words = [w for w in query.split() if len(w) >= 3]
		seen = {}
		for word in words:
			for r in _published_items(or_filters=[[f, "like", f"%{word}%"] for f in ("web_item_name", "short_description", "description", "brand")]):
				seen.setdefault(r.name, [r, 0])
				seen[r.name][1] += 1
		rows = [r for r, _count in sorted(seen.values(), key=lambda x: -x[1])]
	products = [_product_card(r, ctx) for r in rows[:limit]]
	return {"count": len(products), "products": products}


def get_product(args, ctx):
	ref = (args.get("item_code") or "").strip()
	if not ref:
		return {"error": _("Précise le code ou le nom de l'article.")}
	rows = _published_items(filters={"item_code": ref}, limit=1)
	if not rows:
		rows = _published_items(filters={"route": ref.strip("/")}, limit=1)
	if not rows:
		rows = _published_items(or_filters=[["web_item_name", "like", f"%{ref}%"]], limit=1)
	if not rows:
		return {"error": _("Aucun article publié ne correspond à « {0} ».").format(ref)}
	return {"product": _product_card(rows[0], ctx, with_details=True)}


def get_store_hours(args, ctx):
	data = store_hours.opening_hours(settings=ctx.settings)
	if not data.configured:
		return {"configured": False, "note": _("Le magasin n'a pas publié ses horaires.")}
	return {
		"configured": True,
		"now": data.today_text,
		"is_open": bool(data.is_open),
		"status": data.headline,
		"next": data.detail,
		"week": [f"{d.label} : {d.text}" for d in data.week],
		"closures": [c.text for c in data.closures],
		"note": data.note,
		"url": "/store-hours",
	}


def get_store_info(args, ctx):
	settings = ctx.settings
	shop_name = frappe.db.get_single_value("Website Settings", "app_name") or ""
	return {
		"shop_name": shop_name,
		"address": (settings.get("store_address") or "").strip() or None,
		"phone": (settings.get("store_phone") or "").strip() or None,
		"email": (settings.get("store_email") or "").strip() or None,
		"knowledge": (settings.get("assistant_knowledge") or "").strip() or None,
		"pages": {"catalogue": "/all-products", "hours": "/store-hours", "second_hand": "/occasions"},
	}


# ---------------------------------------------------------------------------
# tools for the signed-in customer
# ---------------------------------------------------------------------------


def _order_summary(so, currency):
	return {
		"number": so.name,
		"date": str(so.transaction_date),
		"status": _(so.status),
		"delivery": _(so.delivery_status) if so.get("delivery_status") else None,
		"delivered_percent": flt(so.per_delivered),
		"billed_percent": flt(so.per_billed),
		"total": _money(so.grand_total, currency),
		"url": f"/orders/{so.name}",
	}


def get_my_orders(args, ctx):
	customer = _require_customer(ctx)
	limit = min(cint(args.get("limit")) or 5, DOCUMENT_LIMIT)
	rows = frappe.get_all(
		"Sales Order",
		filters={"customer": customer, "docstatus": 1},
		fields=["name", "transaction_date", "status", "delivery_status", "per_delivered", "per_billed", "grand_total", "currency"],
		order_by="transaction_date desc, creation desc",
		limit=limit,
	)
	return {"count": len(rows), "orders": [_order_summary(r, r.currency) for r in rows]}


def get_order(args, ctx):
	customer = _require_customer(ctx)
	name = (args.get("number") or "").strip()
	so = frappe.db.get_value(
		"Sales Order",
		{"name": name, "customer": customer, "docstatus": 1},
		["name", "transaction_date", "status", "delivery_status", "per_delivered", "per_billed", "grand_total", "currency", "delivery_date"],
		as_dict=True,
	)
	if not so:
		return {"error": _("Aucune commande « {0} » pour ce client.").format(name)}
	items = frappe.get_all(
		"Sales Order Item",
		filters={"parent": so.name},
		fields=["item_name", "qty", "delivered_qty", "rate", "amount"],
		order_by="idx",
	)
	out = _order_summary(so, so.currency)
	out["expected_delivery"] = str(so.delivery_date) if so.delivery_date else None
	out["lines"] = [
		{"item": i.item_name, "qty": flt(i.qty), "delivered": flt(i.delivered_qty), "amount": _money(i.amount, so.currency)}
		for i in items
	]
	deliveries = frappe.get_all(
		"Delivery Note Item",
		filters={"against_sales_order": so.name, "docstatus": 1},
		fields=["parent"],
		distinct=True,
	)
	out["delivery_notes"] = [d.parent for d in deliveries]
	return out


def get_my_invoices(args, ctx):
	customer = _require_customer(ctx)
	limit = min(cint(args.get("limit")) or 5, DOCUMENT_LIMIT)
	rows = frappe.get_all(
		"Sales Invoice",
		filters={"customer": customer, "docstatus": 1},
		fields=["name", "posting_date", "due_date", "status", "grand_total", "outstanding_amount", "currency"],
		order_by="posting_date desc, creation desc",
		limit=limit,
	)
	return {
		"count": len(rows),
		"invoices": [
			{
				"number": r.name,
				"date": str(r.posting_date),
				"due_date": str(r.due_date) if r.due_date else None,
				"status": _(r.status),
				"total": _money(r.grand_total, r.currency),
				"outstanding": _money(r.outstanding_amount, r.currency),
				"url": f"/invoices/{r.name}",
			}
			for r in rows
		],
	}


def get_invoice(args, ctx):
	customer = _require_customer(ctx)
	name = (args.get("number") or "").strip()
	inv = frappe.db.get_value(
		"Sales Invoice",
		{"name": name, "customer": customer, "docstatus": 1},
		["name", "posting_date", "due_date", "status", "grand_total", "outstanding_amount", "currency"],
		as_dict=True,
	)
	if not inv:
		return {"error": _("Aucune facture « {0} » pour ce client.").format(name)}
	items = frappe.get_all(
		"Sales Invoice Item", filters={"parent": inv.name}, fields=["item_name", "qty", "amount"], order_by="idx"
	)
	return {
		"number": inv.name,
		"date": str(inv.posting_date),
		"due_date": str(inv.due_date) if inv.due_date else None,
		"status": _(inv.status),
		"total": _money(inv.grand_total, inv.currency),
		"outstanding": _money(inv.outstanding_amount, inv.currency),
		"lines": [{"item": i.item_name, "qty": flt(i.qty), "amount": _money(i.amount, inv.currency)} for i in items],
		"url": f"/invoices/{inv.name}",
	}


def get_my_quotations(args, ctx):
	customer = _require_customer(ctx)
	limit = min(cint(args.get("limit")) or 5, DOCUMENT_LIMIT)
	rows = frappe.get_all(
		"Quotation",
		filters={"party_name": customer, "quotation_to": "Customer", "docstatus": 1, "order_type": ["!=", "Shopping Cart"]},
		fields=["name", "transaction_date", "valid_till", "status", "grand_total", "currency"],
		order_by="transaction_date desc",
		limit=limit,
	)
	return {
		"count": len(rows),
		"quotations": [
			{
				"number": r.name,
				"date": str(r.transaction_date),
				"valid_till": str(r.valid_till) if r.valid_till else None,
				"status": _(r.status),
				"total": _money(r.grand_total, r.currency),
				"url": f"/quotations/{r.name}",
			}
			for r in rows
		],
	}


def get_my_cart(args, ctx):
	filters = {"docstatus": 0, "order_type": "Shopping Cart"}
	if ctx.customer:
		filters.update({"party_name": ctx.customer, "quotation_to": "Customer"})
	elif ctx.guest_session:
		filters["guest_session"] = ctx.guest_session
	else:
		return {"lines": [], "note": _("Le panier est vide.")}
	name = frappe.db.get_value("Quotation", filters, "name", order_by="modified desc")
	if not name:
		return {"lines": [], "note": _("Le panier est vide.")}
	quotation = frappe.get_doc("Quotation", name)
	return {
		"lines": [
			{"item": i.item_name, "qty": flt(i.qty), "amount": _money(i.amount, quotation.currency)}
			for i in quotation.items
		],
		"total": _money(quotation.grand_total, quotation.currency),
		"coupon": quotation.coupon_code or None,
		"url": "/cart",
	}


# ---------------------------------------------------------------------------
# handing over to people
# ---------------------------------------------------------------------------


def _visitor_email(args, ctx):
	if ctx.user and ctx.user != "Guest":
		return ctx.user
	email = (args.get("email") or "").strip()
	from frappe.utils import validate_email_address

	return email if email and validate_email_address(email) else None


def contact_team(args, ctx):
	from webshop.webshop.assistant.escalation import contact_team as _contact

	email = _visitor_email(args, ctx)
	if not email:
		return {"needs_email": True, "note": _("Demande au visiteur son adresse email pour que l'équipe puisse le recontacter.")}
	return _contact(ctx, summary=(args.get("summary") or "").strip(), email=email)


def create_support_ticket(args, ctx):
	from webshop.webshop.assistant.escalation import create_support_ticket as _ticket

	email = _visitor_email(args, ctx)
	if not email:
		return {"needs_email": True, "note": _("Demande au visiteur son adresse email avant d'ouvrir le ticket.")}
	return _ticket(
		ctx,
		subject=(args.get("subject") or "").strip(),
		description=(args.get("description") or "").strip(),
		email=email,
	)


# ---------------------------------------------------------------------------
# the registry: name, French description for the model, JSON schema, handler
# ---------------------------------------------------------------------------


def _schema(properties=None, required=None):
	return {"type": "object", "properties": properties or {}, "required": required or []}


TOOLS = [
	frappe._dict(
		name="search_products",
		description="Cherche des produits publiés de la boutique par mot-clé (nom, description, marque, catégorie). Rend le prix de vente, la disponibilité et le lien de chaque produit.",
		parameters=_schema({"query": {"type": "string", "description": "Ce que cherche le client"}, "limit": {"type": "integer", "description": "Nombre maximum de résultats, 8 au plus"}}, ["query"]),
		handler=search_products,
	),
	frappe._dict(
		name="get_product",
		description="Détaille un produit publié : description, prix de vente, stock en magasin et chez le fournisseur quand la boutique le publie, délais, occasions disponibles. Accepte le code article, le nom ou le lien.",
		parameters=_schema({"item_code": {"type": "string", "description": "Code article, nom ou lien du produit"}}, ["item_code"]),
		handler=get_product,
	),
	frappe._dict(
		name="get_store_hours",
		description="Les horaires d'ouverture du magasin : ouvert ou fermé en ce moment, prochaine ouverture ou fermeture, la semaine, les fermetures exceptionnelles.",
		parameters=_schema(),
		handler=get_store_hours,
	),
	frappe._dict(
		name="get_store_info",
		description="Adresse, téléphone, email du magasin, et ce que la boutique tient à faire savoir (livraison, retours, paiement, garantie).",
		parameters=_schema(),
		handler=get_store_info,
	),
	frappe._dict(
		name="get_my_orders",
		description="Les dernières commandes du client connecté, avec leur statut de livraison. Refusé si le visiteur n'est pas connecté.",
		parameters=_schema({"limit": {"type": "integer", "description": "Nombre de commandes, 10 au plus"}}),
		handler=get_my_orders,
	),
	frappe._dict(
		name="get_order",
		description="Le détail d'une commande du client connecté : lignes, livraison, facturation. Refusé si la commande n'est pas la sienne.",
		parameters=_schema({"number": {"type": "string", "description": "Numéro de la commande, par exemple BC-2026-00402"}}, ["number"]),
		handler=get_order,
	),
	frappe._dict(
		name="get_my_invoices",
		description="Les dernières factures du client connecté, avec le montant restant dû et l'échéance.",
		parameters=_schema({"limit": {"type": "integer", "description": "Nombre de factures, 10 au plus"}}),
		handler=get_my_invoices,
	),
	frappe._dict(
		name="get_invoice",
		description="Le détail d'une facture du client connecté.",
		parameters=_schema({"number": {"type": "string", "description": "Numéro de la facture"}}, ["number"]),
		handler=get_invoice,
	),
	frappe._dict(
		name="get_my_quotations",
		description="Les devis établis pour le client connecté (pas ses paniers).",
		parameters=_schema({"limit": {"type": "integer", "description": "Nombre de devis, 10 au plus"}}),
		handler=get_my_quotations,
	),
	frappe._dict(
		name="get_my_cart",
		description="Le panier en cours du visiteur : lignes, total, code promo appliqué.",
		parameters=_schema(),
		handler=get_my_cart,
	),
	frappe._dict(
		name="contact_team",
		description="Transmet la demande à l'équipe de la boutique quand tu ne peux pas répondre, quand le client le demande, ou quand il est mécontent. Donne un résumé clair. Si le visiteur n'est pas connecté, il faut son email (demande-le d'abord).",
		parameters=_schema({"summary": {"type": "string", "description": "Ce que veut le client, en deux ou trois phrases"}, "email": {"type": "string", "description": "Email du visiteur s'il n'est pas connecté"}}, ["summary"]),
		handler=contact_team,
	),
	frappe._dict(
		name="create_support_ticket",
		description="Ouvre un ticket de support au nom du client pour un problème à suivre (livraison manquante, produit défectueux, facture à corriger). Si le visiteur n'est pas connecté, il faut son email.",
		parameters=_schema({"subject": {"type": "string", "description": "Titre court du problème"}, "description": {"type": "string", "description": "Le problème, avec les numéros de commande ou de facture"}, "email": {"type": "string", "description": "Email du visiteur s'il n'est pas connecté"}}, ["subject", "description"]),
		handler=create_support_ticket,
	),
]

BY_NAME = {t.name: t for t in TOOLS}


def schemas():
	"""What the model is told it may call: exactly these, in the OpenAI shape."""
	return [
		{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
		for t in TOOLS
	]


def run(name, args, ctx):
	"""Execute one call the model asked for. Never raises: the model gets an error text."""
	tool = BY_NAME.get(name)
	if not tool:
		return {"error": _("Outil inconnu : {0}.").format(escape_html(str(name)))}
	try:
		return tool.handler(args or {}, ctx)
	except ToolRefused as refused:
		return {"error": str(refused)}
	except Exception:
		frappe.log_error(f"Shop assistant tool failed: {name}", frappe.get_traceback())
		return {"error": _("L'outil n'a pas pu répondre. Propose au client de contacter l'équipe.")}


def to_json(result):
	return json.dumps(result, ensure_ascii=False, default=str)
