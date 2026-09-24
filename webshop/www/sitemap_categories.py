# //// Neoffice — added file (no upstream equivalent). The category pages that hold something on
# //// this site — the groups /shop-by-category shows, not every group flagged for the website
# //// (2026-09-24, neoffice-maintenance#691, D12). Built in webshop/webshop/seo/sitemaps.py.
from webshop.webshop.seo.sitemaps import category_links

no_cache = 1
base_template_path = "www/sitemap_categories.xml"


def get_context(context):
	return {"links": category_links()}
