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
	#//// Themes print context.title as the visible page heading and as the
	#//// last breadcrumb, and Frappe defaults it to the route name —
	#//// untranslated. A French shop read "all-products" on screen while its
	#//// browser tab said the translated title.
	context.title = title
	context.body_class = "product-page"
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
	context.no_cache = 1

	from webshop.webshop.shopping_cart.guest_cart import check_and_merge_guest_cart

	check_and_merge_guest_cart()
	return context
