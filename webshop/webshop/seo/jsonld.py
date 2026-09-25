# //// Neoffice — added file (no upstream equivalent): the structured data of the shop's pages,
# //// built from seo/facts.py. neoffice-maintenance#691 (lot 1, D8), 2026-09-24.
"""JSON-LD: what Google's merchant listings, and every other engine, read of a page.

One graph per page, tied by @id. A product page describes one Product with one Offer —
never an AggregateOffer where the product is bought — and a list is never a Product.

The policies every offer follows (returns, shipping) are the shop's, not the product's:
Google wants them declared once, on the organisation, and each offer pointing at them by
@id. The site chrome declares the organisation on the home page (builder's site graph) and
asks this module for the shop's share of it (`site_organization`).
"""

import re

import frappe
from frappe.utils import cint, flt, getdate, nowdate

SCHEMA = "https://schema.org/"
# The Swiss business identification number, as the registry writes it (with or without "TVA").
SWISS_UID = re.compile(r"^CHE-\d{3}\.\d{3}\.\d{3}( (TVA|MWST|IVA|VAT))?$")
# "1950 Sion", "CH-1950 Sion", "75001 Paris": a postcode then the locality.
POSTCODE_LINE = re.compile(r"^(?:[A-Z]{1,2}-)?(\d{4,5})\s+(.+)$")
# A year of closures at most: holidays are fetched a year ahead.
MAX_CLOSURES = 40


def product_graph(facts: frappe._dict) -> dict:
	"""The product page's graph: the Product, its Offer, its rating, reviews and videos; or, on a
	model's page and its variants' pages, the model's ProductGroup (product_group_graph)."""
	if facts.group:
		return product_group_graph(facts.group)
	node = {
		"@context": "https://schema.org",
		"@type": "Product",
		"@id": facts.url + "#product",
		"name": facts.name,
		"url": facts.url,
	}
	if facts.sku:
		node["sku"] = facts.sku
	node.update(facts.identifiers or {})
	if facts.brand:
		node["brand"] = {"@type": "Brand", "name": facts.brand}
	if facts.description:
		node["description"] = facts.description
	if facts.images:
		node["image"] = facts.images
	if facts.category:
		node["category"] = facts.category
	if facts.properties:
		node["additionalProperty"] = [
			{"@type": "PropertyValue", "name": name, "value": value} for name, value in facts.properties
		]
	if facts.offer:
		node["offers"] = offer_node(facts.offer)
	if facts.rating:
		node["aggregateRating"] = {
			"@type": "AggregateRating",
			"ratingValue": facts.rating.value,
			"reviewCount": facts.rating.count,
			"bestRating": 5,
			"worstRating": 1,
		}
	if facts.reviews:
		node["review"] = [review_node(review) for review in facts.reviews]
	if facts.videos:
		node["subjectOf"] = [video_node(video) for video in facts.videos]
	return node


def product_group_graph(group: frappe._dict) -> dict:
	"""A model's page: one ProductGroup, one Product per variant with its own offer (Google's
	single-page variant markup, 2024-02-20). The markup does not change with the variant chosen:
	each variant's offer names the page opened on it (`?variant=`), and the group names the page."""
	node = {
		"@context": "https://schema.org",
		"@type": "ProductGroup",
		"@id": group.url + "#product",
		"name": group.name,
		"url": group.url,
		"productGroupID": group.group_id,
	}
	if group.brand:
		node["brand"] = {"@type": "Brand", "name": group.brand}
	if group.description:
		node["description"] = group.description
	if group.images:
		node["image"] = group.images
	if group.category:
		node["category"] = group.category
	if group.properties:
		node["additionalProperty"] = [
			{"@type": "PropertyValue", "name": name, "value": value} for name, value in group.properties
		]
	if group.varies_by:
		node["variesBy"] = [SCHEMA + name for name in group.varies_by]
	# the shop's seller and policies, read once for every variant's offer
	seller, policies = seller_node(), site_policies()
	node["hasVariant"] = [variant_node(variant, seller, policies) for variant in group.variants]
	if group.rating:
		node["aggregateRating"] = {
			"@type": "AggregateRating",
			"ratingValue": group.rating.value,
			"reviewCount": group.rating.count,
			"bestRating": 5,
			"worstRating": 1,
		}
	if group.reviews:
		node["review"] = [review_node(review) for review in group.reviews]
	if group.videos:
		node["subjectOf"] = [video_node(video) for video in group.videos]
	return node


