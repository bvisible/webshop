# //// Neoffice — added file (no upstream equivalent). Empty on purpose since 2026-09-24: it listed
# //// the catalogue filtered on each brand (/all-products?field_filters=…) for every brand of the
# //// instance, used or not, of this site or not. A filtered catalogue is not a page: it has no
# //// canonical of its own and robots.txt keeps crawlers out of it (neoffice-maintenance#691,
# //// D11). The address stays, empty, until the shop has real brand pages (lot 2 of the plan).
no_cache = 1
base_template_path = "www/sitemap_brands.xml"


def get_context(context):
	return {"links": []}
