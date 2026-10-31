# //// Neoffice — added file (no upstream equivalent).
"""The partner API, version 1: what a reseller's key reads and does.

Five calls, and nothing else (the study, § 4): the products the shop publishes, one product, the key owner's
orders, one order, and a new order. The shop sees what the shop shows a visitor (`selection.scope()`), the price
is the one on THIS customer's price list with the shop's rules (`customer_pricing`, the cart's own answer),
and what a program may send is as small as it can be.

- **The price never comes from the caller.** A line is `{item_code, qty}`; a line that carries anything else
  (a `rate`, a `price`) is refused, not ignored, so a program written against a guess finds out at once. The
  order is priced by ERPNext on the customer's list, then checked against `customer_pricing`.
- **An order waits as a draft** unless staff allowed submission for this key.
- **A call can be replayed**: `idempotency_key` names the order, and the same key with the same lines returns the
  order that was made; the same key with other lines is a 422.
- **The stock is told as "in_stock", "out_of_stock" or "backorder"**, never as a quantity (decision 2).
- Every figure and word is English and stable: the contract is `openapi.yaml`, beside this file.
"""

import hashlib
import json
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import add_days, cint, flt, getdate, nowdate

from webshop.webshop.catalogue import book, rows, selection
from webshop.webshop.partner_api.access import ApiError
from webshop.webshop.seo import availability as stock
from webshop.webshop.shopping_cart.shop_rights import shop_rights
from webshop.webshop.utils import customer_pricing

PAGE_SIZE, PAGE_MAX = 50, 100
MAX_LINES = 100
MAX_QTY = 100000
MAX_TEXT = 140
KEY_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,100}$")
# rows.build_rows reads the brand's figures even when no selling price is asked for: there is no brand here
PAYLOAD = {"values": {"price_display": "Excluding VAT", "price_rounding": "none", "vat_rate": 0, "default_markup_percent": 0}}
NO_PRICE = {"markup_percent": 0.0, "prices": "none"}
THEIR_PRICE = {"markup_percent": 0.0, "prices": "tariff"}


def invalid(parameter, message):
	return ApiError(422, "invalid_parameter", f"{parameter}: {message}")


# ---------------------------------------------------------------------------------------------
# What a call says about time and pages


def _zone():
	return ZoneInfo(frappe.utils.get_system_timezone())


def utc(value):
	"""A datetime of the site's clock as ISO 8601 in UTC with its offset: the reader's clock is not the site's."""
	if not value:
		return None
	moment = frappe.utils.get_datetime(value)
	return moment.replace(tzinfo=_zone()).astimezone(timezone.utc).isoformat(timespec="seconds")


def since(text):
	"""`modified_since` as the site's own naive clock, from ISO 8601 (a date alone is midnight UTC)."""
	try:
		moment = datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
	except ValueError:
		raise invalid("modified_since", "write it as ISO 8601, like 2026-10-31T00:00:00Z") from None
	if moment.tzinfo is None:
		moment = moment.replace(tzinfo=timezone.utc)
	return moment.astimezone(_zone()).replace(tzinfo=None)


def paging(args):
	def number(name, default):
		value = args.get(name)
		return default if value in (None, "") else int(value)

	try:
		page, size = number("page", 1), number("page_size", PAGE_SIZE)
	except ValueError:
		raise invalid("page", "page and page_size are whole numbers") from None
	if page < 1 or not 1 <= size <= PAGE_MAX:
		raise invalid("page_size", f"between 1 and {PAGE_MAX}; page from 1")
	return page, size


def text(args, name):
	"""A text parameter, bounded, or None."""
	value = args.get(name)
	if value in (None, ""):
		return None
	value = str(value).strip()
	if len(value) > MAX_TEXT:
		raise invalid(name, f"{MAX_TEXT} characters at most")
	return value


# ---------------------------------------------------------------------------------------------
# Products


