# //// Neoffice — added file (no upstream equivalent): a model's variants as its page sells them,
# //// read by the variant selector, the page's ProductGroup and the Merchant Center feed.
# //// neoffice-maintenance#691, decision D-1 of the SEO plan, 2026-09-25.
"""A model and its variants: one page, one ProductGroup (decision D-1 of the SEO plan).

A model (a template item with variants) is sold on its own page, where the variant selector picks
the colour and the size, and `?variant=<item code>` opens that page on one variant: its price, its
stock and its picture come from the server. Google reads the page as one ProductGroup whose
variants each carry their own offer.
- The model's page is the canonical one.
- A variant's own page stays online, because carts, wishlists and emails link it. It names the
  model's page as canonical, carries the same group, and leaves the sitemap.
- The feed sends each variant to `model?variant=`.

This holds only where the model's page sells. With Webshop Settings' variant selector
(enable_variants) off, the model's page offers nothing to choose: each variant is bought on its
own page, and each stays a product of its own.

The rows below are the ones the selector draws, the structured data declares and the feed sends:
the prices this visitor would pay (product_info.variant_prices) and the stock by the shop's rule
(availability.bulk_availability). One reading, so the three never disagree about a variant.
"""

from urllib.parse import quote

import frappe
from frappe.utils import cint

# Declared in one ProductGroup: past that, the page's markup outweighs the page. The feed carries
# every variant anyway.
MAX_VARIANTS = 100
PARAMETER = "variant"

# A variant attribute as schema.org names it (variesBy, and the property on each variant), keyed
# by the Google attribute the feed maps the shop's attribute names to (feeds/google.py). An
# attribute schema.org has no property for is declared as an additionalProperty.
SCHEMA_PROPERTIES = {
	"color": "color",
	"size": "size",
	"material": "material",
	"pattern": "pattern",
	"gender": "suggestedGender",
}


def sells_on_model_page(cart_settings=None) -> bool:
	"""Whether a model's page offers its variants (Webshop Settings' variant selector)."""
	if cart_settings is None:
		from webshop.webshop.doctype.webshop_settings.webshop_settings import get_shopping_cart_settings

		cart_settings = get_shopping_cart_settings()
	return bool(cint(cart_settings.get("enable_variants")))


def group_model(doc, cart_settings=None) -> str | None:
	"""The model whose ProductGroup a product page carries: the page's own item when it is a
	model, the model of a variant whose model's page is published on this site; None otherwise."""
	if not sells_on_model_page(cart_settings):
		return None
	if cint(doc.get("has_variants")):
		return doc.item_code
	model = doc.get("variant_of")
	if not model:
		return None
	return model if model_page_name(model) else None


def model_page_name(model_code) -> str | None:
	"""The model's published Website Item on this site, by name, or None."""
	from webshop.webshop.multi_site import excluded_item_names

	name = frappe.db.get_value("Website Item", {"item_code": model_code, "published": 1}, "name")
	if not name or name in (excluded_item_names() or []):
		return None
	return name


def variant_link(model_url: str, item_code: str) -> str:
	"""The model's page opened on one variant."""
	return f"{model_url}?{PARAMETER}={quote(item_code, safe='')}"


def model_attributes(model_code) -> list[str]:
	"""The model's attributes in the model's own order (colour, then size)."""
	return frappe.get_all(
		"Item Variant Attribute",
		filters={"parent": model_code, "parenttype": "Item"},
		pluck="attribute",
		order_by="idx asc",
	)


def variant_label(model_name: str, values) -> str:
	"""A variant's name, as Google wants it: the model's, made precise ("Coastline tee – Grey, XL")."""
	chosen = ", ".join(str(value) for _attribute, value in values if value)
	return f"{model_name} – {chosen}" if chosen else model_name