def variant_node(variant: frappe._dict, seller=None, policies=None) -> dict:
	"""One variant of a ProductGroup: a Product more precisely named than the model, its
	attributes as schema.org properties (color, size...), its offer."""
	node = {"@type": "Product", "name": variant.name, "sku": variant.sku}
	node.update(variant.identifiers or {})
	if variant.image:
		node["image"] = variant.image
	node.update(variant.properties or {})
	if variant.others:
		node["additionalProperty"] = [
			{"@type": "PropertyValue", "name": name, "value": value} for name, value in variant.others
		]
	if variant.offer:
		node["offers"] = offer_node(variant.offer, seller, policies)
	return node


def offer_node(offer: frappe._dict, seller=None, policies=None) -> dict:
	node = {
		"@type": "Offer",
		"url": offer.url,
		"price": offer.price,
		"priceCurrency": offer.currency,
		"availability": offer.availability,
		"itemCondition": offer.condition,
	}
	if offer.struck_price:
		# Google reads the active price as a sale price once a struck price is given; the
		# active price itself carries no priceType.
		node["priceSpecification"] = {
			"@type": "UnitPriceSpecification",
			"priceType": SCHEMA + "StrikethroughPrice",
			"price": offer.struck_price,
			"priceCurrency": offer.currency,
		}
		if offer.valid_from:
			node["validFrom"] = offer.valid_from
		if offer.valid_until:
			node["priceValidUntil"] = offer.valid_until
	seller = seller or seller_node()
	if seller:
		node["seller"] = seller
	policies = policies or site_policies()
	if policies.returns:
		node["hasMerchantReturnPolicy"] = {"@id": policy_id("returns")}
	if policies.shipping:
		node["shippingDetails"] = {
			"@type": "OfferShippingDetails",
			"hasShippingService": {"@id": policy_id("shipping")},
		}
	return node


def review_node(review: frappe._dict) -> dict:
	node = {
		"@type": "Review",
		"author": {"@type": review.author_type or "Person", "name": review.author},
		"reviewRating": {"@type": "Rating", "ratingValue": review.rating, "bestRating": 5, "worstRating": 1},
	}
	if review.date:
		node["datePublished"] = review.date
	if review.title:
		node["name"] = review.title
	if review.text:
		node["reviewBody"] = review.text
	return node


def video_node(video: frappe._dict) -> dict:
	node = {
		"@type": "VideoObject",
		"name": video.name,
		"description": video.name,
		"thumbnailUrl": video.thumbnail,
		"uploadDate": video.uploaded,
	}
	if video.content_url:
		node["contentUrl"] = video.content_url
	if video.embed_url:
		node["embedUrl"] = video.embed_url
	return node


def organization_id() -> str:
	from webshop.webshop.multi_site import site_url

	return site_url("/#organization")


def policy_id(kind: str) -> str:
	from webshop.webshop.multi_site import site_url

	return site_url(f"/#{kind}")


def seller_node() -> dict | None:
	from webshop.webshop.seo.site import shop_name

	name = shop_name()
	return {"@type": "Organization", "@id": organization_id(), "name": name} if name else None


def site_policies(settings=None) -> frappe._dict:
	"""What the shop promises every order, as the product page prints it (utils/promises.py):
	a return window, free delivery from an amount. Nothing is declared that the shop does not
	state — Google suspends a merchant for policies it cannot find on the site."""
	if settings is None:
		from webshop.webshop.doctype.webshop_settings.webshop_settings import get_shopping_cart_settings

		settings = get_shopping_cart_settings()
	# a policy applies somewhere: without the shop's country, nothing can be declared, and an
	# offer must not point at a policy the home page does not declare
	country = shop_country(settings)
	return frappe._dict(
		country=country,
		returns=bool(country) and cint(settings.get("return_days")) > 0,
		shipping=bool(country) and flt(settings.get("free_shipping_from")) > 0,
		return_days=cint(settings.get("return_days")),
		free_shipping_from=flt(settings.get("free_shipping_from")),
	)


