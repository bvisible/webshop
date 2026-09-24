# //// Neoffice — added file (no upstream equivalent): what the outside world may know of a
# //// product on the site being served. neoffice-maintenance#691 (lot 1, D8), 2026-09-24.
"""Product facts: one reading of a product for every machine that describes it.

The product page's structured data reads them today, the Merchant Center feed will tomorrow,
and Google compares both with the page: an item is refused over a cent or an "in stock" of
difference. So nothing here recomputes what the page computed. The price is the one
`get_product_info_for_website` returned and the buy column printed, the struck price the
one it printed struck, the stock the shop's rule (availability.py), the pictures the
gallery's, the rating and the reviews the reviews block's. A fact the page does not show is
not declared.
"""

import re
from datetime import datetime

import frappe
from frappe.utils import cint, flt, getdate, now_datetime

from webshop.webshop.seo.text import html_to_text

# Identifiers a barcode can carry, by length (GS1): the most specific property name wins.
GTIN_PROPERTIES = {8: "gtin8", 12: "gtin12", 13: "gtin13", 14: "gtin14"}
MAX_IMAGES = 10
MAX_REVIEWS = 4  # what the reviews block shows


def product_facts(doc, context) -> frappe._dict:
	"""Everything the structured data of a product page may say, from the page's own context."""
	from webshop.webshop.multi_site import site_url
	from webshop.webshop.seo.availability import schema_availability

	cart_settings = context.shopping_cart.cart_settings
	url = site_url(doc.route)
	return frappe._dict(
		url=url,
		name=doc.web_item_name,
		sku=schema_sku(doc.item_code),
		brand=doc.brand or "",
		description=html_to_text(doc.web_long_description or doc.description or "", 5000),
		images=[absolute_url(image) for image in gallery_images(doc, context)],
		category=category_path(doc.item_group),
		identifiers=product_identifiers(doc.item_code),
		properties=specifications(doc),
		offer=offer_facts(doc, context, url, schema_availability(doc.item_code, cart_settings)),
		rating=rating_facts(context),
		reviews=review_facts(context),
		videos=video_facts(doc),
	)


def schema_sku(item_code: str) -> str:
	"""The item code without whitespace: Google refuses a sku that carries any (2024-02-09)."""
	return re.sub(r"\s+", "", item_code or "")


def gallery_images(doc, context) -> list[str]:
	"""The pictures the gallery shows (item_image.html), in its order: the slideshow when the
	item has one, else its website image."""
	slides = [slide.get("image") for slide in context.get("slides") or [] if slide.get("image")]
	images = slides or ([doc.website_image] if doc.website_image else [])
	return list(dict.fromkeys(images))[:MAX_IMAGES]


def category_path(item_group: str | None) -> str:
	"""The item group and its published ancestors, as the breadcrumb names them: "Shoes > Trail"."""
	if not item_group:
		return ""
	bounds = frappe.db.get_value("Item Group", item_group, ["lft", "rgt"], as_dict=True)
	if not bounds:
		return ""
	groups = frappe.get_all(
		"Item Group",
		filters={"lft": ("<=", bounds.lft), "rgt": (">=", bounds.rgt), "show_in_website": 1},
		fields=["name", "lft"],
		order_by="lft asc",
	)
	return " > ".join(group.name for group in groups if group.lft != 1)


def product_identifiers(item_code: str) -> dict:
	"""GTIN (only one whose check digit is right) and manufacturer part number, from the item."""
	identifiers = {}
	stock_uom = frappe.db.get_value("Item", item_code, "stock_uom")
	for row in frappe.get_all(
		"Item Barcode",
		filters={"parent": item_code, "parenttype": "Item"},
		fields=["barcode", "uom"],
		order_by="idx asc",
	):
		# a barcode of another unit (a carton of twelve) is not this product's
		if row.uom and row.uom != stock_uom:
			continue
		code = (row.barcode or "").strip()
		if valid_gtin(code):
			identifiers.setdefault(GTIN_PROPERTIES[len(code)], code)
	mpn = (frappe.db.get_value("Item", item_code, "default_manufacturer_part_no") or "").strip()
	if mpn:
		identifiers["mpn"] = mpn
	return identifiers


def valid_gtin(code: str) -> bool:
	"""A GTIN-8, 12, 13 or 14 whose GS1 check digit is right."""
	if not code or not code.isdigit() or len(code) not in GTIN_PROPERTIES or not int(code):
		return False
	digits = [int(char) for char in code]
	body, check = digits[:-1], digits[-1]
	total = sum(digit * (3 if position % 2 == 0 else 1) for position, digit in enumerate(reversed(body)))
	return (10 - total % 10) % 10 == check


def specifications(doc) -> list[tuple[str, str]]:
	"""The characteristics the page lists (item_specifications.html), as name and text."""
	found = []
	for row in doc.get("website_specifications") or []:
		name = (row.get("label") or "").strip()
		value = html_to_text(row.get("description") or "", 300)
		if name and value:
			found.append((name, value))
	return found