def offered_variants(model_code, cart_settings=None, limit=MAX_VARIANTS) -> list[frappe._dict]:
	"""The model's variants a customer can see on this site (enabled, published, not sold, not
	reserved to another site of the instance), in item code order. Each row carries:
	- its attribute values, in the model's order, as `choices` (a frappe._dict's `values` is dict.values);
	- the price this visitor is charged (None when the page shows this visitor no price);
	- its availability, with the quantity the shop may promise (None when it does not count)."""
	from webshop.webshop.multi_site import excluded_item_names
	from webshop.webshop.seo.availability import bulk_availability
	from webshop.webshop.shopping_cart.product_info import variant_prices

	if cart_settings is None:
		from webshop.webshop.doctype.webshop_settings.webshop_settings import get_shopping_cart_settings

		cart_settings = get_shopping_cart_settings()
	excluded = set(excluded_item_names() or [])
	enabled = set(frappe.get_all("Item", filters={"variant_of": model_code, "disabled": 0}, pluck="name"))
	pages = [
		page
		for page in frappe.get_all(
			"Website Item",
			filters={"variant_of": model_code, "published": 1, "sold": 0},
			fields=["name", "item_code", "route", "website_image", "item_condition"],
			order_by="item_code asc",
		)
		if page.item_code in enabled and page.name not in excluded
	][:limit]
	if not pages:
		return []
	codes = [page.item_code for page in pages]
	order = model_attributes(model_code)
	values = {}
	for row in frappe.get_all(
		"Item Variant Attribute",
		filters={"parent": ["in", codes], "parenttype": "Item"},
		fields=["parent", "attribute", "attribute_value"],
	):
		values.setdefault(row.parent, {})[row.attribute] = row.attribute_value
	prices = variant_prices(model_code, cart_settings)
	stock = bulk_availability(codes, cart_settings)
	rows = []
	for page in pages:
		attributes = values.get(page.item_code) or {}
		price = (prices or {}).get(page.item_code)
		rows.append(
			frappe._dict(
				item_code=page.item_code,
				route=page.route,
				image=page.website_image,
				condition=page.item_condition,
				choices=[(attribute, attributes[attribute]) for attribute in order if attributes.get(attribute)],
				price=frappe._dict(price) if price else None,
				availability=stock[page.item_code].availability,
				qty=stock[page.item_code].qty,
			)
		)
	return rows


def schema_attributes(values, mapping) -> tuple[dict, list[tuple[str, str]]]:
	"""A variant's attribute values as schema.org properties ({"color": "Grey", "size": "XL"}),
	and those schema.org has no property for, as (name, value) pairs."""
	properties, others = {}, []
	for attribute, value in values:
		google = mapping.get((attribute or "").strip().lower())
		schema = SCHEMA_PROPERTIES.get(google)
		if schema and schema not in properties:
			properties[schema] = str(value)
		else:
			others.append((attribute, str(value)))
	return properties, others


def price_display(price) -> dict:
	"""A variant's price row as the selector's footer prints it: the price, and the list price
	struck through with the discount when a rule lowered it. The shop's own formatter, the one
	its cards use (currency symbol shown or hidden by Webshop Settings)."""
	from frappe.utils import flt

	from webshop.webshop.utils.utils import format_currency_value

	if not price:
		return {}
	rate, mrp, currency = flt(price.get("price")), flt(price.get("mrp")), price.get("currency")
	shown = {
		"price_list_rate": rate,
		"currency": currency,
		"formatted_price": format_currency_value(rate, currency=currency),
	}
	if mrp > rate > 0:
		shown["formatted_mrp"] = format_currency_value(mrp, currency=currency)
		shown["discount_percent"] = int(round((mrp - rate) / mrp * 100))
	return shown


def chosen_variant(rows, item_code, cart_settings) -> frappe._dict | None:
	"""The variant `?variant=` names, among those the page sells, as the selector's footer shows
	it once chosen: printed by the server, so a crawler that runs no script (Google Shopping's
	checks of a landing page) reads the variant's price and stock on the address the feed gives."""
	from webshop.webshop.seo.availability import BACK_ORDER, OUT_OF_STOCK

	if not item_code:
		return None
	row = next((row for row in rows or [] if row.item_code == item_code), None)
	if not row:
		return None
	chosen = frappe._dict(
		item_code=row.item_code,
		image=row.image,
		label=" · ".join(str(value) for _attribute, value in row.choices),
		choices=row.choices,
		price=price_display(row.price),
		in_stock=row.availability != OUT_OF_STOCK,
		backorder=row.availability == BACK_ORDER,
		few_left=None,
	)
	if cint(cart_settings.get("show_stock_availability")) and row.qty and 0 < row.qty < 10:
		chosen.few_left = int(row.qty) if float(row.qty).is_integer() else row.qty
	return chosen


def model_view(model_code, cart_settings) -> frappe._dict | None:
	"""What a model's page shows the current visitor of its variants, for the feed:
	- the page's address;
	- its gallery;
	- the rows of offered_variants, by item code.
	None when the model's page does not sell them. Kept for the job or the request: the feed asks
	for every variant of a model in turn."""
	from frappe.website.doctype.website_slideshow.website_slideshow import get_slideshow

	from webshop.webshop.multi_site import get_current_profile_name, site_url
	from webshop.webshop.seo.facts import absolute_url, gallery_images

	memo = getattr(frappe.local, "webshop_model_views", None)
	if memo is None:
		memo = frappe.local.webshop_model_views = {}
	key = (get_current_profile_name(), frappe.session.user, model_code)
	if key not in memo:
		view = None
		name = model_page_name(model_code) if sells_on_model_page(cart_settings) else None
		if name:
			model = frappe.get_cached_doc("Website Item", name)
			context = frappe._dict(get_slideshow(model)) if model.slideshow else frappe._dict()
			view = frappe._dict(
				url=site_url(model.route),
				item_condition=model.get("item_condition"),
				images=[absolute_url(image) for image in gallery_images(model, context)],
				rows={row.item_code: row for row in offered_variants(model_code, cart_settings)},
			)
		memo[key] = view
	return memo[key]


