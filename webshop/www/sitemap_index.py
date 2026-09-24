# //// Neoffice — added file (no upstream equivalent). The sitemap index, also served at
# //// /sitemap.xml since 2026-09-24; this address stays for the tools that were given it. The
# //// index carries no <lastmod>: it used to print today's date for every sitemap, and Google
# //// stops trusting a lastmod that is not true (neoffice-maintenance#691, D13).
from webshop.webshop.seo.sitemaps import index_entries

no_cache = 1
base_template_path = "www/sitemap_index.xml"


def get_context(context):
	return {"sitemaps": index_entries()}