def offer_facts(doc, context, url: str, availability: str) -> frappe._dict | None:
	"""The offer the buy column shows, or None when it shows no price: prices hidden, hidden
	from a visitor, a gift card (the buyer chooses its amount), no price on the list."""
	from webshop.webshop.utils.used_items import condition_schema_url

	cart_settings = context.shopping_cart.cart_settings
	price = (context.shopping_cart.get("product_info") or {}).get("price") or {}
	if not cart_settings.get("show_price") or not price:
		return None
	if doc.get("is_gift_card"):
		return None
	# A model's page prints no price: its buy column is the variant selector, which prices a
	# variant once one is chosen (item_details.html). Declaring the cheapest variant's price
	# here was the mismatch Google refuses — measured on osiris, a polo's page offering 39.00
	# in its JSON-LD and nowhere in its HTML (2026-09-24). The variants' own offers belong in
	# a ProductGroup (decision D-1 of the SEO plan).
	if doc.get("has_variants"):
		return None
	# item_add_to_cart.html prints price_list_rate × conversion_factor as THE price
	amount = flt(price.get("price_list_rate")) * flt(price.get("conversion_factor") or 1)
	if amount <= 0:
		return None
	offer = frappe._dict(
		url=url,
		price=flt(amount, 2),
		currency=price.get("currency") or "",
		availability=availability,
		condition=condition_schema_url(doc.get("item_condition")),
		struck_price=None,
		valid_from=None,
		valid_until=None,
	)
	# The struck price is printed only when formatted_mrp is: then it is real, the list price
	# before the shop's own rule (PBV art. 16 wants a comparison price that was really asked).
	struck = flt(price.get("mrp"))
	if price.get("formatted_mrp") and struck > offer.price:
		offer.struck_price = flt(struck, 2)
		offer.valid_from = _schema_datetime(price.get("valid_from"))
		until = _schema_datetime(price.get("valid_upto"))
		# a date gone by makes Google drop the listing: only a sale still running has an end
		if until and getdate(price.get("valid_upto")) >= getdate(now_datetime()):
			offer.valid_until = until
	return offer


def rating_facts(context) -> frappe._dict | None:
	"""The average the reviews block prints (on 5) and the number of reviews, when it prints one."""
	settings = context.shopping_cart.cart_settings
	total = cint(context.get("total_reviews"))
	if not settings.get("enable_reviews") or total <= 0:
		return None
	average = flt(context.get("average_rating"), 1)
	if average <= 0:
		return None
	return frappe._dict(value=average, count=total)


def review_facts(context) -> list[frappe._dict]:
	"""The reviews the page shows: author, rating on 5, date, title and text."""
	settings = context.shopping_cart.cart_settings
	if not settings.get("enable_reviews"):
		return []
	reviews = []
	for review in (context.get("reviews") or [])[:MAX_REVIEWS]:
		rating = flt(review.get("rating"))
		# the Rating field stores 0..1; the page prints it on 5 (macros.html)
		rating = rating * 5 if rating <= 1 else rating
		author = (review.get("customer") or "").strip()
		if not author or rating <= 0:
			continue
		company = frappe.get_cached_value("Customer", author, "customer_type") == "Company"
		reviews.append(
			frappe._dict(
				author=author,
				author_type="Organization" if company else "Person",
				rating=round(rating),
				date=str(getdate(review.get("creation"))) if review.get("creation") else "",
				title=(review.get("review_title") or "").strip(),
				text=html_to_text(review.get("comment") or "", 1000),
			)
		)
	return reviews


def video_facts(doc) -> list[frappe._dict]:
	"""The videos of the gallery that Google can describe: it requires a name, a thumbnail and
	an upload date, and a way to play them (a file, or the platform's player)."""
	from webshop.webshop.utils.videos import video_info

	videos = []
	for row in doc.get("videos") or []:
		info = video_info(row.as_dict() if hasattr(row, "as_dict") else row)
		if not info or not info.poster:
			continue
		video = frappe._dict(
			name=info.title or doc.web_item_name,
			thumbnail=absolute_url(info.poster),
			uploaded=str(getdate(row.get("creation"))) if row.get("creation") else "",
		)
		if not video.uploaded:
			continue
		if info.kind == "file":
			video.content_url = absolute_url(info.src)
		else:
			video.embed_url = info.embed.split("?")[0]
		videos.append(video)
	return videos


def absolute_url(path: str) -> str:
	"""A file of this site as an address on the domain being browsed, spaces and accents
	escaped (a file name as uploaded is not a URL)."""
	from urllib.parse import quote

	from webshop.webshop.multi_site import site_url

	if path.startswith(("http://", "https://")):
		return path
	return site_url(quote(path, safe="/%?=&:+~"))


def _schema_datetime(value) -> str | None:
	"""A Pricing Rule's date as ISO 8601 with the site's time zone, as Google asks of a sale."""
	if not value:
		return None
	try:
		moment = datetime.fromisoformat(str(value))
	except ValueError:
		return None
	from zoneinfo import ZoneInfo

	from frappe.utils import get_system_timezone

	return moment.replace(tzinfo=ZoneInfo(get_system_timezone())).isoformat()
