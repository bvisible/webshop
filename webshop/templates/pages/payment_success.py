# //// Neoffice — added file (no upstream equivalent). The template of this route read the request by itself:
# //// webshop comes after payments in installed_apps, so it serves /payment-success in place of payments' page
# //// and held none of its checks. A filter from a JSON body reached `frappe.get_doc`, `redirect_to` was
# //// printed raw in a script, and the page was cached by path, so a visitor got the page of the one before.
# Copyright (c) 2026, Neoffice and contributors
# License: MIT. See LICENSE

import frappe

from payments.utils.utils import require_text, safe_redirect_to

no_cache = 1


def get_context(context):
	doctype, docname = frappe.form_dict.doctype, frappe.form_dict.docname
	require_text(doctype, docname, frappe.form_dict.token)

	# A name that resolves to nothing reads like no name: a visitor does not learn which requests exist.
	context.payment_request = None
	if doctype == "Payment Request" and docname and frappe.db.exists("Payment Request", docname):
		context.payment_request = frappe.get_doc("Payment Request", docname)

	context.redirect_to = safe_redirect_to(frappe.form_dict.redirect_to) or "/orders"
