# //// Neoffice — added file (no upstream equivalent).
"""A catalogue's content: sections of products, priced for one reseller, ready for the template.

What the reseller sees is computed here, on the server, from what they asked for: a selection (which
products), a markup, a layout. The browser never sends a price. Every product is read the way the shop
shows it (published, not sold, visible on this site) and priced the way the cart will charge THIS
customer (their price list, the shop's rules), then the reseller's markup is added.

Two things are deliberate, and tested:
- **The price the reseller pays is never printed**: `Product.price` holds the selling price only, and
  a catalogue made without prices carries none at all.
- **A model is one card**, "from" the price of its cheapest variant (the variant with the lowest list
  rate, priced like any other item): pricing every variant of every model would multiply the cost of a
  catalogue — a customer's price costs about 21 ms an item — for a figure nobody prints.
"""

import html

import frappe
from frappe import _
from frappe.utils import formatdate, nowdate, strip_html

from webshop.webshop.catalogue import images, markup, markup_rules, selection
from webshop.webshop.catalogue.sheet import price_text, reseller_issuer
from webshop.webshop.seo.text import truncate
from webshop.webshop.utils import customer_pricing

LAYOUTS = ("grid", "list")
PRICE_MODES = ("customers", "none")
TITLE_MAX = 80
CARD_PICTURE = (440, 74)  # longest side in pixels, JPEG quality: a card is 56 mm wide, 200 dpi is enough
DESCRIPTION_MAX = 180
PRICE_CHUNK = 20  # items priced between two reports of progress


class CatalogueRefused(ValueError):
	"""A catalogue that cannot be made; `reason` is a short code `refusals.catalogue_message` words."""

	def __init__(self, reason):
		super().__init__(reason)
		self.reason = reason


class OptionsRefused(ValueError):
	"""An option that is not one of the allowed values; `field` names it for the page."""

	def __init__(self, field, reason):
		super().__init__(f"{field}: {reason}")
		self.field = field
		self.reason = reason


def _plain(value):
	"""Frappe stores a Data field with its HTML characters escaped: print what was typed."""
	return html.unescape(value) if isinstance(value, str) else (value or "")


def clean_title(value):
	"""The catalogue's title: a plain text of 1 to TITLE_MAX characters, on one line."""
	title = " ".join(str(value or "").split())
	if not title:
		raise OptionsRefused("title", "required")
	if len(title) > TITLE_MAX:
		raise OptionsRefused("title", "too_long")
	if any(char in title for char in "<>"):
		raise OptionsRefused("title", "not_plain")
	return title


def clean_options(raw, default_markup):
	"""The options a catalogue is made with: {"markup_percent": float, "prices": ..., "layout": ...}.

	The markup defaults to the reseller's own; the others come from closed lists. A price is never an option."""
	raw = raw if isinstance(raw, dict) else {}
	percent = raw.get("markup_percent")
	if percent in (None, ""):
		percent = default_markup
	try:
		percent = float(markup.clean_markup_percent(percent))
	except ValueError:
		raise OptionsRefused("markup_percent", "out_of_range") from None
	prices = raw.get("prices") or "customers"
	if prices not in PRICE_MODES:
		raise OptionsRefused("prices", "not_allowed")
	layout = raw.get("layout") or "grid"
	if layout not in LAYOUTS:
		raise OptionsRefused("layout", "not_allowed")
	return {"markup_percent": percent, "prices": prices, "layout": layout}


def _abbreviation(name):
	words = [word for word in (name or "").split() if word[:1].isalnum()]
	return "".join(word[0] for word in words[:2]).upper() or "?"


def _short_text(row):
	text = strip_html(row.get("short_description") or "")
	return truncate(" ".join(_plain(text).split()), DESCRIPTION_MAX)


def _cheapest_variants(models, price_list):
	"""{model code: (its variant with the lowest list rate, how many variants the shop offers)}."""
	if not models:
		return {}
	variants = frappe.get_all(
		"Website Item",
		filters={"variant_of": ["in", models], "published": 1, "sold": 0},
		fields=["item_code", "variant_of"],
	)
	rates = customer_pricing.list_rates([row.item_code for row in variants], price_list) if variants else {}
	found = {}
	for row in variants:
		cheapest, count = found.get(row.variant_of, (None, 0))
		rate = rates.get(row.item_code)
		if rate is not None and (cheapest is None or rate < rates[cheapest]):
			cheapest = row.item_code
		found[row.variant_of] = (cheapest, count + 1)
	return found


