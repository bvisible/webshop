# //// Neoffice — added file (the reseller's brand page, no upstream equivalent).
"""/my-brand: a reseller's logo, colours, contact details and markup.

A visitor is sent to sign in; a signed-in account the shop did not allow gets the 403 page, so the
route tells nothing about who may use it. Every label comes from the server: a website page has no
`__()` catalogue of its own, and this page speaks the shop's language.
"""

import frappe
from frappe import _

from webshop.webshop.catalogue import access

no_cache = 1
PAGE_ROUTE = "/my-brand"


def labels():
	return {
		"lead": _(
			"Your logo, your colours and your contact details appear on the catalogues and the product sheets you make. "
			"The prices are yours too: your markup is added to what you pay."
		),
		"brand": _("Brand"),
		"brand_name": _("Brand name"),
		"logo": _("Logo"),
		"logo_hint": _("A PNG or a JPEG, 2 MB at most."),
		"logo_choose": _("Choose a logo"),
		"logo_remove": _("Remove the logo"),
		"logo_none": _("No logo yet."),
		"primary_colour": _("Primary colour"),
		"secondary_colour": _("Secondary colour"),
		"sample": _("How your name reads on your colours"),
		"contact": _("Contact details"),
		"contact_email": _("E-mail"),
		"contact_phone": _("Phone"),
		"contact_website": _("Website"),
		"contact_address": _("Address"),
		"vat_number": _("VAT number"),
		"footer_text": _("Footer text"),
		"footer_hint": _("Printed at the bottom of every page."),
		"prices": _("Prices"),
		"markup": _("Markup (%)"),
		"markup_hint": _("Added to the price you pay. Between 0 and 300."),
		"rounding": _("Rounding"),
		"rounding_0.05": _("To 5 centimes"),
		"rounding_0.10": _("To 10 centimes"),
		"rounding_1.00": _("To the franc"),
		"rounding_none": _("No rounding"),
		"price_display": _("Show prices"),
		"display_excluding": _("Excluding VAT"),
		"display_including": _("Including VAT"),
		"vat_rate": _("VAT rate (%)"),
		"vat_hint": _("One rate for the whole catalogue."),
		"rules": _("Particular markups"),
		"rules_lead": _(
			"A markup of its own for a category, a brand or a product. It replaces the markup above for what it names; "
			"the most specific one wins: a product, then its category, then its brand."
		),
		"rule_for": _("For"),
		"rule_group": _("Category"),
		"rule_brand": _("Brand"),
		"rule_item": _("Product"),
		"rule_name": _("Name"),
		"rule_percent": _("Markup (%)"),
		"rule_pick_group": _("Choose a category"),
		"rule_pick_brand": _("Choose a brand"),
		"rule_search": _("Search a product by name or reference"),
		"rule_selected": _("Chosen: {0}"),
		"rule_add": _("Add"),
		"rule_remove": _("Remove"),
		"rule_none": _("No particular markup: every product takes the markup above."),
		"rule_choose": _("Choose what the markup is for."),
		"rule_twice": _("This one already has a markup."),
		"rule_percent_missing": _("Enter the markup in percent."),
		"rule_apply": _("Particular markups are used once you have saved."),
		"try": _("Your prices with this markup"),
		"try_product": _("Product"),
		"try_cost": _("You pay"),
		"try_price": _("You sell at"),
		"try_list": _("Prices of your price list: {0}."),
		"try_empty": _("No product to show yet."),
		"credit": _("The supplier adds this line to every catalogue you make: {0}"),
		"save": _("Save"),
		"saved": _("Saved."),
		"loading": _("Loading…"),
		"failed": _("This could not be done. Try again."),
		"logo_too_large": _("The logo is too large: 2 MB at most."),
	}


def get_context(context):
	context.body_class = "product-page"  # the shop's ground (webshop_ground.scss)
	context.no_cache = 1
	context.title = _("Brand")
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = f"/login?redirect-to={PAGE_ROUTE}"
		raise frappe.Redirect
	if not access.is_offered():
		raise frappe.PermissionError(_("The reseller catalogue is not available for your account."))
	context.config = {"labels": labels()}
	return context
