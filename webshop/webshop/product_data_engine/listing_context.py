# //// Neoffice — added file (no upstream equivalent). The product listing
# //// context, shared by /all-products and /occasions: one place builds the
# //// facets, the price filters, the settings the listing script reads.

import frappe
from frappe import _
from frappe.utils import cint

from webshop.webshop.product_data_engine.filters import ProductFiltersBuilder


def build_listing_context(context, title, locked_field_filters=None, listing_route="/all-products"):
	"""Fill a listing page context.

	`locked_field_filters` ({fieldname: [values]}) is applied to every query
	the page makes and its facet is taken out of the sidebar: the visitor
	cannot untick it. This is how /occasions is /all-products restricted to
	second-hand units.
	"""
	# //// Themes print context.title as the visible page heading and as the
	# //// last breadcrumb, and Frappe defaults it to the route name —
	# //// untranslated. A French shop read "all-products" on screen while its
	# //// browser tab said the translated title.
	context.title = title
	context.body_class = "product-page"
	# //// Neoffice — "filters in a drawer on every screen" (Webshop Settings, 2026-09-13):
	# //// the page carries a class and the stylesheet turns the sidebar into the phone's
	# //// drawer at every width; the products take the whole width.
	# //// read off the cached document: a site whose schema is a step behind (pulled, not yet
	# //// migrated) must not answer 417 on its catalogue for a display option
	if frappe.get_cached_doc("Webshop Settings").get("filters_in_drawer"):
		context.body_class += " wsp-filters-drawer"
	context.parents = [{"name": _("Home"), "route": "/"}]
	context.listing_route = listing_route
	context.locked_field_filters = locked_field_filters or {}

	filter_engine = ProductFiltersBuilder()
	field_filters = filter_engine.get_field_filters()
	if locked_field_filters:
		field_filters = [f for f in field_filters if f[0].fieldname not in locked_field_filters]
	context.field_filters = field_filters
	context.attribute_filters = filter_engine.get_attribute_filters()

	if frappe.db.get_single_value("Webshop Settings", "enable_tag_filters"):
		context.tag_filters = filter_engine.get_tag_filters()

	if frappe.db.get_single_value("Webshop Settings", "enable_price_filter"):
		context.price_filters = filter_engine.get_price_filters()

	context.product_settings = {
		"default_product_sort": frappe.db.get_single_value("Webshop Settings", "default_product_sort")
		or "relevance"
	}
	context.page_length = cint(frappe.db.get_single_value("Webshop Settings", "products_per_page")) or 20
	context.enable_stock_filter = bool(
		frappe.db.get_single_value("Webshop Settings", "enable_stock_filter")
	)
	context.stock_filter_default_checked = bool(
		frappe.db.get_single_value("Webshop Settings", "stock_filter_default_checked")
	)
	# //// A way into the second-hand page from the catalogue: the theme's menu
	# //// is the shop's own, so the listing itself says when there is
	# //// something used to see.
	# //// (2026-09-13) on every listing: the toggle sits next to the discount one everywhere
	context.second_hand_count = count_second_hand()
	# //// (2026-09-14) the discounted count next to the discount toggle, from a short cache
	context.discount_count = count_discounted()
	# //// (2026-09-14) a quiet way in to the quick order, next to the search box, for whoever may use it
	context.quick_order_url = quick_order_url()
	context.no_cache = 1
	# //// Neoffice — 2026-09-24 (#691, D15): the listings had no canonical and no description,
	# //// and every search, facet and page of them answered as a page of its own. They now say
	# //// what they hold and name one reference address (webshop/webshop/seo/meta.py).
	from webshop.webshop.seo.meta import listing_metatags

	listing_metatags(context, title, listing_route, locked_field_filters)

	from webshop.webshop.shopping_cart.guest_cart import check_and_merge_guest_cart

	check_and_merge_guest_cart()
	return context


# //// Neoffice — powers the catalogue's "See second-hand items (n)" link:
# //// /occasions has no menu entry of its own (the menu is the theme's), so
# //// the listing itself says when there is something used to see
# //// (0227bfd0 "feat(occasion): une section État qui n'avale rien, expliquée, et un chemin depuis le catalogue").
def count_second_hand():
	"""Published second-hand units this site still sells (a sold unit left the catalogue)."""
	from webshop.webshop.multi_site import excluded_item_names
	from webshop.webshop.utils.used_items import SECOND_HAND_CONDITIONS

	names = frappe.get_all(
		"Website Item",
		filters={"published": 1, "sold": 0, "item_condition": ("in", SECOND_HAND_CONDITIONS)},
		pluck="name",
	)
	excluded = set(excluded_item_names())
	return len([n for n in names if n not in excluded])


# //// Neoffice — added (2026-09-14): the figure next to the "discounted only" toggle. The
# //// count itself is one SQL over the listing's joins (query.count_discounted_items); here it
# //// is kept for five minutes per site and price list, and dropped by the Pricing Rule and
# //// Item Price hooks, so a catalogue view never pays the join and the figure never lags a
# //// price change by more than the cache.
DISCOUNT_COUNT_CACHE = "webshop:discount_count"
DISCOUNT_COUNT_TTL = 300


def count_discounted():
	from webshop.webshop.multi_site import effective_price_list, get_current_profile_name
	from webshop.webshop.product_data_engine.query import count_discounted_items

	key = f"{DISCOUNT_COUNT_CACHE}:{get_current_profile_name() or ''}:{effective_price_list() or ''}"
	cached = frappe.cache().get_value(key)
	if cached is not None:
		return cint(cached)
	try:
		count = count_discounted_items()
	except Exception:
		frappe.log_error("Discount count failed", frappe.get_traceback())
		return 0
	frappe.cache().set_value(key, count, expires_in_sec=DISCOUNT_COUNT_TTL)
	return count


def clear_discount_count():
	"""Every site's and every price list's figure at once: a rule or a price changed."""
	frappe.cache().delete_keys(DISCOUNT_COUNT_CACHE)



# //// Neoffice — added (2026-09-14): the quick order is offered from the catalogue, next to the
# //// search box, to whoever may fill a cart here (quick_order.api.quick_order_offered).
def quick_order_url():
	from webshop.webshop.quick_order.api import quick_order_offered

	try:
		return "/quick-order" if quick_order_offered() else ""
	except Exception:
		return ""
