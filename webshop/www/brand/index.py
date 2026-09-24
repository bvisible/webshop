# //// Neoffice — added file (no upstream equivalent): a brand's page, /brands/<slug> (hooks.py
# //// website_route_rules; product_data_engine/brand_pages.py). neoffice-maintenance#691, lot 2.
"""The catalogue with its brand locked, under the brand's logo and text. A brand with nothing this
site shows has no page: its address does not exist."""

import frappe

from webshop.webshop.product_data_engine.brand_pages import brand_of_slug, brand_route
from webshop.webshop.product_data_engine.listing_context import build_listing_context
from webshop.webshop.seo.site import shop_name
from webshop.webshop.seo.text import one_line

no_cache = 1
# Google cuts a longer description in its results
DESCRIPTION_LIMIT = 160


def get_context(context):
	brand = brand_of_slug(frappe.form_dict.get("brand_slug"))
	if not brand:
		raise frappe.PageDoesNotExistError
	build_listing_context(
		context, brand, locked_field_filters={"brand": [brand]}, listing_route="/" + brand_route(brand)
	)
	record = frappe.db.get_value("Brand", brand, ["image", "description"], as_dict=True) or frappe._dict()
	context.brand = frappe._dict(name=brand, image=record.image, description=(record.description or "").strip())
	# the heading and the breadcrumb say the brand; the browser tab and Google's title add the shop
	name = shop_name()
	context.html_title = f"{brand} | {name}" if name else brand
	if context.brand.description:
		context.metatags["description"] = one_line(context.brand.description, DESCRIPTION_LIMIT)
	if record.image:
		context.metatags["image"] = record.image
	return context
