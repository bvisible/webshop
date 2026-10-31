# //// Neoffice — added file (the reseller's integration page, no upstream equivalent).
"""/my-integration: a reseller asks for the partner API, reads where the request stands, and makes their key.

A visitor is sent to sign in; a signed-in account the shop did not allow gets the 403 page. Every label comes
from the server: a website page has no `__()` catalogue of its own, and this page speaks the shop's language.
"""

import frappe
from frappe import _

from webshop.webshop.catalogue import access

no_cache = 1
PAGE_ROUTE = "/my-integration"


def labels():
	return {
		"lead": _(
			"Connect your own systems to the shop: read its catalogue with your prices and place orders without "
			"typing them. Staff look at each request first."
		),
		"loading": _("Loading…"),
		"failed": _("This could not be done. Try again."),
		"status": _("State"),
		"status_Requested": _("Waiting for an answer"),
		"status_Active": _("Active"),
		"status_Suspended": _("Suspended"),
		"status_Refused": _("Refused"),
		"asked_on": _("Asked on {0}"),
		"note": _("Message from the shop"),
		"request_title": _("Ask for access"),
		"use_case": _("What do you want to do with it?"),
		"use_case_hint": _("One or two sentences: for example, keep your own shop's prices and stock up to date."),
		"expected_volume": _("About how many calls?"),
		"expected_volume_hint": _("For example: a few hundred a day."),
		"wants_orders": _("I also want to place orders"),
		"wants_orders_hint": _("Orders wait as drafts for the shop to read them, unless it allows more."),
		"send_request": _("Send the request"),
		"refused_again": _("You can ask again, saying more about what you need."),
		"allowed": _("What your key may do"),
		"scope_products": _("Read the catalogue, with your prices"),
		"scope_orders": _("Place and read orders"),
		"submit_orders": _("Orders are submitted at once"),
		"drafts": _("Orders wait as drafts for the shop to read them"),
		"allowance": _("{0} calls a minute"),
		"key_title": _("Your key"),
		"no_key": _("You have no key yet."),
		"key_info": _("Key {0}, made on {1}."),
		"key_used": _("Last used: {0}"),
		"key_never_used": _("Not used yet."),
		"make_key": _("Make a key"),
		"replace_key": _("Replace the key"),
		"replace_confirm": _("The current key stops working at once. Continue?"),
		"revoke_key": _("Revoke the key"),
		"revoke_confirm": _("The key stops working at once. Continue?"),
		"secret_title": _("Copy your key now"),
		"secret_warning": _("It is shown once and kept nowhere. Lose it, and you make another."),
		"copy": _("Copy"),
		"copied": _("Copied"),
		"use_title": _("Using it"),
		"base_url": _("Address"),
		"contract": _("The contract (OpenAPI)"),
		"example": _("An example"),
		"example_note": _("Send the key in the X-API-Key header."),
		"feed_hint": _("To keep a whole catalogue up to date, the product feed on your catalogues page costs fewer calls."),
	}


def get_context(context):
	context.body_class = "product-page"  # the shop's ground (webshop_ground.scss)
	context.no_cache = 1
	context.title = _("Integration")
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = f"/login?redirect-to={PAGE_ROUTE}"
		raise frappe.Redirect
	if not access.is_offered():
		raise frappe.PermissionError(_("The integration is not available for your account."))
	context.config = {"labels": labels()}
	return context
