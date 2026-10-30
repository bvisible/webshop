# //// Neoffice — added file (no upstream equivalent).
"""The product sheet: one product as a page a person can keep or hand over.

Two issuers, one reading of the product. The **shop** hands a visitor the sheet of what the page shows
(price, availability, promises, a QR code to the page). A **reseller** hands their customers a sheet in their
own name: their logo and colours, their contact details, their prices — the price the reseller pays, plus
their markup — and no availability or promise, which are the supplier's, not theirs.

Everything the sheet says is read from `seo.facts.product_facts`, the reading the product page's structured
data and the Google feed share: a sheet that disagreed with the page by a cent would be a second source of
truth. A model with variants prints no price of its own, exactly as its page does; its choices are listed.
"""

import html

import frappe
from frappe import _
from frappe.utils import cint, flt, fmt_money, formatdate, nowdate

from webshop.webshop.catalogue import brand, images, markup, qr
from webshop.webshop.seo.text import truncate

MAX_PICTURES = 4
MAIN_PICTURE = (1000, 82)
THUMBNAIL = (420, 78)
MAX_DESCRIPTION = 800
MAX_SPECS = 14
MAX_VARIANTS = 24
DEFAULT_COLOUR = "#1f2933"
SHOP = "shop"
RESELLER = "reseller"


# ---------------------------------------------------------------------------
# which product, and what the page knows of it
# ---------------------------------------------------------------------------


def find_item(reference):
	"""The Website Item a sheet may be made of, or None: published, not sold, visible on this site.

	`reference` is a Website Item's name or its item code. Whatever is not offered by the shop being
	browsed has no sheet, and nothing tells the difference between that and a code that does not exist."""
	if not reference or not isinstance(reference, str):
		return None
	name = frappe.db.get_value("Website Item", {"name": reference}, "name") or frappe.db.get_value(
		"Website Item", {"item_code": reference}, "name"
	)
	if not name:
		return None
	doc = frappe.get_doc("Website Item", name)
	if not cint(doc.published) or cint(doc.get("sold")):
		return None
	from webshop.webshop.multi_site import excluded_item_names

	if doc.name in (excluded_item_names() or []):
		return None
	return doc


def page_context(doc):
	"""The part of the product page's context the sheet reads: the price this visitor is shown, the
	slideshow, the model a variant belongs to. Built the way `Website Item.get_context` builds it."""
	from frappe.website.doctype.website_slideshow.website_slideshow import get_slideshow

	from webshop.webshop.seo.variants import group_model, offered_variants

	context = frappe._dict()
	doc.set_shopping_cart_data(context)
	if not doc.website_image and doc.variant_of:
		from webshop.webshop.utils.variant_image import inherit_template_images

		inherit_template_images([doc])
	if doc.slideshow:
		context.update(get_slideshow(doc))
	settings = context.shopping_cart.cart_settings
	context.group_model = group_model(doc, settings)
	if context.group_model == doc.item_code:
		context.model_variants = offered_variants(doc.item_code, settings)
	return context


def _picture_urls(doc, context):
	"""The pictures the page's gallery shows, as addresses of public files: the model's, for a variant."""
	from frappe.website.doctype.website_slideshow.website_slideshow import get_slideshow

	from webshop.webshop.seo.facts import gallery_images
	from webshop.webshop.seo.variants import model_page_name

	model_code = context.get("group_model")
	source, source_context = doc, context
	if model_code and doc.item_code != model_code:
		name = model_page_name(model_code)
		if name:
			source = frappe.get_doc("Website Item", name)
			source_context = frappe._dict()
			if source.slideshow:
				source_context.update(get_slideshow(source))
	return gallery_images(source, source_context)[:MAX_PICTURES]


def _pictures(doc, context):
	"""The main picture and up to three thumbnails, rebuilt small, as data URIs."""
	uris = []
	for index, url in enumerate(_picture_urls(doc, context)):
		side, quality = MAIN_PICTURE if index == 0 else THUMBNAIL
		uri = images.site_picture(url, max_side=side, quality=quality)
		if uri:
			uris.append(uri)
	return uris


# ---------------------------------------------------------------------------
# what the sheet says
# ---------------------------------------------------------------------------


def availability_line(schema_url):
	"""The pill under the price: the shop's own stock rule, in words."""
	from webshop.webshop.seo.availability import BACK_ORDER, IN_STOCK

	if schema_url == IN_STOCK:
		return frappe._dict(label=_("In stock"), tone="in")
	if schema_url == BACK_ORDER:
		return frappe._dict(label=_("On order"), tone="order")
	return frappe._dict(label=_("Out of stock"), tone="out")


