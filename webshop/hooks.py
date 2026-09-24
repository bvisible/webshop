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
# //// Neoffice — added. Upstream only wires after_install, so a shop that was
# //// installed before a field/portal-menu change never got it: after_migrate
# //// re-runs our idempotent setup (custom fields, portal menu, workspace) on
# //// every deploy (6112d75f8c, 2026-08-29 "une installation neuve créait 3
# //// champs personnalisés sur 20"). after_clear_cache rebuilds the RediSearch
# //// index, which `bench clear-cache` drops without telling anyone — the shop
# //// search then returned nothing until someone rebuilt it by hand
# //// (ce5220b7e7 / 2c14d7c948, 2025-12-14 "auto-rebuild Redis search index").
after_migrate = "webshop.setup.install.after_migrate"
on_logout = "webshop.webshop.shopping_cart.utils.clear_cart_count"
on_session_creation = [
	# //// Neoffice — body re-indented from 4 spaces to tabs by our editor config
	# //// (no behaviour change). Kept as-is: reverting it would be a second
	# //// whitespace churn on top of the first. Expect whitespace conflicts here
	# //// at the next upstream merge — resolve by taking OUR side.
	"webshop.webshop.utils.portal.update_debtors_account",
	"webshop.webshop.shopping_cart.utils.set_cart_count",
]

# //// Neoffice — added. Our shops are built with Builder, whose pages replaced
# //// the upstream /home, /navbar and /footer routes, and our listing lives at
# //// /all-products; without these the old upstream URLs (still in customers'
# //// bookmarks and in Google's index) 404ed instead of landing on the shop.
website_redirects = [
	{"source": "/home", "target": "/"},
	{"source": "/homepage", "target": "/"},
	{"source": "/navbar", "target": "/"},
	{"source": "/footer", "target": "/"},
	{"source": "/all-item-groups", "target": "/all-products"}
]

update_website_context = [
	"webshop.webshop.shopping_cart.utils.update_website_context",
	# //// Neoffice — added with the shop maintenance mode (deb34ad632, 2025-06-19
	# //// "Feat. maintenance mode"): the veil has to be injected into EVERY web
	# //// page's context, not only the /maintenance route, otherwise a visitor
	# //// already deep in the shop kept browsing it while it was closed.
	"webshop.webshop.maintenance_context.inject_maintenance_css",
	# //// Neoffice — SEO (2026-09-24, #691): a default robots.txt when nobody wrote one (Frappe
	# //// served an empty file), and "noindex" on the pages a searcher has nothing to do with.
	"webshop.webshop.seo.meta.update_website_context",
]

# //// Neoffice — SEO (2026-09-24, #691 lot 1): the shop's share of the Organization that the site
# //// chrome declares on the home page (builder/site_graph.py): an OnlineStore, its return window
# //// and its free delivery, which every offer of the product pages points at by @id.
site_organization = ["webshop.webshop.seo.jsonld.site_organization"]

# Scheduled Tasks
scheduler_events = {
	"daily": [
		# //// Neoffice — nightly purge of old shop-assistant conversations, except the escalated ones (84412d0bec "feat(assistant): rapport d'usage, purge de nuit, conversations sur la fiche client")
		"webshop.webshop.assistant.api.purge_old_conversations",
		"webshop.webshop.utils.frequently_bought_together.calculate_frequently_bought_together",
		# //// Neoffice — each site's Google Merchant Center feed, written for Google's daily fetch (#691 lot 3)
		"webshop.webshop.seo.feeds.google.generate_feeds",
	],
	# //// Neoffice — abandoned carts: one look per hour at the carts left behind
	"hourly": ["webshop.webshop.utils.abandoned_carts.send_abandoned_cart_reminders"],
	# //// Neoffice — purchase follow-ups go out in the morning, not at midnight
	# //// Neoffice — every ten minutes, what IndexNow should hear of (seo/indexnow.py, #691 lot 4)
	"cron": {
		"15 8 * * *": ["webshop.webshop.utils.follow_ups.send_due_follow_ups"],
		"*/10 * * * *": ["webshop.webshop.seo.indexnow.submit_queue"],
	},
	# //// Neoffice — the store's public holidays: one look a month is enough to
	# //// have next year's in the list well before December, and a provider that is
	# //// down simply leaves the list alone until the next run.
	"monthly": ["webshop.webshop.utils.holidays.top_up_holidays"],
}

