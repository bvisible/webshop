# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _

# //// Neoffice — see make_payment_request.
from frappe.utils import cint

from webshop.webshop.doctype.webshop_settings.webshop_settings import show_attachments

# //// Neoffice — see get_context.
from webshop.webshop.shopping_cart import pending_order


# //// Neoffice — added function (no upstream equivalent). The page offered "Pay" whatever the state of the
# //// document, and make_payment_request raised the request: a customer could pay an order the shop had
# //// cancelled or closed. An order On Hold stays payable: it waits for that very payment. order.html
# //// states the same rule on its button.
def can_be_paid(doc):
	return (
		doc.doctype in ("Sales Order", "Sales Invoice")
		and doc.docstatus == 1
		and doc.get("status") not in ("Cancelled", "Closed")
	)


def get_context(context):
	context.body_class = "product-page"  # //// Neoffice — the shop's ground (webshop_ground.scss)
	context.no_cache = 1
	context.show_sidebar = True
	context.doc = frappe.get_doc(frappe.form_dict.doctype, frappe.form_dict.name)
	# //// Neoffice — multilingual lot 5: the lines are named in the language of the page, else of the order
	from webshop.webshop.utils.localized import localize_lines

	localize_lines(context.doc)
	# //// Neoffice — the placeholder order a card payment is raised on (pending_order.py) is no order yet: it has no
	# //// page, whoever asks (its "Pay" button would raise a second payment on the cart's behalf). Judged on the name
	# //// of the document LOADED: the database finds `pending-qtn-1` or an accented spelling as it finds the real name.
	if context.doc.doctype == "Sales Order" and pending_order.is_placeholder(context.doc.name):
		raise frappe.DoesNotExistError
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
	# //// Neoffice — the Pay form posts it (#2222, see make_payment_request).
	from frappe.sessions import get_csrf_token

	context.csrf_token = get_csrf_token()

	default_print_format = frappe.db.get_value(
		"Property Setter",
		dict(property="default_print_format", doc_type=frappe.form_dict.doctype),
		"value",
	)
	if default_print_format:
		context.print_format = default_print_format
	else:
		context.print_format = "Standard"

	# //// Neoffice — the fallback upstream 15.124 gave its own order page (a member of the staff reads what
	# //// the desk lets them read): the new has_website_permission answers False to an account without the
	# //// Customer or Supplier role, a Website Manager included, who would meet "Not Permitted" on /order.
	if not (context.doc.has_permission("read") or frappe.has_website_permission(context.doc)):
		frappe.throw(_("Not Permitted"), frappe.PermissionError)

	# //// Neoffice — upstream reads context.doc.customer, which a Quotation does not have
	# //// (it carries party_name / customer_name), so the loyalty block never appeared on a
	# //// quotation. The guard `if context.doc.get("customer")` is dropped with it
	# //// (618eedfdb8, 2025-03-24).
	# //// Neoffice — the customer by its link (customer_of), not by context.doc.customer_name: a
	# //// label, which missed every customer named by series. The balance through loyalty_rights:
	# //// upstream v15.123.0 refuses ERPNext's get_loyalty_program_details_with_points to a portal
	# //// customer (Customer read on the session user, aea326869b); the website permission above
	# //// already let this session see the order, and the shop then asks with its own rights.
	from webshop.webshop.shopping_cart.loyalty_rights import customer_loyalty_details, customer_of

	loyalty_customer = customer_of(context.doc)
	# check for the loyalty program of the customer
	customer_loyalty_program = loyalty_customer and frappe.db.get_value(  # //// Neoffice — see above
		"Customer", loyalty_customer, "loyalty_program"
	)
	
	# //// Neoffice — the balance is rounded DOWN to a multiple of ten, because a programme
	# //// redeems in tens and the buyer was shown a number they could not spend; its cash
	# //// value goes through format_currency_value so the shop's currency setting applies
	# //// (0134ef756e, 2025-07-03).
	loyalty_program_details = customer_loyalty_program and customer_loyalty_details(
		loyalty_customer, customer_loyalty_program
	)

	if loyalty_program_details:
		# //// Neoffice — see above.
		import math
		
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


