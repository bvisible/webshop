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

import frappe
from frappe.utils import cint, flt

SCHEMA = "https://schema.org/"


def product_graph(facts: frappe._dict) -> dict:
	"""The product page's graph: the Product, its Offer, its rating, reviews and videos."""
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


def offer_node(offer: frappe._dict) -> dict:
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
	seller = seller_node()
	if seller:
		node["seller"] = seller
	policies = site_policies()
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
	return frappe._dict(
		returns=cint(settings.get("return_days")) > 0,
		shipping=flt(settings.get("free_shipping_from")) > 0,
		return_days=cint(settings.get("return_days")),
		free_shipping_from=flt(settings.get("free_shipping_from")),
	)