# //// Neoffice — follow-ups and cart reminders show under the customer's
# //// connections, next to its orders.
override_doctype_dashboards = {
	"Customer": "webshop.webshop.utils.follow_ups.customer_dashboard",
	"Sales Order": "webshop.webshop.utils.follow_ups.sales_order_dashboard",
	"Sales Invoice": "webshop.webshop.utils.follow_ups.sales_invoice_dashboard",
	"Quotation": "webshop.webshop.utils.follow_ups.quotation_dashboard",
}

# //// Neoffice — the customer's gift cards page (/gift_cards) in the account's menu: the
# //// page existed with no link to it anywhere (2026-09-13). Portal Settings lets a shop
# //// without gift cards switch the entry off.
standard_portal_menu_items = [
	{"title": "Gift Cards", "route": "/gift_cards", "reference_doctype": "Coupon Code", "role": "Customer"},
]

# //// Neoffice — added (2026-09-22). A reminder about an abandoned cart is a trace,
# //// not a value: it must never stop the cart it talks about from being deleted.
# ////
# //// Frappe refuses to delete a document another one links to, and `update_cart`
# //// deletes the quotation when its last line goes — so a customer who had received
# //// a reminder got a 417 on the cross of their last line and could never empty
# //// their cart. That was patched once inside update_cart (b8160bb709), by deleting
# //// the reminders in the rescue branch; but the guard only covered that one code
# //// path, and only after a first failed delete. The hook is the framework's own
# //// answer — `check_if_doc_is_linked` and `check_if_doc_is_dynamically_linked` both
# //// skip these doctypes on a delete — and it is where frappe itself puts
# //// Communication, ToDo, Activity Log, File and Version, for the same reason.
# ////
# //// Payment Request is deliberately NOT here: a request that was PAID means money
# //// moved, and that link must keep holding. `_release_unsuccessful_payment_requests`
# //// releases only the ones that never succeeded.
ignore_links_on_delete = ["Abandoned Cart Reminder"]

website_generators = ["Website Item", "Item Group"]

override_doctype_class = {
	# //// Neoffice — the three upstream entries are unchanged apart from the
	# //// 4-spaces-to-tabs re-indentation (see on_session_creation above).
	"Payment Request": "webshop.webshop.doctype.override_doctype.payment_request.PaymentRequest",
	"Item Group": "webshop.webshop.doctype.override_doctype.item_group.WebshopItemGroup",
	"Item": "webshop.webshop.doctype.override_doctype.item.WebshopItem",
	# //// Neoffice — added: a webshop order that is paid must end as an INVOICE,
	# //// not stop at the Sales Order (536741147b, 2026-07-27 "facturer la
	# //// commande payée au lieu de s'arrêter à la commande client").
	"Sales Invoice": "webshop.webshop.doctype.override_doctype.sales_invoice.SalesInvoice"
}

doctype_js = {
	"Item": "public/js/override/item.js",
	# //// Neoffice — added: the cross-sell / order-bump offers are configured from
	# //// the Item Group and Brand forms (8c29208cca, 2026-09-03 "offres croisées
	# //// et order bump, portés par une Pricing Rule générée"), and the gift-card
	# //// Coupon Code form gets its own script (23c0ae97d9, 2025-02-11).
	"Item Group": "public/js/override/cross_sell_trigger.js",
	"Brand": "public/js/override/cross_sell_trigger.js",
	"Homepage": "public/js/override/homepage.js",
	"Coupon Code": "public/js/coupon_code.js",
	# //// Neoffice — added: "Payment received" on a request the shop raised for a
	# //// transfer. ERPNext's own "Set as Paid" fails on those — the order is held
	# //// until the money is in, and a held order cannot be invoiced.
	"Payment Request": "public/js/override/payment_request.js",
	# //// Neoffice — added: a bank-transfer order is driven from the order itself —
	# //// raise the request, print it (the QR is inside), book the money.
	"Sales Order": "public/js/override/sales_order.js",
}