def site_organization(organization: dict) -> list[dict] | None:
	"""builder's `site_organization` hook: the shop's share of the Organization the site chrome
	declares on the home page (builder/site_graph.py). An organisation that sells here is an
	OnlineStore, and its offers point at the policies below by @id (offer_node). Returns the
	shop's physical store as a node of its own, when it states its hours and its address."""
	from webshop.webshop.doctype.webshop_settings.webshop_settings import get_shopping_cart_settings

	settings = get_shopping_cart_settings()
	if not settings.get("enabled"):
		return None
	organization["@type"] = "OnlineStore"
	company = settings.get("company")
	if company:
		legal_name, tax_id = frappe.get_cached_value("Company", company, ["company_name", "tax_id"]) or ("", "")
		if legal_name and legal_name != organization.get("name"):
			organization.setdefault("legalName", legal_name)
		# only a Swiss UID, a public registry number, is published as the organisation's VAT id
		if tax_id and SWISS_UID.match(tax_id.strip()):
			organization["vatID"] = tax_id.strip()
	policies = site_policies(settings)
	country = policies.country
	if policies.returns:
		organization["hasMerchantReturnPolicy"] = {
			"@type": "MerchantReturnPolicy",
			"@id": policy_id("returns"),
			"applicableCountry": country,
			"returnPolicyCountry": country,
			"returnPolicyCategory": SCHEMA + "MerchantReturnFiniteReturnWindow",
			"merchantReturnDays": policies.return_days,
		}
	if policies.shipping:
		currency = shop_currency(settings)
		organization["hasShippingService"] = {
			"@type": "ShippingService",
			"@id": policy_id("shipping"),
			"shippingConditions": {
				"@type": "ShippingConditions",
				"shippingDestination": {"@type": "DefinedRegion", "addressCountry": country},
				# free from this amount: what the product page promises, and all it promises
				"orderValue": {"@type": "MonetaryAmount", "minValue": policies.free_shipping_from, "currency": currency},
				"shippingRate": {"@type": "MonetaryAmount", "value": 0, "currency": currency},
			},
		}
	store = store_node(organization, country)
	return [store] if store else None


def store_node(organization: dict, country: str = "") -> dict | None:
	"""The shop's store, as the opening-hours block shows it (utils/store_hours.py): its address,
	its weekly hours and the days it closes, holidays included. Only when the shop states both
	its hours and its address: a store Google cannot place is not one."""
	from webshop.webshop.multi_site import site_url
	from webshop.webshop.utils.store_hours import WEEKDAYS, get_settings, schedule

	settings = get_settings()
	address = (settings.get("store_address") or "").strip()
	sched = schedule(settings)
	if not sched.configured or not address:
		return None
	node = {
		"@type": "Store",
		"@id": site_url("/#store"),
		"name": organization.get("name"),
		"url": site_url("/store-hours"),
		"parentOrganization": {"@id": organization.get("@id")},
		"address": postal_address(address, country),
		"openingHoursSpecification": [
			{
				"@type": "OpeningHoursSpecification",
				"dayOfWeek": SCHEMA + WEEKDAYS[day],
				"opens": opens.strftime("%H:%M"),
				"closes": closes.strftime("%H:%M"),
			}
			for day, periods in sorted(sched.periods.items())
			for opens, closes in periods
		],
	}
	for field, key in (("store_phone", "telephone"), ("store_email", "email")):
		value = (settings.get(field) or "").strip()
		if value:
			node[key] = value
	# a closed day, as Google reads one: opens and closes at 00:00 between two dates
	today = getdate(nowdate())
	closures = [c for c in sched.closures if c.to_date >= today and (c.from_date - today).days <= 366]
	if closures:
		node["specialOpeningHoursSpecification"] = [
			{
				"@type": "OpeningHoursSpecification",
				"validFrom": str(c.from_date),
				"validThrough": str(c.to_date),
				"opens": "00:00",
				"closes": "00:00",
			}
			for c in sorted(closures, key=lambda c: c.from_date)[:MAX_CLOSURES]
		]
	return node


def postal_address(text: str, country: str = "") -> dict:
	"""A store address typed as a customer reads it ("Rue du Rhône 12, 1950 Sion") as a
	PostalAddress: the line carrying the postcode gives the postcode and the locality, the lines
	before it the street."""
	lines = [line.strip(" ,") for line in re.split(r"[\n,]", text) if line.strip(" ,")]
	address = {"@type": "PostalAddress"}
	street = lines
	for index, line in enumerate(lines):
		match = POSTCODE_LINE.match(line)
		if match:
			address["postalCode"], address["addressLocality"] = match.group(1), match.group(2).strip()
			street = lines[:index]
			break
	if street:
		address["streetAddress"] = ", ".join(street)
	if country:
		address["addressCountry"] = country
	return address


def shop_country(settings) -> str:
	"""ISO 3166 code of the shop's company country: where its policies apply."""
	company = settings.get("company")
	country = company and frappe.get_cached_value("Company", company, "country")
	code = country and frappe.get_cached_value("Country", country, "code")
	return (code or "").upper()


def shop_currency(settings) -> str:
	price_list = settings.get("price_list")
	currency = price_list and frappe.get_cached_value("Price List", price_list, "currency")
	return currency or frappe.defaults.get_global_default("currency") or ""