def _product(row, modified, detail=False):
	product = {
		"code": row["code"],
		"model": row["model"] or None,
		"name": row["name"],
		"brand": row["brand"] or None,
		"category": row["category"] or None,
		"unit": row["unit"] or None,
		"ean": row["ean"] or None,
		"mpn": row["mpn"] or None,
		"attributes": row["attributes"],
		"availability": row["availability"],
		"image": row["image"] or None,
		"url": row["url"] or None,
		"modified": utc(modified),
	}
	if detail:
		product["description"] = row["description"] or None
		product["images"] = [url for url in [row["image"], *row["more_images"]] if url]
	return product


def _orderable_filters():
	"""Website Item filters of what a key may read and order: what the shop shows, a model's variants included
	(the shop hides them from its listings, not from its buyers), never a model itself."""
	filters = selection.scope()
	filters.pop("variant_of", None)
	filters["has_variants"] = 0
	return filters


def list_products(access, args):
	page, size = paging(args)
	filters = _orderable_filters()
	for argument, field in (("brand", "brand"), ("model", "variant_of"), ("code", "item_code")):
		value = text(args, argument)
		if value:
			filters[field] = value
	group = text(args, "item_group")
	if group:
		filters["item_group"] = ["in", selection.group_names([group]) or [""]]
	if args.get("modified_since"):
		filters["modified"] = [">", since(args["modified_since"])]
	needle = text(args, "search")
	either = (
		[["web_item_name", "like", f"%{needle}%"], ["item_code", "like", f"%{needle}%"], ["brand", "like", f"%{needle}%"]]
		if needle
		else None
	)
	total = frappe.get_all("Website Item", filters=filters, or_filters=either, fields=["count(name) as total"])[0].total
	found = frappe.get_all(
		"Website Item",
		filters=filters,
		or_filters=either,
		fields=["item_code", "modified"],
		order_by="modified asc, name asc",
		limit_start=(page - 1) * size,
		limit_page_length=size,
	)
	products = []
	if found:
		data = rows.build_rows(
			access.customer,
			PAYLOAD,
			selection.clean_selection({"items": [row.item_code for row in found]}),
			NO_PRICE,
			include_variants=True,
		)
		by_code = {row["code"]: row for row in data.rows}
		products = [_product(by_code[row.item_code], row.modified) for row in found if row.item_code in by_code]
	return {"page": page, "page_size": size, "total": total, "products": products}


def get_product(access, code):
	code = str(code or "").strip()[:MAX_TEXT]
	found = frappe.get_all(
		"Website Item", filters={**_orderable_filters(), "item_code": code}, fields=["item_code", "modified"], limit=1
	)
	if not found:
		raise ApiError(404, "not_found", "No such product: it is not published, it is a model (order its variants) or the code is wrong.")
	data = rows.build_rows(
		access.customer, PAYLOAD, selection.clean_selection({"items": [code]}), THEIR_PRICE, include_variants=True
	)
	row = next((row for row in data.rows if row["code"] == code), None)
	if not row:
		raise ApiError(404, "not_found", "No such product.")
	product = _product(row, found[0].modified, detail=True)
	product["price"] = row.get("purchase_price")
	product["currency"] = row.get("currency")
	return product


# ---------------------------------------------------------------------------------------------
# Orders


def _order_fields():
	fields = ["name", "po_no", "status", "docstatus", "transaction_date", "delivery_date", "currency", "net_total", "grand_total", "modified"]
	if frappe.get_meta("Sales Order").has_field("neo_confirmed_delivery_date"):
		fields.append("neo_confirmed_delivery_date")
	return fields


def _order(row):
	return {
		"id": row.name,
		"reference": row.po_no or None,
		"status": row.status,
		"submitted": row.docstatus == 1,
		"date": str(row.transaction_date),
		"requested_delivery_date": str(row.delivery_date) if row.delivery_date else None,
		"confirmed_delivery_date": str(row.get("neo_confirmed_delivery_date") or "") or None,
		"currency": row.currency,
		"net_total": flt(row.net_total),
		"grand_total": flt(row.grand_total),
		"modified": utc(row.modified),
	}