doc_events = {
	# //// Neoffice — a product or a category whose route changes leaves a 301 behind it
	# //// (2026-09-24, #691, D26): Frappe keeps no history of routes, the old address died.
	"Website Item": {
		# //// Neoffice — and IndexNow hears of it (seo/indexnow.py, #691 lot 4), when switched on;
		# //// its pictures get their WebP copies in the background (utils/renditions.py, lot 5)
		"on_update": [
			"webshop.webshop.seo.redirects.remember_old_route",
			"webshop.webshop.seo.indexnow.queue_website_item",
			"webshop.webshop.utils.renditions.on_website_item_update",
		],
		"on_trash": ["webshop.webshop.seo.indexnow.queue_website_item"],
	},
	# //// Neoffice — a deleted picture takes its WebP copies with it (utils/renditions.py, #691 lot 5)
	"File": {
		"on_trash": ["webshop.webshop.utils.renditions.on_file_trash"],
	},
	"Item Group": {
		"on_update": ["webshop.webshop.seo.redirects.remember_old_route"],
	},
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
	# //// Neoffice — multi-warehouse: webshop Sales Order lines sourced from a
	# //// supplier warehouse prepare a draft Purchase Order (stacked per
	# //// supplier) or a Material Request. Gated inside on Webshop Settings
	# //// (enable_multi_warehouse + enable_supplier_procurement) and on
	# //// order_type "Shopping Cart"; never raises into the submit.
	# //// The feature's doctype fields are ours too: Webshop Settings
	# //// "multi_warehouse_section" (+ its warehouse source table) and Website
	# //// Item "warehouse_sources_mode". Their help texts used to start with
	# //// this marker, which the desk then displayed to users: the marker
	# //// lives here, the descriptions are plain user text (translated).
	"Sales Order": {
		"on_submit": [
			"webshop.webshop.multi_warehouse.procurement.process_sales_order",
			# //// Neoffice — purchase follow-ups enrol the customer; a cart
			# //// that became an order stops being "abandoned".
			"webshop.webshop.utils.follow_ups.enroll_from_sales_order",
			"webshop.webshop.utils.abandoned_carts.mark_converted",
			# //// Neoffice — second-hand: a used unit an order holds is sold (see on_cancel).
			"webshop.webshop.utils.used_items.on_sales_order_change",
		],
		"on_cancel": [
			"webshop.webshop.utils.follow_ups.on_cancel",
			# //// Neoffice — second-hand: submitting and cancelling an order recompute
			# //// Website Item.sold of the used units it holds (utils/used_items.py).
			"webshop.webshop.utils.used_items.on_sales_order_change",
		],
	},
	# //// Neoffice — multi-warehouse: ERPNext reserves the received goods for
	# //// the customer order on its own (Stock Settings); this only writes the
	# //// timeline comment on the Sales Order so the seller side sees it.
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
	# //// Neoffice — second-hand (2026-09-14): a used unit is one of a kind, so the stock ledger
	# //// decides whether it is still in the catalogue (Website Item.sold, utils/used_items.py).
	# //// Only second-hand items are looked at; ordinary movements return at once.
	"Stock Ledger Entry": {
		"on_submit": ["webshop.webshop.utils.used_items.on_stock_ledger_entry"],
	},
	# //// Neoffice — second-hand (2026-09-14): the ledger entry's hook only remembers the used
	# //// units a voucher moves, because ERPNext updates the bins after it; the voucher's own
	# //// on_submit / on_cancel (any doctype that writes stock) recomputes their `sold` flag.
	# //// Returns at once when nothing second-hand moved.
	"*": {
		"on_submit": ["webshop.webshop.utils.used_items.refresh_moved_used_units"],
		"on_cancel": ["webshop.webshop.utils.used_items.refresh_moved_used_units"],
	},
	"Pricing Rule": {
		"on_update": "webshop.webshop.crud_events.pricing_rule.invalidate_discount_cache.execute",
		"after_insert": "webshop.webshop.crud_events.pricing_rule.invalidate_discount_cache.execute",
		"on_trash": "webshop.webshop.crud_events.pricing_rule.invalidate_discount_cache.execute",
	},
	"Item Price": {
		# //// Neoffice — a selling price changed: IndexNow hears of the pages (seo/indexnow.py, #691 lot 4)
		"on_update": ["webshop.webshop.crud_events.item_price.invalidate_price_cache.execute", "webshop.webshop.seo.indexnow.queue_item_price"],
		"after_insert": ["webshop.webshop.crud_events.item_price.invalidate_price_cache.execute", "webshop.webshop.seo.indexnow.queue_item_price"],
		"on_trash": ["webshop.webshop.crud_events.item_price.invalidate_price_cache.execute", "webshop.webshop.seo.indexnow.queue_item_price"],
	},
}

