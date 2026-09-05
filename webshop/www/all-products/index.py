# //// Neoffice — _ imported for the page title (d579b1c02a, 2025-12-14).
from frappe import _

# //// Neoffice — the listing context is built by a shared helper: the category page, the
# //// /occasions page and this one must offer the same facets and the same paging, and
# //// they had drifted (listing_context.py; 8a593a948a, 2026-07-08 for the multi-site
# //// scoping).
from webshop.webshop.product_data_engine.listing_context import build_listing_context

sitemap = 1


def get_context(context):
	# //// Neoffice — the listing context moved to listing_context.py so that
	# //// /occasions (the second-hand page) builds the very same page.
	build_listing_context(context, _("All Products"))
