from . import __version__ as _version

app_name = "webshop"
app_title = "Webshop"
app_publisher = "Frappe Technologies Pvt. Ltd."
app_description = "Open Source eCommerce Platform"
app_email = "contact@frappe.io"
app_license = "GNU General Public License (v3)"
app_version = _version

required_apps = ["payments", "erpnext"]

web_include_css = "webshop-web.bundle.css"

web_include_js = "web.bundle.js"

after_install = "webshop.setup.install.after_install"
after_migrate = "webshop.setup.install.after_migrate"
after_clear_cache = "webshop.webshop.redisearch_utils.rebuild_index_after_clear_cache"
on_logout = "webshop.webshop.shopping_cart.utils.clear_cart_count"
on_session_creation = [
	"webshop.webshop.utils.portal.update_debtors_account",
	"webshop.webshop.shopping_cart.utils.set_cart_count",
]

website_redirects = [
	{"source": "/home", "target": "/"},
	{"source": "/homepage", "target": "/"},
	{"source": "/navbar", "target": "/"},
	{"source": "/footer", "target": "/"},
	{"source": "/all-item-groups", "target": "/all-products"}
]

update_website_context = [
	"webshop.webshop.shopping_cart.utils.update_website_context",
	"webshop.webshop.maintenance_context.inject_maintenance_css",
]

# Scheduled Tasks
scheduler_events = {
	"daily": [
		"webshop.webshop.utils.frequently_bought_together.calculate_frequently_bought_together"
	],
	#//// Neoffice — abandoned carts: one look per hour at the carts left behind
	"hourly": ["webshop.webshop.utils.abandoned_carts.send_abandoned_cart_reminders"],
	#//// Neoffice — purchase follow-ups go out in the morning, not at midnight
	"cron": {"15 8 * * *": ["webshop.webshop.utils.follow_ups.send_due_follow_ups"]},
}

#//// Neoffice — follow-ups and cart reminders show under the customer's
#//// connections, next to its orders.
override_doctype_dashboards = {
	"Customer": "webshop.webshop.utils.follow_ups.customer_dashboard",
	"Sales Order": "webshop.webshop.utils.follow_ups.sales_order_dashboard",
	"Sales Invoice": "webshop.webshop.utils.follow_ups.sales_invoice_dashboard",
	"Quotation": "webshop.webshop.utils.follow_ups.quotation_dashboard",
}

website_generators = ["Website Item", "Item Group"]

override_doctype_class = {
	"Payment Request": "webshop.webshop.doctype.override_doctype.payment_request.PaymentRequest",
	"Item Group": "webshop.webshop.doctype.override_doctype.item_group.WebshopItemGroup",
	"Item": "webshop.webshop.doctype.override_doctype.item.WebshopItem",
	"Sales Invoice": "webshop.webshop.doctype.override_doctype.sales_invoice.SalesInvoice"
}

doctype_js = {
	"Item": "public/js/override/item.js",
	"Item Group": "public/js/override/cross_sell_trigger.js",
	"Brand": "public/js/override/cross_sell_trigger.js",
	"Homepage": "public/js/override/homepage.js",
	"Coupon Code": "public/js/coupon_code.js"
}

