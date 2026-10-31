# //// Neoffice — added file (no upstream equivalent).
"""The lines of a spreadsheet or a feed: one per thing that can be bought, priced for one reseller.

`book.py` makes the content of a PDF (a model is one card, "from" its cheapest variant); a table is read
by a machine or filtered by a person, and a model cannot be bought, so its lines are its variants. The
selection, the scope (published, not sold, visible on this site), the customer's price and the reseller's
markup are the catalogue's own: the same functions, the same answer — a figure in a spreadsheet is the
figure of the PDF.

**Which price is in the file depends on the mode asked**, and the server decides it, never the browser:

- `customers`: what the reseller sells at — what they pay, plus their markup, rounded, VAT if shown. For
  their own customers and their own shop.
- `tariff`: what they pay (their price list, the shop's rules), alone. For their own use.
- `both`: the two side by side, to work a margin.
- `none`: no price.

The shop's own price is never in a line, and a feed (served by a secret address) carries only `customers`
or `none`: the address would give a competitor the price a reseller pays if it leaked.
"""

import html

import frappe
from frappe import _
from frappe.utils import formatdate, nowdate

from webshop.webshop.catalogue import book, markup, selection
from webshop.webshop.multi_site import site_url
from webshop.webshop.seo import availability as stock
from webshop.webshop.seo import variants as seo_variants
from webshop.webshop.seo.facts import bulk_identifiers, category_path
from webshop.webshop.seo.text import html_to_text
from webshop.webshop.utils import customer_pricing

PRICE_MODES = ("customers", "tariff", "both", "none")
FEED_PRICE_MODES = ("customers", "none")
MAX_ROWS = 5000  # lines: about two minutes of prices, the long queue's worker is shared
MAX_DESCRIPTION = 2000
MAX_MORE_IMAGES = 9
AVAILABILITY = {stock.IN_STOCK: "in_stock", stock.BACK_ORDER: "backorder", stock.OUT_OF_STOCK: "out_of_stock"}
DETAIL_FIELDS = [
	"item_code",
	"web_item_name",
	"item_name",
	"brand",
	"item_group",
	"website_image",
	"slideshow",
	"short_description",
	"web_long_description",
	"variant_of",
	"route",
]


def clean_options(raw, default_markup, modes=PRICE_MODES):
	"""The options a table is made with: {"markup_percent": float, "prices": one of `modes`}.

	The markup defaults to the reseller's own; the mode comes from a closed list. A price is never an option."""
	raw = raw if isinstance(raw, dict) else {}
	percent = raw.get("markup_percent")
	if percent in (None, ""):
		percent = default_markup
	try:
		percent = float(markup.clean_markup_percent(percent))
	except ValueError:
		raise book.OptionsRefused("markup_percent", "out_of_range") from None
	prices = raw.get("prices") or "customers"
	if prices not in modes:
		raise book.OptionsRefused("prices", "not_allowed")
	return {"markup_percent": percent, "prices": prices}


def columns_for(prices):
	"""The keys of a line, in the order of the file; the price columns exist only for the modes that carry them."""
	columns = ["code", "model", "name", "brand", "category", "ean", "mpn", "unit", "attributes"]
	if prices != "none":
		columns.append("currency")
		if prices in ("tariff", "both"):
			columns.append("purchase_price")
		if prices in ("customers", "both"):
			columns += ["price", "price_includes_vat"]
	return columns + ["availability", "description", "image", "more_images", "url"]


def _plain(value):
	"""Frappe stores a Data field with its HTML characters escaped: write what was typed."""
	return html.unescape(value) if isinstance(value, str) else (value or "")


def _public(path):
	"""The whole address of a picture anybody can fetch, or None: a private file is not for a reseller's shop."""
	if not path or path.startswith(("/private/", "private/")):
		return None
	return site_url(path)


def _variants_of(models):
	"""{model: [its published, unsold variants' codes]} as the shop shows them on this site."""
	if not models:
		return {}
	filters = selection.scope()
	filters["variant_of"] = ["in", list(models)]
	found = {}
	for row in frappe.get_all(
		"Website Item", filters=filters, fields=["item_code", "variant_of"], order_by="variant_of asc, item_code asc"
	):
		found.setdefault(row.variant_of, []).append(row.item_code)
	return found


