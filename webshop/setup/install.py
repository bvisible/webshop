import click
import frappe

from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from webshop.webshop.utils.setup import has_ecommerce_fields

def after_install():
	run_patches()
	copy_from_ecommerce_settings()
	drop_ecommerce_settings()
	remove_ecommerce_settings_doctype()
	add_custom_fields()
	navbar_add_products_link()
	say_thanks()


def copy_from_ecommerce_settings():
	if not has_ecommerce_fields():
		return

	frappe.reload_doc("webshop", "doctype", "webshop_settings")

	qb = frappe.qb
	table = frappe.qb.Table("tabSingles")
	old_doctype = "E Commerce Settings"
	new_doctype = "Webshop Settings"

	entries = (
		qb.from_(table)
		.select(table.field, table.value)
		.where((table.doctype == old_doctype) & (table.field != "name"))
		.run(as_dict=True)
	)

	for e in entries:
		qb.into(table).insert(new_doctype, e.field, e.value).run()

	for doctype in ["Website Filter Field", "Website Attribute"]:
		table = qb.DocType(doctype)
		query = (
			qb.update(table)
			.set(table.parent, new_doctype)
			.set(table.parenttype, new_doctype)
			.where(table.parent == old_doctype)
		)

		query.run()

def drop_ecommerce_settings():
	frappe.delete_doc_if_exists("DocType", "E Commerce Settings", force=True)


def remove_ecommerce_settings_doctype():
	if not has_ecommerce_fields():
		return

	table = frappe.qb.Table("tabSingles")
	old_doctype = "E Commerce Settings"

	frappe.qb.from_(table).delete().where(table.doctype == old_doctype).run()


def add_custom_fields():
	custom_fields = {
		"Item": [
			{
				"default": 0,
				"depends_on": "published_in_website",
				"fieldname": "published_in_website",
				"fieldtype": "Check",
				"ignore_user_permissions": 1,
				"insert_after": "default_manufacturer_part_no",
				"label": "Published In Website",
				"read_only": 1,
				"no_copy": 1,
			}
		],
		"Item Group": [
			{
				"fieldname": "custom_website_settings",
				"fieldtype": "Section Break",
				"label": "Website Settings",
				"insert_after": "taxes",
			},
			{
				"default": "0",
				"description": "Make Item Group visible in website",
				"fieldname": "show_in_website",
				"fieldtype": "Check",
				"label": "Show in Website",
				"insert_after": "custom_website_settings",
			},
			{
				"depends_on": "show_in_website",
				"fieldname": "route",
				"fieldtype": "Data",
				"label": "Route",
				"no_copy": 1,
				"unique": 1,
				"insert_after": "show_in_website",
			},
			{
				"depends_on": "show_in_website",
				"fieldname": "website_title",
				"fieldtype": "Data",
				"label": "Title",
				"insert_after": "route",
			},
			{
				"depends_on": "show_in_website",
				"description": "HTML / Banner that will show on the top of product list.",
				"fieldname": "description",
				"fieldtype": "Text Editor",
				"label": "Description",
				"insert_after": "website_title",
			},
			{
				"default": "0",
				"depends_on": "show_in_website",
				"description": "Include Website Items belonging to child Item Groups",
				"fieldname": "include_descendants",
				"fieldtype": "Check",
				"label": "Include Descendants",
				"insert_after": "website_title",
			},
			{
				"fieldname": "column_break_16",
				"fieldtype": "Column Break",
				"insert_after": "include_descendants",
			},
			{
				"depends_on": "show_in_website",
				"fieldname": "weightage",
				"fieldtype": "Int",
				"label": "Weightage",
				"insert_after": "column_break_16",
			},
			{
				"depends_on": "show_in_website",
				"description": "Show this slideshow at the top of the page",
				"fieldname": "slideshow",
				"fieldtype": "Link",
				"label": "Slideshow",
				"options": "Website Slideshow",
				"insert_after": "weightage",
			},
			{
				"depends_on": "show_in_website",
				"fieldname": "website_specifications",
				"fieldtype": "Table",
				"label": "Website Specifications",
				"options": "Item Website Specification",
				"insert_after": "description",
			},
			{
				"collapsible": 1,
				"depends_on": "show_in_website",
				"fieldname": "website_filters_section",
				"fieldtype": "Section Break",
				"label": "Website Filters",
				"insert_after": "website_specifications",
			},
			{
				"fieldname": "filter_fields",
				"fieldtype": "Table",
				"label": "Item Fields",
				"options": "Website Filter Field",
				"insert_after": "website_filters_section",
			},
			{
				"fieldname": "filter_attributes",
				"fieldtype": "Table",
				"label": "Attributes",
				"options": "Website Attribute",
				"insert_after": "filter_fields",
			},
		]
	}

	frappe.make_property_setter(
		{
			"doctype": "Item Group",
			"doctype_or_field": "DocType",
			"fieldname": "allow_guest_to_view",
			"property": "allow_guest_to_view",
			"value": 1,
			"property_type": "Check"
		},
		is_system_generated=True,
	)

	return create_custom_fields(custom_fields)