def get_order(access, order_id):
	row = frappe.db.get_value(
		"Sales Order", {"name": str(order_id or "")[:MAX_TEXT], "customer": access.customer}, _order_fields(), as_dict=True
	)
	if not row:
		raise ApiError(404, "not_found", "No such order.")
	order = _order(row)
	order["lines"] = [
		{"item_code": line.item_code, "name": line.item_name, "qty": flt(line.qty), "unit": line.uom, "price": flt(line.rate), "amount": flt(line.amount)}
		for line in frappe.get_all(
			"Sales Order Item",
			filters={"parent": row.name},
			fields=["item_code", "item_name", "qty", "uom", "rate", "amount"],
			order_by="idx asc",
		)
	]
	return order


def list_orders(access, args):
	page, size = paging(args)
	filters = {"customer": access.customer}
	status = text(args, "status")
	if status:
		filters["status"] = status
	reference = text(args, "reference")
	if reference:
		filters["po_no"] = reference
	if args.get("modified_since"):
		filters["modified"] = [">", since(args["modified_since"])]
	total = frappe.db.count("Sales Order", filters)
	found = frappe.get_all(
		"Sales Order",
		filters=filters,
		fields=_order_fields(),
		order_by="modified asc, name asc",
		limit_start=(page - 1) * size,
		limit_page_length=size,
	)
	return {"page": page, "page_size": size, "total": total, "orders": [_order(row) for row in found]}


def _clean_order(body):
	"""The order a program asked for, as {reference, key, lines, delivery, dry_run}, or a 422."""
	if not isinstance(body, dict):
		raise ApiError(422, "invalid_body", "The body is a JSON object.")
	unknown = set(body) - {"reference", "idempotency_key", "lines", "requested_delivery_date", "dry_run"}
	if unknown:
		raise ApiError(422, "invalid_body", f"Not accepted here: {', '.join(sorted(unknown))}. The price is the server's.")
	key = str(body.get("idempotency_key") or "")
	if not KEY_PATTERN.match(key):
		raise ApiError(422, "invalid_idempotency_key", "idempotency_key is required: 1 to 100 letters, digits and _ . : -")
	reference = str(body.get("reference") or "").strip()
	if len(reference) > MAX_TEXT or any(char in reference for char in "<>"):
		raise invalid("reference", f"{MAX_TEXT} characters at most, without < or >")
	lines = body.get("lines")
	if not isinstance(lines, list) or not 1 <= len(lines) <= MAX_LINES:
		raise invalid("lines", f"a list of 1 to {MAX_LINES} lines")
	clean, seen = [], set()
	for index, line in enumerate(lines):
		if not isinstance(line, dict) or set(line) != {"item_code", "qty"}:
			raise invalid(f"lines[{index}]", "a line is {item_code, qty} and nothing else: the price is the server's")
		code, qty = line["item_code"], line["qty"]
		if not isinstance(code, str) or not code.strip() or len(code) > MAX_TEXT:
			raise invalid(f"lines[{index}].item_code", "a product code")
		if isinstance(qty, bool) or not isinstance(qty, (int, float)) or not 0 < qty <= MAX_QTY:
			raise invalid(f"lines[{index}].qty", f"a number above 0 and up to {MAX_QTY}")
		code = code.strip()
		if code in seen:
			raise invalid(f"lines[{index}].item_code", f"{code} is on two lines: one line a product")
		seen.add(code)
		clean.append({"item_code": code, "qty": qty})
	delivery = None
	if body.get("requested_delivery_date"):
		try:
			delivery = getdate(body["requested_delivery_date"])
		except Exception:
			raise invalid("requested_delivery_date", "a date like 2026-11-15") from None
		if delivery < getdate(nowdate()) or delivery > getdate(add_days(nowdate(), 366)):
			raise invalid("requested_delivery_date", "from today to a year from today")
	return {"reference": reference, "key": key, "lines": clean, "delivery": delivery, "dry_run": body.get("dry_run") is True}


