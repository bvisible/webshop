# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _

from webshop.webshop.doctype.webshop_settings.webshop_settings import show_attachments


def get_context(context):
	context.no_cache = 1
	context.show_sidebar = True
	context.doc = frappe.get_doc(frappe.form_dict.doctype, frappe.form_dict.name)
	if hasattr(context.doc, "set_indicator"):
		context.doc.set_indicator()

	if show_attachments():
		context.attachments = get_attachments(frappe.form_dict.doctype, frappe.form_dict.name)

	context.parents = frappe.form_dict.parents
	context.title = frappe.form_dict.name
	context.payment_ref = frappe.db.get_value(
		"Payment Request", {"reference_name": frappe.form_dict.name}, "name"
	)

	context.enabled_checkout = frappe.get_doc("Webshop Settings").enable_checkout

	default_print_format = frappe.db.get_value(
		"Property Setter",
		dict(property="default_print_format", doc_type=frappe.form_dict.doctype),
		"value",
	)
	if default_print_format:
		context.print_format = default_print_format
	else:
		context.print_format = "Standard"

	if not frappe.has_website_permission(context.doc):
		frappe.throw(_("Not Permitted"), frappe.PermissionError)

	# //// Neoffice — upstream reads context.doc.customer, which a Quotation does not have
	# //// (it carries party_name / customer_name), so the loyalty block never appeared on a
	# //// quotation. The guard `if context.doc.get("customer")` is dropped with it
	# //// (618eedfdb8, 2025-03-24).
	# check for the loyalty program of the customer
	customer_loyalty_program = frappe.db.get_value(
		"Customer", context.doc.customer_name, "loyalty_program"
	)
	
	if customer_loyalty_program:
		from erpnext.accounts.doctype.loyalty_program.loyalty_program import (
			get_loyalty_program_details_with_points,
		)
		# //// Neoffice — see above.
		import math

		# //// Neoffice — the balance is rounded DOWN to a multiple of ten, because a programme
		# //// redeems in tens and the buyer was shown a number they could not spend; its cash
		# //// value goes through format_currency_value so the shop's currency setting applies
		# //// (0134ef756e, 2025-07-03).
		loyalty_program_details = get_loyalty_program_details_with_points(
			context.doc.customer_name, customer_loyalty_program
		)
		
		# Get raw loyalty points
		raw_loyalty_points = float(loyalty_program_details.get("loyalty_points", 0))
		
		# Round down loyalty points to the nearest 10
		rounded_loyalty_points = math.floor(raw_loyalty_points / 10) * 10
		
		# Update the loyalty program details
		loyalty_program_details["loyalty_points"] = rounded_loyalty_points
		
		# Set rounded loyalty points in context
		context.available_loyalty_points = rounded_loyalty_points
		
		# If you're also setting the loyalty_points_value here, calculate it based on rounded points
		if "conversion_factor" in loyalty_program_details:
			conversion_factor = loyalty_program_details.get("conversion_factor", 0)
			equivalent_value = rounded_loyalty_points * conversion_factor
			from webshop.webshop.utils.utils import format_currency_value
			context.loyalty_points_value = format_currency_value(equivalent_value, currency=context.doc.currency)

	# show Make Purchase Invoice button based on permission
	context.show_make_pi_button = frappe.has_permission("Purchase Invoice", "create")


def get_attachments(dt, dn):
	return frappe.get_all(
		"File",
		fields=["name", "file_name", "file_url", "is_private"],
		filters={"attached_to_name": dn, "attached_to_doctype": dt, "is_private": 0},
	)
