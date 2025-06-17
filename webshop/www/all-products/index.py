import frappe
from frappe.utils import cint

from webshop.webshop.product_data_engine.filters import ProductFiltersBuilder

sitemap = 1


def get_context(context):
	# Add homepage as parent
	context.body_class = "product-page"
	context.parents = [{"name": frappe._("Home"), "route": "/"}]

	filter_engine = ProductFiltersBuilder()
	context.field_filters = filter_engine.get_field_filters()
	context.attribute_filters = filter_engine.get_attribute_filters()
	
	# Add tag filters if enabled
	if frappe.db.get_single_value("Webshop Settings", "enable_tag_filters"):
		context.tag_filters = filter_engine.get_tag_filters()
		
	# Add price filters if enabled
	enable_price_filter = frappe.db.get_single_value("Webshop Settings", "enable_price_filter")
	
	if enable_price_filter:
		price_filters = filter_engine.get_price_filters()
		# Avoid logging the entire price filters array which is too long
		context.price_filters = price_filters

	# Add product settings for sort order
	context.product_settings = {
		"default_product_sort": frappe.db.get_single_value("Webshop Settings", "default_product_sort") or "relevance"
	}
	
	context.page_length = (
		cint(frappe.db.get_single_value("Webshop Settings", "products_per_page")) or 20
	)
	
	# Add stock filter settings
	context.enable_stock_filter = bool(frappe.db.get_single_value("Webshop Settings", "enable_stock_filter"))
	context.stock_filter_default_checked = bool(frappe.db.get_single_value("Webshop Settings", "stock_filter_default_checked"))

	context.no_cache = 1

	from webshop.webshop.shopping_cart.guest_cart import check_and_merge_guest_cart

	# Check and merge guest cart if needed
	check_and_merge_guest_cart()