def price_many(codes, price_list, party, settings, progress):
	"""{item code: price dict} for every code the customer has a price for, reporting as it goes."""
	prices = {}
	for start in range(0, len(codes), PRICE_CHUNK):
		chunk = codes[start : start + PRICE_CHUNK]
		prices.update(customer_pricing.prices_for(chunk, price_list, party, settings))
		if progress:
			progress("prices", min(start + PRICE_CHUNK, len(codes)), len(codes))
	return prices


def _inherited_pictures(rows):
	"""{variant item code: its model's picture} for the variants that have none of their own."""
	wanted = {row.variant_of for row in rows if row.variant_of and not row.website_image}
	if not wanted:
		return {}
	by_model = dict(
		frappe.get_all("Website Item", filters={"item_code": ["in", list(wanted)]}, fields=["item_code", "website_image"], as_list=True)
	)
	return {row.item_code: by_model.get(row.variant_of) for row in rows if row.variant_of and not row.website_image}


def build_book(customer, payload, credit_line, title, clean_selection, options, progress=None):
	"""Everything the template prints. `payload` is the reseller's brand (`api._payload`); `progress`, when
	given, is called as progress(stage, done, total) with stage "prices" or "pictures"."""
	rows = selection.product_rows(clean_selection)
	if not rows:
		raise CatalogueRefused("empty")
	if len(rows) > selection.MAX_PRODUCTS:
		raise CatalogueRefused("too_many_products")

	values = payload["values"]
	with_prices = options["prices"] == "customers"
	settings = frappe.get_cached_doc("Webshop Settings")
	party = frappe.get_doc("Customer", customer)
	price_list = customer_pricing.customer_price_list(settings, party)
	currency = customer_pricing.currency_of(price_list)
	including_vat = values["price_display"] == "Including VAT"

	models = {row.item_code: row for row in rows if row.has_variants}
	variants_of = _cheapest_variants(list(models), price_list)
	prices = {}
	if with_prices:
		to_price = [row.item_code for row in rows if not row.has_variants]
		to_price += [cheapest for cheapest, _count in variants_of.values() if cheapest]
		prices = price_many(to_price, price_list, party, settings, progress)

	markups = markup_rules.load(customer, options["markup_percent"])

	def selling(code, row):
		cost = (prices.get(code) or {}).get("price")
		if cost is None:
			return None
		# a model's "from" price is its cheapest variant's, marked up as the model is
		percent = markups.percent([row.item_code], row.item_group, row.brand)
		price = markup.selling_price(cost, percent, values["price_rounding"], values["vat_rate"], including_vat)
		return price_text(price, currency)

	inherited = _inherited_pictures(rows)
	sections = []
	for index, row in enumerate(rows):
		name = _plain(row.web_item_name or row.item_name or row.item_code)
		picture_url = row.website_image or inherited.get(row.item_code)
		picture = None
		if picture_url:
			picture = images.site_picture(picture_url, max_side=CARD_PICTURE[0], quality=CARD_PICTURE[1], small_copy=True)
		if row.has_variants:
			cheapest, choices = variants_of.get(row.item_code, (None, 0))
			text = selling(cheapest, row) if cheapest else None
		else:
			text, choices = selling(row.item_code, row), 0
		product = frappe._dict(
			name=name,
			brand=_plain(row.brand),
			reference=row.item_code,
			picture=picture,
			abbreviation=_abbreviation(name),
			description=_short_text(row),
			price=text if with_prices else None,
			price_missing=with_prices and text is None,
			price_from=bool(row.has_variants),
			choices=choices,
		)
		group = _plain(row.item_group)
		if not sections or sections[-1].title != group:
			sections.append(frappe._dict(title=group, products=[]))
		sections[-1].products.append(product)
		if progress:
			progress("pictures", index + 1, len(rows))

	valid = _("Prices valid on {0}").format(formatdate(nowdate()))
	return frappe._dict(
		lang=frappe.local.lang or "en",
		title=title,
		issuer=reseller_issuer(payload, credit_line),
		date=formatdate(nowdate()),
		with_prices=with_prices,
		price_note=f"{valid} · {_('Including VAT') if including_vat else _('Excluding VAT')}" if with_prices else "",
		layout=options["layout"],
		sections=sections,
		product_count=len(rows),
	)
