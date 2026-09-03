from frappe import _

from webshop.webshop.product_data_engine.listing_context import build_listing_context

sitemap = 1


def get_context(context):
	#//// Neoffice — the listing context moved to listing_context.py so that
	#//// /occasions (the second-hand page) builds the very same page.
	build_listing_context(context, _("All Products"))
