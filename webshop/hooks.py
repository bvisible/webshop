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
#//// Neoffice — added. Upstream only wires after_install, so a shop that was
#//// installed before a field/portal-menu change never got it: after_migrate
#//// re-runs our idempotent setup (custom fields, portal menu, workspace) on
#//// every deploy (6112d75f8c, 2026-08-29 "une installation neuve créait 3
#//// champs personnalisés sur 20"). after_clear_cache rebuilds the RediSearch
#//// index, which `bench clear-cache` drops without telling anyone — the shop
#//// search then returned nothing until someone rebuilt it by hand
#//// (ce5220b7e7 / 2c14d7c948, 2025-12-14 "auto-rebuild Redis search index").
after_migrate = "webshop.setup.install.after_migrate"
after_clear_cache = "webshop.webshop.redisearch_utils.rebuild_index_after_clear_cache"
on_logout = "webshop.webshop.shopping_cart.utils.clear_cart_count"
on_session_creation = [
	#//// Neoffice — body re-indented from 4 spaces to tabs by our editor config
	#//// (no behaviour change). Kept as-is: reverting it would be a second
	#//// whitespace churn on top of the first. Expect whitespace conflicts here
	#//// at the next upstream merge — resolve by taking OUR side.
	"webshop.webshop.utils.portal.update_debtors_account",
	"webshop.webshop.shopping_cart.utils.set_cart_count",
]

#//// Neoffice — added. Our shops are built with Builder, whose pages replaced
#//// the upstream /home, /navbar and /footer routes, and our listing lives at
#//// /all-products; without these the old upstream URLs (still in customers'
#//// bookmarks and in Google's index) 404ed instead of landing on the shop.
website_redirects = [
	{"source": "/home", "target": "/"},
	{"source": "/homepage", "target": "/"},
	{"source": "/navbar", "target": "/"},
	{"source": "/footer", "target": "/"},
	{"source": "/all-item-groups", "target": "/all-products"}
]

update_website_context = [
	"webshop.webshop.shopping_cart.utils.update_website_context",
	#//// Neoffice — added with the shop maintenance mode (deb34ad632, 2025-06-19
	#//// "Feat. maintenance mode"): the veil has to be injected into EVERY web
	#//// page's context, not only the /maintenance route, otherwise a visitor
	#//// already deep in the shop kept browsing it while it was closed.
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
	#//// Neoffice — the three upstream entries are unchanged apart from the
	#//// 4-spaces-to-tabs re-indentation (see on_session_creation above).
	"Payment Request": "webshop.webshop.doctype.override_doctype.payment_request.PaymentRequest",
	"Item Group": "webshop.webshop.doctype.override_doctype.item_group.WebshopItemGroup",
	"Item": "webshop.webshop.doctype.override_doctype.item.WebshopItem",
	#//// Neoffice — added: a webshop order that is paid must end as an INVOICE,
	#//// not stop at the Sales Order (536741147b, 2026-07-27 "facturer la
	#//// commande payée au lieu de s'arrêter à la commande client").
	"Sales Invoice": "webshop.webshop.doctype.override_doctype.sales_invoice.SalesInvoice"
}

doctype_js = {
	"Item": "public/js/override/item.js",
	#//// Neoffice — added: the cross-sell / order-bump offers are configured from
	#//// the Item Group and Brand forms (8c29208cca, 2026-09-03 "offres croisées
	#//// et order bump, portés par une Pricing Rule générée"), and the gift-card
	#//// Coupon Code form gets its own script (23c0ae97d9, 2025-02-11).
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

#//// Neoffice — everything below is added; upstream's hooks.py ends at
#//// has_website_permission. ▼▼▼
#////   · website_route_rules: the PSPs (Stripe, Wallee, TWINT, Payrexx, PayPal)
#////     call back one fixed public URL; upstream has no such entry point
#////     (f3f669f6f3, 2025-02-11 "move PayPal payment handling to a dedicated
#////     module", then 7edfb905be / 77e7ed3c19 for the other gateways).
#////   · page_renderer: the maintenance veil must beat the website router for
#////     EVERY route, which only a page renderer can do (deb34ad632, 2025-06-19).
#////   · jinja.methods: helpers our Builder-built templates call directly
#////     (cart drawer, carousels, wishlist) — upstream templates need none.
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