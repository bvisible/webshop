# //// Neoffice — added file (no upstream equivalent). The brand pages of the site being browsed,
# //// /brands/<slug> (seo/sitemaps.py brand_links; neoffice-maintenance#691, lot 2). It used to list
# //// the catalogue filtered on each brand (/all-products?field_filters=…) for every brand of the
# //// instance, used or not, of this site or not: a filtered catalogue is not a page, and it stayed
# //// empty from 2026-09-24 (D11) until the brands had pages of their own.
from webshop.webshop.seo.sitemaps import brand_links

no_cache = 1
base_template_path = "www/sitemap_brands.xml"


def get_context(context):
	return {"links": brand_links()}