has_website_permission = {
    "Website Item": "webshop.webshop.doctype.website_item.website_item.has_website_permission_for_website_item",
    "Item Group": "webshop.webshop.doctype.website_item.website_item.has_website_permission_for_item_group"
}

# //// Neoffice — everything below is added; upstream's hooks.py ends at
# //// has_website_permission. ▼▼▼
# ////   · website_route_rules: the PSPs (Stripe, Wallee, TWINT, Payrexx, PayPal)
# ////     call back one fixed public URL; upstream has no such entry point
# ////     (f3f669f6f3, 2025-02-11 "move PayPal payment handling to a dedicated
# ////     module", then 7edfb905be / 77e7ed3c19 for the other gateways).
# ////   · page_renderer: the maintenance veil must beat the website router for
# ////     EVERY route, which only a page renderer can do (deb34ad632, 2025-06-19).
# ////   · jinja.methods: helpers our Builder-built templates call directly
# ////     (cart drawer, carousels, wishlist) — upstream templates need none.
website_route_rules = [
	{"from_route": "/api/payment/callback", "to_route": "webshop.controllers.payment_handler.payment_callback"},
	# //// Neoffice — a brand's page (#691 lot 2): /brands/<slug> renders www/brand with its slug.
	{"from_route": "/brands/<brand_slug>", "to_route": "brand"},
]

page_renderer = [
	"webshop.webshop.page_renderers.maintenance_renderer.MaintenancePageRenderer",
	# //// Neoffice — each site's Google Merchant Center feed, /feeds/google.xml (#691 lot 3)
	"webshop.webshop.seo.feeds.google.FeedRenderer",
	# //// Neoffice — the IndexNow key at each site's root, /<key>.txt (#691 lot 4)
	"webshop.webshop.seo.indexnow.KeyRenderer",
	# //// Neoffice — /llms.txt, the shop's card for language models (#691 lot 4)
	"webshop.webshop.seo.llms.LlmsTxtRenderer",
	# //// Neoffice — a picture's WebP copy nobody has written yet, /files/wsr/… (#691 lot 5)
	"webshop.webshop.utils.renditions.RenditionRenderer",
]

jinja = {
	"methods": [
		"webshop.webshop.utils.utils",
		"webshop.webshop.utils.cart_helpers.get_cart_data",
        "webshop.webshop.utils.product_carousel_helper.get_carousel_items",
        "webshop.webshop.utils.product_carousel_helper.render_product_carousel",
        "webshop.webshop.utils.brand_carousel_helper.get_brands_with_product_count",
        "webshop.webshop.utils.wishlist_helper.get_wishlist_data",
        # //// Neoffice — lets templates/includes/opening_hours.html fill itself where
        # //// no controller passes `hours` (a Builder page, the site footer, a page
        # //// generated by Nora). See webshop_opening_hours().
        "webshop.webshop.utils.store_hours.webshop_opening_hours",
        "webshop.webshop.utils.store_hours.opening_hours_css",
        # //// Neoffice — a component included in a Builder page carries its own
        # //// stylesheet, once per request (utils/assets.py). The carousels use it.
        "webshop.webshop.utils.assets.webshop_component_css",
        # //// Neoffice — street + house number composed by ONE rule (utils/address.py).
        # //// The two templates that print an address did it inline, each with its own
        # //// concatenation; erpnextswiss owns the rule and this delegates to it where
        # //// that app is installed.
        "webshop.webshop.utils.address.street_line",
        # //// Neoffice — absolute addresses on the domain of the site being browsed, for the
        # //// breadcrumb's JSON-LD (2026-09-24, #691): get_url answers the instance's host_name.
        "webshop.webshop.seo.site.webshop_site_url",
        # //// Neoffice — srcset, sizes, width and height of a picture (utils/renditions.py, #691 lot 5)
        "webshop.webshop.utils.renditions.webshop_picture",
        # //// Neoffice — {brand: "/brands/<slug>"} for the brands that have a page (#691 lot 2):
        # //// the product page, the brand carousel and the category page link a brand there.
        "webshop.webshop.product_data_engine.brand_pages.brand_page_routes",
	]
}