def _lines(products):
	"""The item codes of the lines, in the products' order: a model brings its variants, a code stands once."""
	models = [row.item_code for row in products if row.has_variants]
	variants = _variants_of(models)
	codes, seen = [], set()
	for row in products:
		for code in variants.get(row.item_code, []) if row.has_variants else [row.item_code]:
			if code not in seen:
				seen.add(code)
				codes.append(code)
	return codes, models


def _attributes(codes):
	"""{variant code: {attribute: value}}, the attributes in the order the item lists them."""
	found = {}
	for row in frappe.get_all(
		"Item Variant Attribute",
		filters={"parent": ["in", codes], "parenttype": "Item"},
		fields=["parent", "attribute", "attribute_value"],
		order_by="parent asc, idx asc",
	):
		found.setdefault(row.parent, {})[_plain(row.attribute)] = _plain(row.attribute_value)
	return found


def _slides(details):
	"""{slideshow name: [images]} for every slideshow the lines (or their models) point at."""
	names = list({row.slideshow for row in details.values() if row.get("slideshow")})
	if not names:
		return {}
	found = {}
	for row in frappe.get_all(
		"Website Slideshow Item",
		filters={"parent": ["in", names], "parenttype": "Website Slideshow"},
		fields=["parent", "image"],
		order_by="parent asc, idx asc",
	):
		found.setdefault(row.parent, []).append(row.image)
	return found


def _urls(codes, details):
	"""{code: whole address of its page}: a variant is read through its model's page opened on it."""
	items = [{"item_code": code, "route": (details.get(code) or {}).get("route") or ""} for code in codes]
	seo_variants.link_variants_to_models(items)
	return {item["item_code"]: site_url(item["route"]) if item["route"] else "" for item in items}


def count_lines(clean_selection):
	"""How many lines a clean selection makes, counted up to one above the cap. Two reads, no price."""
	products = selection.product_rows(clean_selection, limit=MAX_ROWS + 1)
	return len(_lines(products)[0]) if len(products) <= MAX_ROWS else MAX_ROWS + 1


