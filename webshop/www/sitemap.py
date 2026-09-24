# //// Neoffice — added file (no upstream equivalent; it replaces Frappe's /sitemap.xml, which
# //// lists Website Route Meta only). Since 2026-09-24 it is the sitemap INDEX: /sitemap.xml is
# //// the address every tool tries first and the one a hand-written robots.txt names, and it
# //// used to list no product at all (neoffice-maintenance#691, D9). The lists themselves are
# //// built in webshop/webshop/seo/sitemaps.py.
from webshop.webshop.seo.sitemaps import index_entries

no_cache = 1
base_template_path = "www/sitemap.xml"


def get_context(context):
	return {"sitemaps": index_entries()}