def _check_lines(customer, lines):
	"""Every line against what the shop sells this customer: published, priced on their list, in stock.
	A list of the lines that cannot be served, empty when all can. No quantity of stock is ever told."""
	settings = frappe.get_cached_doc("Webshop Settings")
	party = frappe.get_doc("Customer", customer)
	price_list = customer_pricing.customer_price_list(settings, party)
	codes = [line["item_code"] for line in lines]
	visible = {
		row.item_code
		for row in frappe.get_all("Website Item", filters={**_orderable_filters(), "item_code": ["in", codes]}, fields=["item_code"])
	}
	prices = customer_pricing.prices_for(sorted(visible), price_list, party, settings) if visible else {}
	available = stock.bulk_availability(sorted(visible)) if visible else {}
	problems = []
	for line in lines:
		code, qty = line["item_code"], line["qty"]
		if code not in visible:
			problems.append({"item_code": code, "code": "not_available", "message": "Not published in this shop, or a model: order its variants."})
		elif code not in prices:
			problems.append({"item_code": code, "code": "no_price", "message": "No price on this customer's price list (price on request)."})
		elif available[code].availability == stock.OUT_OF_STOCK:
			problems.append({"item_code": code, "code": "out_of_stock", "message": "Out of stock."})
		elif (
			available[code].availability != stock.BACK_ORDER
			and available[code].qty is not None
			and flt(available[code].qty) < flt(qty)
		):
			problems.append({"item_code": code, "code": "insufficient_stock", "message": "Not enough in stock for this quantity."})
	return problems, price_list


def create_order(access, body):
	"""(status, order, replayed): 201 for a new order, 200 for a replay or a dry run."""
	if not access.scope_orders:
		raise ApiError(403, "scope_missing", "This key may not place orders.")
	asked = _clean_order(body)
	customer = access.customer
	digest = hashlib.sha256(
		json.dumps(
			{"reference": asked["reference"], "lines": sorted(asked["lines"], key=lambda line: line["item_code"]), "delivery": str(asked["delivery"] or "")},
			sort_keys=True,
		).encode()
	).hexdigest()
	lookup = hashlib.sha256(f"{customer}\n{asked['key']}".encode()).hexdigest()
	# two calls of one customer meet here: the second reads, once the first has committed, what it wrote
	frappe.db.get_value("Customer", customer, "name", for_update=True)
	known = frappe.db.get_value("Partner API Order", lookup, ["sales_order", "request_hash"], as_dict=True, for_update=True)
	if known and not asked["dry_run"]:
		if known.request_hash != digest:
			raise ApiError(422, "idempotency_conflict", "This idempotency_key was used with other lines. Use a new key for a new order.")
		return 200, get_order(access, known.sales_order), True
	problems, price_list = _check_lines(customer, asked["lines"])
	if problems:
		raise ApiError(422, "invalid_lines", "Some lines cannot be served. Nothing was ordered.", details={"lines": problems})
	settings = frappe.get_cached_doc("Webshop Settings")
	user = access.requested_by or "Administrator"
	try:
		with shop_rights():
			order = frappe.get_doc(
				{
					"doctype": "Sales Order",
					"customer": customer,
					"company": settings.company,
					"transaction_date": nowdate(),
					"delivery_date": asked["delivery"] or add_days(nowdate(), 1),
					"selling_price_list": price_list,
					"po_no": asked["reference"],
					"items": [{"item_code": line["item_code"], "qty": line["qty"]} for line in asked["lines"]],
				}
			)
			order.flags.ignore_permissions = True
			order.insert()
			if access.submit_orders and not asked["dry_run"]:
				order.submit()
	except (frappe.ValidationError, frappe.PermissionError) as error:
		frappe.db.rollback()
		raise ApiError(422, "order_refused", f"The order could not be made: {frappe.utils.strip_html(str(error))[:300]}") from None
	frappe.db.set_value("Sales Order", order.name, {"owner": user, "modified_by": user}, update_modified=False)
	made = get_order(access, order.name)
	if asked["dry_run"]:
		frappe.db.rollback()
		return 200, {**made, "id": None, "dry_run": True}, False
	frappe.get_doc(
		{
			"doctype": "Partner API Order",
			"lookup": lookup,
			"customer": customer,
			"idempotency_key": asked["key"],
			"request_hash": digest,
			"sales_order": order.name,
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()
	return 201, made, False