doc_events = {
	"Item": {
		"on_update": [
			"webshop.webshop.crud_events.item.update_website_item.execute",
			"webshop.webshop.crud_events.item.invalidate_item_variants_cache.execute",
		],
		"before_rename": [
			"webshop.webshop.crud_events.item.validate_duplicate_website_item.execute",
		],
		"after_rename": [
			"webshop.webshop.crud_events.item.invalidate_item_variants_cache.execute",
		],
	},
	"Product Bundle": {
		"on_update": [
			"webshop.webshop.crud_events.product_bundle.invalidate_bundle_cache.execute",
		],
	},
	"Sales Taxes and Charges Template": {
		"on_update": [
			"webshop.webshop.doctype.webshop_settings.webshop_settings.validate_cart_settings",
		],
	},
	"Quotation": {
		"validate": [
			"webshop.webshop.crud_events.quotation.validate_shopping_cart_items.execute",
		],
		"on_trash": "webshop.webshop.shopping_cart.cart.remove_quotation_loyalty_points",
		"on_cancel": "webshop.webshop.shopping_cart.cart.remove_quotation_loyalty_points"
	},
	"Price List": {
		"validate": [
			"webshop.webshop.crud_events.price_list.check_impact_on_cart.execute"
		],
	},
	"Tax Rule": {
		"validate": [
			"webshop.webshop.crud_events.tax_rule.validate_use_for_cart.execute",
		],
	},
	#//// Neoffice — multi-warehouse: webshop Sales Order lines sourced from a
	#//// supplier warehouse prepare a draft Purchase Order (stacked per
	#//// supplier) or a Material Request. Gated inside on Webshop Settings
	#//// (enable_multi_warehouse + enable_supplier_procurement) and on
	#//// order_type "Shopping Cart"; never raises into the submit.
	"Sales Order": {
		"on_submit": [
			"webshop.webshop.multi_warehouse.procurement.process_sales_order",
			#//// Neoffice — purchase follow-ups enrol the customer; a cart
			#//// that became an order stops being "abandoned".
			"webshop.webshop.utils.follow_ups.enroll_from_sales_order",
			"webshop.webshop.utils.abandoned_carts.mark_converted",
		],
		"on_cancel": ["webshop.webshop.utils.follow_ups.on_cancel"],
	},
	#//// Neoffice — multi-warehouse: ERPNext reserves the received goods for
	#//// the customer order on its own (Stock Settings); this only writes the
	#//// timeline comment on the Sales Order so the seller side sees it.
	"Purchase Receipt": {
		"on_submit": [
			"webshop.webshop.multi_warehouse.procurement.notify_sales_orders_on_receipt",
		],
	},
	"Sales Invoice": {
		"validate": "webshop.webshop.crud_events.sales_invoice.validate",
		"on_submit": [
			"webshop.webshop.crud_events.sales_invoice.on_submit",
			"webshop.webshop.utils.follow_ups.enroll_from_sales_invoice",
		],
		"on_cancel": ["webshop.webshop.utils.follow_ups.on_cancel"],
		"on_update": [
			"webshop.webshop.shopping_cart.cart.create_gift_cards_from_invoice"
		]
	},
	"Payment Entry": {
		"on_submit": ["webshop.webshop.shopping_cart.cart.check_gift_cards_from_payment"]
	},
	"Pricing Rule": {
		"on_update": "webshop.webshop.crud_events.pricing_rule.invalidate_discount_cache.execute",
		"after_insert": "webshop.webshop.crud_events.pricing_rule.invalidate_discount_cache.execute",
		"on_trash": "webshop.webshop.crud_events.pricing_rule.invalidate_discount_cache.execute",
	},
	"Item Price": {
		"on_update": "webshop.webshop.crud_events.item_price.invalidate_price_cache.execute",
		"after_insert": "webshop.webshop.crud_events.item_price.invalidate_price_cache.execute",
		"on_trash": "webshop.webshop.crud_events.item_price.invalidate_price_cache.execute",
	},
}

has_website_permission = {
    "Website Item": "webshop.webshop.doctype.website_item.website_item.has_website_permission_for_website_item",
    "Item Group": "webshop.webshop.doctype.website_item.website_item.has_website_permission_for_item_group"
}

website_route_rules = [
	{"from_route": "/api/payment/callback", "to_route": "webshop.controllers.payment_handler.payment_callback"}
]

page_renderer = [
	"webshop.webshop.page_renderers.maintenance_renderer.MaintenancePageRenderer"
]

jinja = {
	"methods": [
		"webshop.webshop.utils.utils",
		"webshop.webshop.utils.cart_helpers.get_cart_data",
        "webshop.webshop.utils.product_carousel_helper.get_carousel_items",
        "webshop.webshop.utils.product_carousel_helper.render_product_carousel",
        "webshop.webshop.utils.brand_carousel_helper.get_brands_with_product_count",
        "webshop.webshop.utils.wishlist_helper.get_wishlist_data"
	]
}