def build_rows(customer, payload, clean_selection, options, progress=None, include_variants=False):
	"""The lines a clean selection stands for, priced for `customer` (the reseller's brand is `payload`).

	Returns {columns, rows, currency, prices, markup_percent, including_vat, prices_as_of}. `progress`, when
	given, is called as progress("prices", done, total)."""
	products = selection.product_rows(clean_selection, limit=MAX_ROWS + 1, variants=include_variants)
	if not products:
		raise book.CatalogueRefused("empty")
	if len(products) > MAX_ROWS:
		raise book.CatalogueRefused("too_many_rows")
	codes, models = _lines(products)
	if not codes:
		raise book.CatalogueRefused("empty")
	if len(codes) > MAX_ROWS:
		raise book.CatalogueRefused("too_many_rows")

	mode = options["prices"]
	values = payload["values"]
	including_vat = values["price_display"] == "Including VAT"
	settings = frappe.get_cached_doc("Webshop Settings")
	party = frappe.get_doc("Customer", customer)
	price_list = customer_pricing.customer_price_list(settings, party)
	currency = customer_pricing.currency_of(price_list)
	costs = book.price_many(codes, price_list, party, settings, progress) if mode != "none" else {}

	details = {
		row.item_code: row
		for row in frappe.get_all(
			"Website Item", filters={"item_code": ["in", list({*codes, *models})]}, fields=DETAIL_FIELDS
		)
	}
	items = {
		row.name: row
		for row in frappe.get_all("Item", filters={"name": ["in", codes]}, fields=["name", "stock_uom", "variant_of"])
	}
	# a variant asked for on its own inherits its model's picture and text: the model may not be in the selection
	absent = {row.variant_of for row in items.values() if row.variant_of} - set(details)
	if absent:
		details.update(
			{
				row.item_code: row
				for row in frappe.get_all("Website Item", filters={"item_code": ["in", list(absent)]}, fields=DETAIL_FIELDS)
			}
		)
	attributes = _attributes(codes)
	identifiers = bulk_identifiers(codes)
	available = stock.bulk_availability(codes)
	slides = _slides(details)
	pages = _urls(codes, details)
	categories = {}

	def category(group):
		if group not in categories:
			categories[group] = category_path(group) or _plain(group)
		return categories[group]

	def selling(cost):
		if cost is None:
			return None
		price = markup.selling_price(
			cost, options["markup_percent"], values["price_rounding"], values["vat_rate"], including_vat
		)
		return float(price)

	lines = []
	for code in codes:
		detail = details.get(code) or frappe._dict()
		model_code = (items.get(code) and items[code].variant_of) or detail.get("variant_of") or ""
		model = details.get(model_code) or frappe._dict()
		name = _plain(detail.get("web_item_name") or detail.get("item_name") or model.get("web_item_name") or code)
		main = _public(detail.get("website_image") or model.get("website_image"))
		show = detail.get("slideshow") or model.get("slideshow")
		more = []
		for image in slides.get(show, []):
			url = _public(image)
			if url and url != main and url not in more:
				more.append(url)
		text = html_to_text(
			detail.get("web_long_description")
			or detail.get("short_description")
			or model.get("web_long_description")
			or model.get("short_description"),
			MAX_DESCRIPTION,
		)
		identifier = identifiers.get(code) or {}
		line = {
			"code": code,
			"model": model_code,
			"name": name,
			"brand": _plain(detail.get("brand") or model.get("brand")),
			"category": category(detail.get("item_group") or model.get("item_group")),
			"ean": next((value for key, value in identifier.items() if key.startswith("gtin")), ""),
			"mpn": identifier.get("mpn", ""),
			"unit": (items.get(code) and items[code].stock_uom) or "",
			"attributes": attributes.get(code, {}),
		}
		if mode != "none":
			line["currency"] = currency
			cost = (costs.get(code) or {}).get("price")
			if mode in ("tariff", "both"):
				line["purchase_price"] = round(float(cost), 4) if cost is not None else None
			if mode in ("customers", "both"):
				line["price"] = selling(cost)
				line["price_includes_vat"] = including_vat
		line.update(
			availability=AVAILABILITY.get(available[code].availability, "out_of_stock"),
			description=_plain(text),
			image=main or "",
			more_images=more[:MAX_MORE_IMAGES],
			url=pages.get(code, ""),
		)
		lines.append(line)

	return frappe._dict(
		columns=columns_for(mode),
		rows=lines,
		currency=currency,
		prices=mode,
		markup_percent=options["markup_percent"],
		including_vat=including_vat,
		prices_as_of=nowdate(),
	)


def labels(data, title="", issuer=""):
	"""The words of the Excel file, in the language the job runs in: headers, the answers a cell can hold, and
	the sheet that says what the file is. (CSV and JSON carry the machine names instead.)"""
	columns = {
		"code": _("Code"),
		"model": _("Model"),
		"name": _("Name"),
		"brand": _("Brand"),
		"category": _("Category"),
		"ean": _("EAN"),
		"mpn": _("Manufacturer's reference"),
		"unit": _("Unit"),
		"attributes": _("Variant"),
		"currency": _("Currency"),
		"purchase_price": _("Your purchase price"),
		"price": _("Selling price"),
		"price_includes_vat": _("Price includes VAT"),
		"availability": _("Availability"),
		"description": _("Description"),
		"image": _("Picture"),
		"more_images": _("More pictures"),
		"url": _("Page"),
	}
	facts = {_("Title"): title}
	if issuer:
		facts[_("Made for")] = issuer
	facts[_("Made on")] = formatdate(nowdate())
	facts[_("Prices as of")] = formatdate(data.prices_as_of)
	facts[_("Lines")] = len(data.rows)
	if data.prices != "none":
		facts[_("Currency")] = data.currency
	if data.prices in ("customers", "both"):
		facts[_("Markup")] = f"{data.markup_percent:g} %"
		facts[_("Selling prices")] = _("Including VAT") if data.including_vat else _("Excluding VAT")
	if data.prices in ("tariff", "both"):
		facts[_("Purchase prices")] = _("Your own price list, as the shop's rules apply to you. Confidential: not for your customers.")
	return {
		"columns": columns,
		"availability": {
			"in_stock": _("In stock"),
			"out_of_stock": _("Out of stock"),
			"backorder": _("On backorder"),
		},
		"yes": _("Yes"),
		"no": _("No"),
		"products": _("Products"),
		"information": _("Information"),
		"facts": facts,
	}