def used_lines(doc):
	"""What the page says about a second-hand or refurbished unit, or None."""
	from webshop.webshop.utils.used_items import condition_info

	info = condition_info(doc)
	if not info:
		return None
	months = info.warranty_months
	return frappe._dict(
		condition=_(info.condition),
		grade=_(info.grade) if info.grade else "",
		details=truncate(frappe.utils.strip_html(info.details or ""), 240),
		warranty=_("{0}-month warranty").format(months) if months else "",
	)


def price_text(amount, currency):
	"""A price with its currency, always. Global Defaults' "hide currency symbol" is a preference of the
	desk's screens and makes `fmt_money` drop it; a sheet is read away from the site, where a bare figure
	says nothing (osiris printed "160.65" for a price in CHF)."""
	text = fmt_money(flt(amount), currency=currency or None)
	if currency and frappe.defaults.get_global_default("hide_currency_symbol") == "Yes":
		text = f"{currency} {text}"
	return text


def shop_price(offer):
	"""The price the page prints, and the struck one where the page prints it."""
	if not offer:
		return None
	return frappe._dict(
		amount=price_text(offer.price, offer.currency),
		struck=price_text(offer.struck_price, offer.currency) if offer.struck_price else "",
		note="",
	)


def reseller_price(offer, values):
	"""The price the reseller sells at: what they pay for it, plus their markup, rounded, VAT if shown.

	The price they pay is the page's own (their price list, their rules): never printed, never struck."""
	if not offer:
		return None
	including_vat = values["price_display"] == "Including VAT"
	selling = markup.selling_price(
		offer.price, values["default_markup_percent"], values["price_rounding"], values["vat_rate"], including_vat
	)
	return frappe._dict(
		amount=price_text(selling, offer.currency),
		struck="",
		note=_("Including VAT") if including_vat else _("Excluding VAT"),
	)


def _plain(text):
	"""A name as a person reads it. Frappe stores what a merchant types in a Data field with its HTML
	characters escaped (`&amp;`, `&lt;`), and the template escapes once more: the text of the sheet is the
	stored one, decoded once, so a product called "Salt & Pepper" prints so, not "Salt &amp; Pepper"."""
	return html.unescape(text) if isinstance(text, str) else (text or "")


def _specs(facts, item_code, settings):
	from webshop.webshop.seo.facts import shown_identifiers

	rows = [(_plain(name), value) for name, value in (facts.get("properties") or [])]
	return rows[:MAX_SPECS], shown_identifiers(item_code, settings)


def _variant_rows(group, price_for):
	rows = []
	for variant in (group.variants or [])[:MAX_VARIANTS]:
		identifiers = variant.identifiers or {}
		ean = identifiers.get("gtin13") or identifiers.get("gtin8") or identifiers.get("gtin12") or identifiers.get("gtin14") or ""
		price = price_for(variant.offer)
		rows.append(frappe._dict(name=_plain(variant.name), ean=ean, price=price.amount if price else ""))
	return rows


def _description(text):
	return [line for line in truncate(text or "", MAX_DESCRIPTION).split("\n") if line.strip()]


def _abbreviation(name):
	words = [word for word in (name or "").split() if word[:1].isalnum()]
	return "".join(word[0] for word in words[:2]).upper() or "?"


# ---------------------------------------------------------------------------
# the two issuers
# ---------------------------------------------------------------------------


def shop_issuer():
	"""The shop's header: its name and, when its site chrome has a PNG or JPEG logo, the logo; its colour."""
	from webshop.webshop.seo.site import shop_name

	issuer = frappe._dict(name=_plain(shop_name()), logo=None, colour=DEFAULT_COLOUR, contact=[], footer="", credit="")
	try:
		from builder.hf_utils.header_footer import get_header_footer_config
	except ImportError:
		return issuer
	config = get_header_footer_config()
	if not config:
		return issuer
	colour = getattr(config, "primary_color", None)
	if brand.is_colour(colour):
		issuer.colour = colour.lower()
	if getattr(config, "logo_type", "") == "Image" and getattr(config, "logo_image", None):
		# an SVG logo cannot be rebuilt by Pillow: the sheet then prints the shop's name
		issuer.logo = images.site_picture(config.logo_image, max_side=500, quality=85)
	return issuer


def reseller_issuer(brand_payload, credit_line):
	"""The reseller's header, from their brand settings (`api._payload`): logo, colour, contact lines."""
	values = brand_payload["values"]
	# four short lines rather than six: the header of a one-page sheet is not the place for a letterhead
	address = ", ".join(line for line in (values.get("contact_address") or "").split("\n") if line)
	contact = [
		" · ".join(part for part in (values.get("contact_email"), values.get("contact_phone")) if part),
		values.get("contact_website"),
		address,
		_("VAT no. {0}").format(values["vat_number"]) if values.get("vat_number") else "",
	]
	return frappe._dict(
		name=values.get("brand_name") or "",
		logo=brand_payload.get("logo"),
		colour=values.get("primary_colour") or DEFAULT_COLOUR,
		contact=[line for line in contact if line],
		footer=values.get("footer_text") or "",
		credit=credit_line or "",
	)