# //// Neoffice — added function (no upstream equivalent): the order page's "Pay" button. erpnext's make_payment_request
# //// asks its caller for the right to create a Payment Request (v15.99.0, GHSA-wpfx-jw7g-7f83), which a portal customer
# //// does not have: the button, which called it directly, would stop working. The page already shows an order only to
# //// whoever the website permission lets see it; the same test guards the request, which is then made as the system.
# //// Drop this, and the two links to it in order.html and order.js, if upstream's page ever makes its own way to it.
# //// Neoffice — POST only (neoffice-maintenance#2222): a GET that creates a Payment Request could be fired by any
# //// page at a signed-in customer. The order page posts a form with its CSRF token, as erpnext's does since
# //// v15.124.4 (71b17c6aff).
@frappe.whitelist(methods=["POST"])
def make_payment_request(**args):
	args = frappe._dict(args)
	if args.dt not in ("Sales Order", "Sales Invoice") or not isinstance(args.dn, str):
		frappe.throw(_("Not Permitted"), frappe.PermissionError)

	# //// Neoffice — loaded once: the placeholder test and the permission test below judge the same document.
	order = frappe.get_doc(args.dt, args.dn)

	# //// Neoffice — the cart's placeholder order is no order to pay (pending_order.py): the cart is paid through
	# //// the checkout. Judged on the name of the document loaded (see get_context).
	if order.doctype == "Sales Order" and pending_order.is_placeholder(order.name):
		frappe.throw(_("Not Permitted"), frappe.PermissionError)

	# //// Neoffice — the document loaded above (it was loaded here).
	# //// Neoffice — same fallback as in get_context (upstream 15.124's has_website_permission needs the Customer role).
	if not (order.has_permission("read") or frappe.has_website_permission(order)):
		frappe.throw(_("Not Permitted"), frappe.PermissionError)

	# //// Neoffice — see can_be_paid. After the test above: a stranger learns nothing of the order's state.
	if not can_be_paid(order):
		frappe.throw(_("This order can no longer be paid."), frappe.PermissionError)

	# //// Neoffice — what the two links of the page send, and nothing else. Every other argument went
	# //// through to erpnext, which runs below as Administrator: `party_type` and `party` read the default
	# //// bank account of any party into the answer, `recipient_id` mailed the link anywhere,
	# //// `payment_request_type` or `mode_of_payment` made another request than the page's. The party is
	# //// now the order's, no bank account is named, and the answer is the redirect to the payment page. A
	# //// document handed in by the client (`ref_doc`) goes with the rest.
	request = {"dt": order.doctype, "dn": order.name, "submit_doc": 1, "order_type": "Shopping Cart"}
	if cint(args.get("loyalty_points")):
		request["loyalty_points"] = cint(args.get("loyalty_points"))
	# order.js names the account of the shop's settings; a browser picks no other one
	account = frappe.db.get_single_value("Webshop Settings", "payment_gateway_account")
	if account and args.get("payment_gateway_account") == account:
		request["payment_gateway_account"] = account

	from erpnext.accounts.doctype.payment_request.payment_request import (
		make_payment_request as erpnext_make_payment_request,
	)

	session = frappe.local.session
	previous = session.user
	# not frappe.set_user(): it replaces the session id and its data too
	session.user = "Administrator"
	try:
		# //// Neoffice — `request`, not the caller's arguments: see above.
		return erpnext_make_payment_request(**request)
	finally:
		session.user = previous


# //// Neoffice — added function (no upstream equivalent): the redemption factor the order page's loyalty
# //// field asks for. The page called erpnext's get_redeemption_factor, which upstream v15.123.0 opens only
# //// to a desk right on Sales or POS Invoice (aea326869b): a portal customer could no longer redeem.
# //// Guarded like make_payment_request above: the order the session may see names the customer -- a
# //// customer sent by the browser is never trusted -- then loyalty_rights asks with the shop's rights.
@frappe.whitelist()
def get_redemption_factor(dt, dn):
	if dt != "Sales Order" or not isinstance(dn, str):
		frappe.throw(_("Not Permitted"), frappe.PermissionError)

	doc = frappe.get_doc(dt, dn)
	# //// Neoffice — same fallback as in get_context (upstream 15.124's has_website_permission needs the Customer role).
	if not (doc.has_permission("read") or frappe.has_website_permission(doc)):
		frappe.throw(_("Not Permitted"), frappe.PermissionError)

	from webshop.webshop.shopping_cart.loyalty_rights import customer_of, customer_redemption_factor

	return customer_redemption_factor(customer_of(doc))


def get_attachments(dt, dn):
	return frappe.get_all(
		"File",
		fields=["name", "file_name", "file_url", "is_private"],
		filters={"attached_to_name": dn, "attached_to_doctype": dt, "is_private": 0},
	)