def navbar_add_products_link():
	website_settings = frappe.get_doc("Website Settings")
	if website_settings.top_bar_items:
		return

	website_settings.append(
		"top_bar_items",
		{
			"label": _("Products"),
			"url": "/all-products",
			"right": False,
		},
	)

	website_settings.save()


def say_thanks():
	click.secho("Thank you for installing Frappe Webshop!", color="green")


def after_migrate():
	"""Ensure Customer role has permission to create addresses in checkout."""
	setup_address_permissions()


def setup_address_permissions():
	"""
	Add Custom DocPerm for Customer role on Address DocType.
	This is required for webshop checkout to work properly when customers
	create new addresses.
	"""
	# Check if Customer permission already exists
	existing = frappe.db.exists("Custom DocPerm", {
		"parent": "Address",
		"role": "Customer"
	})

	if existing:
		return

	# Create permission for Customer role
	perm = frappe.get_doc({
		"doctype": "Custom DocPerm",
		"parent": "Address",
		"role": "Customer",
		"permlevel": 0,
		"read": 1,
		"write": 1,
		"create": 1,
		"delete": 1,
		"if_owner": 1,
		"idx": 10
	})
	perm.insert(ignore_permissions=True)
	frappe.db.commit()

	click.secho("Added Customer permission on Address for webshop checkout", fg="green")


patches = [
	"create_website_items",
	"populate_e_commerce_settings",
	"add_homepage_field",
	"make_homepage_products_website_items",
	"fetch_thumbnail_in_website_items",
	"convert_to_website_item_in_item_card_group_template",
	"shopping_cart_to_ecommerce",
	"copy_custom_field_filters_to_website_item",
	"add_homepage_field",
	"add_guest_session_to_quotation",
]

#//// Neoffice — the custom fields a fresh install would otherwise never get.
#////
#//// `bench install-app` marks everything in patches.txt as already applied
#//// instead of running it — correct for a schema patch, wrong for a patch whose
#//// whole job is to CREATE a field. Only three of the twenty field-creating
#//// patches were replayed above, so a new shop started life missing seventeen
#//// custom fields: payment idempotency and gateway, gift cards, loyalty,
#//// coupons, shipping rule descriptions, the multi-warehouse marker.
#////
#//// It is not theoretical. Without `custom_idempotency_token`, the very first
#//// query in create_payment_request raises "Unknown column
#//// tabPayment Request.custom_idempotency_token", the blanket except turns it
#//// into "error creating the payment request", and nobody can pay. CI on a
#//// fresh site is what surfaced it.
#////
#//// Every one of these checks before it writes, so replaying them is free.
#//// RULE: a patch that creates a field belongs in this list, in patches.txt
#//// order.
CHAMPS_A_CREER_A_L_INSTALLATION = [
	"add_shipping_rule_description",
	"add_loyalty_points_reduction_field",
	"add_loyalty_point_entry_field",
	"add_checkout_fields_to_payment_gateway_account",
	"add_gift_card_data_to_sales_doctypes",
	"add_payment_gateway_to_quotation",
	"add_sales_invoice_link_to_coupon_code",
	"add_from_checkout_to_payment_request",
	"add_gift_card_amount_field",
	"add_payment_method_field",
	"add_gift_card_fields_to_quotation",
	"add_coupon_code_residual_field",
	"add_idempotency_token_to_payment_request",
	"add_missing_gift_card_fields",
	"add_birthday_field_to_contact",
	"add_webshopsi_fee_field",
	"add_webshop_po_marker_field",
	"add_item_condition_fields",
	"add_condition_shop_filter",
	"add_item_replenishment_field",
	"seed_follow_up_email_templates",
]


def run_patches():
	# Customers migrating from v13 to v15 directly need to run all below patches

	frappe.flags.in_patch = True

	try:
		for patch in patches + CHAMPS_A_CREER_A_L_INSTALLATION:
			try:
				frappe.get_attr(f"webshop.patches.{patch}.execute")()
			except Exception:
				#//// One missing field must not abort the whole installation:
				#//// log it and carry on, so the shop still installs and the
				#//// gap is visible in the error log.
				frappe.log_error(
					"Webshop install: patch failed",
					f"patch={patch}\n{frappe.get_traceback()}",
				)

	finally:
		frappe.flags.in_patch = False