def _website_address(value):
	value = (value or "").strip()
	if not value:
		return ""
	return value if value.startswith(("http://", "https://")) else "https://" + value


# ---------------------------------------------------------------------------
# the sheet
# ---------------------------------------------------------------------------


def build_sheet(doc, issuer_kind=SHOP, reseller=None):
	"""Everything the template prints, for `doc` (a Website Item this site sells).

	`reseller` (with `issuer_kind` RESELLER) is the brand payload of the signed-in reseller
	(`catalogue.api._payload`) and the supplier's credit line, as {payload, credit_line, prices}."""
	from webshop.webshop.multi_site import site_url
	from webshop.webshop.seo.facts import product_facts

	context = page_context(doc)
	settings = context.shopping_cart.cart_settings
	facts = product_facts(doc, context)
	group = facts.get("group")
	core = group or facts
	item_code = context.get("group_model") or doc.item_code
	specs, identifiers = _specs(core, item_code, settings)
	reseller_mode = issuer_kind == RESELLER

	if reseller_mode:
		values = reseller["payload"]["values"]
		issuer = reseller_issuer(reseller["payload"], reseller["credit_line"])
		with_prices = bool(reseller.get("prices", True))
		price_for = (lambda offer: reseller_price(offer, values)) if with_prices else (lambda offer: None)
		website = _website_address(values.get("contact_website"))
		qr_target = website
		qr_caption = _("Scan to visit {0}").format(values.get("contact_website")) if website else ""
	else:
		issuer = shop_issuer()
		price_for = shop_price
		qr_target = site_url(doc.route)
		qr_caption = _("Scan to see this product online")

	offer = None if group else facts.get("offer")
	price = price_for(offer)
	# availability and promises are the supplier's: a reseller's customers are not promised them
	availability = None if reseller_mode or group or not offer else availability_line(offer.availability)
	promises = []
	if not reseller_mode:
		from webshop.webshop.utils.promises import shopping_promises

		promises = [promise["text"] for promise in shopping_promises(settings)]

	return frappe._dict(
		lang=frappe.local.lang or "en",
		title=_plain(core.name),
		name=_plain(core.name),
		brand=_plain(core.get("brand")),
		category=_plain(core.get("category")),
		reference=item_code,
		identifiers=identifiers,
		abbreviation=_abbreviation(_plain(core.name)),
		pictures=_pictures(doc, context),
		price=price,
		availability=availability,
		used=used_lines(doc),
		promises=promises,
		description=_description(core.get("description")),
		specs=specs,
		variants=_variant_rows(group, price_for) if group else [],
		choices=len(group.variants or []) if group else 0,
		show_variant_prices=bool(group) and not (reseller_mode and not reseller.get("prices", True)),
		qr=qr.qr_data_uri(qr_target) if qr_target else None,
		qr_caption=qr_caption,
		date_line=_("Prices valid on {0}").format(formatdate(nowdate())) if (price or group) else formatdate(nowdate()),
		issuer=issuer,
	)


# ---------------------------------------------------------------------------
# the page
# ---------------------------------------------------------------------------


def css_string(text):
	"""`text` as the inside of a CSS string literal, safe inside a <style> element: no quote, backslash,
	angle bracket or control character gets through."""
	cleaned = "".join(char if char >= " " and char != "\x7f" else " " for char in str(text or ""))
	for char, replacement in (("\\", "/"), ('"', "'"), ("<", "("), (">", ")")):
		cleaned = cleaned.replace(char, replacement)
	return " ".join(cleaned.split())


def page_css(sheet):
	"""The stylesheet: the file, the issuer's colour, and the @page rule with the issuer's footer."""
	with open(frappe.get_app_path("webshop", "templates", "catalogue", "product_sheet.css"), encoding="utf-8") as handle:
		base = handle.read()
	colour = sheet.issuer.colour if brand.is_colour(sheet.issuer.colour) else DEFAULT_COLOUR
	footer = css_string(sheet.issuer.name)
	font = '7.5pt "Helvetica Neue", Arial, sans-serif'
	page = (
		"@page { size: A4; margin: 14mm 14mm 20mm 14mm; "
		f'@bottom-left {{ content: "{footer}"; font: {font}; color: #7b8794; }} '
		f'@bottom-right {{ content: counter(page) " / " counter(pages); font: {font}; color: #7b8794; }} }}'
	)
	return f":root {{ --brand: {colour}; --on-brand: {brand.readable_ink(colour)}; }}\n{base}\n{page}\n"


def render_html(sheet):
	return frappe.render_template("templates/catalogue/product_sheet.html", {"sheet": sheet, "css": page_css(sheet)})
