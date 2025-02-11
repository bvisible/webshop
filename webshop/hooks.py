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

web_include_js = [
    "web.bundle.js",
]

after_install = "webshop.setup.install.after_install"
on_logout = "webshop.webshop.shopping_cart.utils.clear_cart_count"
on_session_creation = [
    "webshop.webshop.utils.portal.update_debtors_account",
    "webshop.webshop.shopping_cart.utils.set_cart_count",
]
update_website_context = [
    "webshop.webshop.shopping_cart.utils.update_website_context",
]
my_account_context = "webshop.webshop.shopping_cart.utils.update_my_account_context"

website_generators = ["Website Item", "Item Group"]

override_doctype_class = {
    "Payment Request": "webshop.webshop.doctype.override_doctype.payment_request.PaymentRequest",
    "Item Group": "webshop.webshop.doctype.override_doctype.item_group.WebshopItemGroup",
    "Item": "webshop.webshop.doctype.override_doctype.item.WebshopItem",
    "Sales Invoice": "webshop.webshop.doctype.override_doctype.sales_invoice.SalesInvoice"
}

doctype_js = {
    "Item": "public/js/override/item.js",
    "Homepage": "public/js/override/homepage.js",
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
    "Sales Invoice": {
        "validate": "webshop.webshop.crud_events.sales_invoice.validate",
        "on_submit": "webshop.webshop.crud_events.sales_invoice.on_submit",
        "on_update": [
            "webshop.webshop.shopping_cart.cart.create_gift_cards_from_invoice"
        ]
    }
}

has_website_permission = {
    "Website Item": "webshop.webshop.doctype.website_item.website_item.has_website_permission_for_website_item",
    "Item Group": "webshop.webshop.doctype.website_item.website_item.has_website_permission_for_item_group"
}

website_route_rules = [
    {"from_route": "/api/payment/callback", "to_route": "webshop.controllers.payment_handler.payment_callback"}
]

jinja = {
    "methods": [
        "webshop.utils.utils"
    ]
}