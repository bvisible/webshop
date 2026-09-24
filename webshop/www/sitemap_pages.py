# //// Neoffice — added file (no upstream equivalent). The site's own pages: the Builder pages
# //// this site serves (not those of the other site of the instance), Web Pages, the shop's
# //// listings, contact and about. The home page is listed as the site root. Built in
# //// webshop/webshop/seo/sitemaps.py (2026-09-24).
from webshop.webshop.seo.sitemaps import page_links

no_cache = 1
base_template_path = "www/sitemap_pages.xml"


def get_context(context):
	return {"links": page_links()}