def selector_data(item_code: str) -> dict:
	"""What the variant selector draws (item_configure_grid.js, webshop.webshop.api.
	get_all_variants_info): every enabled variant of a model this site publishes with its
	attribute values, and for those the page sells their picture, their stock by the shop's rule
	and the price this visitor pays, only where the page shows this visitor prices."""
	from frappe.utils import flt

	from webshop.webshop.doctype.webshop_settings.webshop_settings import get_shopping_cart_settings
	from webshop.webshop.seo.availability import BACK_ORDER, OUT_OF_STOCK
	from webshop.webshop.utils.utils import format_currency_value

	# a model this site publishes, and nothing else
	if not frappe.db.get_value("Item", item_code, "has_variants") or not model_page_name(item_code):
		return {"variants": []}

	# Get all variants
	variants = frappe.get_all(
		"Item",
		filters={"variant_of": item_code, "disabled": 0},
		fields=["name", "item_code", "item_name"],
		order_by="name asc",
	)

	if not variants:
		return {"variants": []}

	# Get variant attributes
	variant_attributes = frappe.get_all(
		"Item Variant Attribute",
		filters={"parent": item_code},
		fields=["attribute"],
		order_by="idx"
	)

	cart_settings = get_shopping_cart_settings()
	# the variants the page sells, priced for this visitor and stocked by the shop's rule
	offered = {row.item_code: row for row in offered_variants(item_code, cart_settings)}
	show_qty = cint(cart_settings.show_stock_availability)
	# each variant's EAN and manufacturer's reference, which the page's characteristics follow
	# (#691 plan note 20, B2): the structured data already declares them, nothing new is told
	codes = {}
	if offered and cint(cart_settings.get("show_product_identifiers")):
		from webshop.webshop.seo.facts import bulk_identifiers, identifier_rows

		codes = {code: identifier_rows(found) for code, found in bulk_identifiers(list(offered)).items()}
	values = {}
	for row in frappe.get_all(
		"Item Variant Attribute",
		filters={"parent": ["in", [variant.name for variant in variants]], "parenttype": "Item"},
		fields=["parent", "attribute", "attribute_value"],
	):
		values.setdefault(row.parent, {})[row.attribute] = row.attribute_value

	# Build variant data
	variants_data = []
	rates = []
	currency = None

	for variant in variants:
		offer = offered.get(variant.item_code)
		variant_data = {
			"item_code": variant.item_code,
			"item_name": variant.item_name,
			"attributes": values.get(variant.item_code) or {},
			"in_stock": False,
			"stock_qty": 0,
			"exists": True,
			"website_item": bool(offer),
		}
		if offer:
			variant_data["image"] = offer.image
			variant_data["codes"] = codes.get(variant.item_code) or []
			variant_data["in_stock"] = offer.availability != OUT_OF_STOCK
			variant_data["backorder"] = offer.availability == BACK_ORDER
			# the quantity only where the shop shows its stock
			variant_data["stock_qty"] = offer.qty if show_qty else None
			if offer.price:
				variant_data["price"] = price_display(offer.price)
				rates.append(flt(offer.price.price))
				currency = currency or offer.price.currency
		variants_data.append(variant_data)

	# Build price range
	price_range = None
	if rates:
		price_min, price_max = min(rates), max(rates)
		if price_min == price_max:
			price_range = {
				"min": price_min,
				"max": price_max,
				"formatted": format_currency_value(price_min, currency=currency)
			}
		else:
			price_range = {
				"min": price_min,
				"max": price_max,
				"formatted": f"{format_currency_value(price_min, currency=currency)} - {format_currency_value(price_max, currency=currency)}"
			}

	# the values of each attribute in the attribute's own order (S, M, L, XL — not alphabetical),
	# for the rows of chips the page draws (2026-09-13)
	attribute_values = {}
	for attr in variant_attributes:
		attribute_values[attr.attribute] = frappe.get_all(
			"Item Attribute Value", filters={"parent": attr.attribute}, pluck="attribute_value", order_by="idx asc"
		)
		if frappe.db.get_value("Item Attribute", attr.attribute, "numeric_values"):
			present = sorted({v["attributes"].get(attr.attribute) for v in variants_data if v["attributes"].get(attr.attribute)}, key=lambda x: float(x))
			attribute_values[attr.attribute] = present

	return {
		"variants": variants_data,
		"attribute_values": attribute_values,
		"attributes": variant_attributes,
		"price_range": price_range,
		# whether the page shows this visitor prices: the footer then says nothing
		"show_prices": bool(cart_settings.show_price) and not (frappe.session.user == "Guest" and cart_settings.hide_price_for_guest),
	}
