# //// Neoffice — added file (no upstream equivalent). Every product page the catalogue shows on
# //// this site, with its pictures; the list is built in webshop/webshop/seo/sitemaps.py
# //// (2026-09-24: the scope of the listing, a lastmod that counts price changes, no
# //// changefreq/priority, which Google ignores).
from webshop.webshop.seo.sitemaps import product_links

no_cache = 1
base_template_path = "www/sitemap_products.xml"


def get_context(context):
	return {"links": product_links()}
