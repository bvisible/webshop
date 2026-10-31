# //// Neoffice — added file (no upstream equivalent).
"""The words of a refusal, in the language of the person who is refused.

brand.py and logo.py answer with codes, so that they stay pure and testable; this module is the only
place that turns a code into a sentence. Every msgid is an English literal inside a function, where
`bench generate-pot-file` finds it.
"""

from frappe import _


def brand_message(field, reason):
	labels = {
		"brand_name": _("Brand name"),
		"contact_email": _("E-mail"),
		"contact_phone": _("Phone"),
		"contact_website": _("Website"),
		"contact_address": _("Address"),
		"vat_number": _("VAT number"),
		"footer_text": _("Footer text"),
		"primary_colour": _("Primary colour"),
		"secondary_colour": _("Secondary colour"),
		"default_markup_percent": _("Price markup"),
		"price_rounding": _("Rounding"),
		"price_display": _("Show prices"),
		"vat_rate": _("VAT rate"),
		"markup_rules": _("Particular markups"),
	}
	reasons = {
		"too_long": _("{0} is too long."),
		"control_characters": _("{0} contains characters that cannot be printed."),
		"bad_colour": _("{0} must be a colour written like #0b6e4f."),
		"bad_email": _("{0} must be one e-mail address."),
		"bad_website": _("{0} must be a web address, like www.example.ch."),
		"bad_markup": _("{0} must be a number between 0 and 300."),
		"bad_rounding": _("{0} must be one of the choices offered."),
		"bad_display": _("{0} must be one of the choices offered."),
		"bad_vat": _("{0} must be a number between 0 and 100."),
		"rule_not_a_list": _("{0} could not be read."),
		"rule_too_many": _("{0} has too many rows: 200 at most."),
		"rule_bad_kind": _("Each of the {0} is for a category, a brand or a product."),
		"rule_bad_target": _("Each of the {0} must name a category, a brand or a product."),
		"rule_bad_percent": _("Each of the {0} must be a number between 0 and 300."),
		"rule_duplicate": _("The {0} name a category, a brand or a product twice."),
		"rule_unknown_target": _("The {0} name something this shop does not carry."),
	}
	return reasons.get(reason, _("{0} is not valid.")).format(labels.get(field, field))


def logo_message(reason):
	messages = {
		"too_large": _("The logo is too large: 2 MB at most."),
		"not_an_image": _("This file is not an image that can be read. Send a PNG or a JPEG."),
		"format": _("Only a PNG or a JPEG can be used as a logo."),
		"too_many_pixels": _("This picture has too many pixels. Send a smaller one."),
	}
	return messages.get(reason, _("This logo cannot be used."))


def selection_message(reason):
	messages = {
		"empty": _("Choose at least one category, one brand or one product."),
		"too_many": _("The selection has too many entries. Choose categories rather than products one by one."),
	}
	return messages.get(reason, _("This selection could not be read."))


def options_message(field, reason):
	"""The refusal of a catalogue's title or option, worded for the field the page shows it beside."""
	messages = {
		("title", "required"): _("Give the catalogue a title."),
		("title", "too_long"): _("The title is too long: 80 characters at most."),
		("title", "not_plain"): _("The title cannot contain the characters < and >."),
		("markup_percent", "out_of_range"): _("The markup must be a number between 0 and 300."),
		("prices", "not_allowed"): _("Choose which prices to show from the list."),
		("layout", "not_allowed"): _("Choose a layout from the list."),
		("format", "not_allowed"): _("Choose a format from the list."),
	}
	return messages.get((field, reason), _("This option is not valid."))


def catalogue_message(reason, number=None):
	"""Why a catalogue was not made, in a sentence. `number` is the limit the sentence names, when it names one."""
	messages = {
		"empty": _("The shop offers none of the products of this selection."),
		"too_many_products": _("This selection holds more than {0} products. Narrow it down.").format(number),
		"too_many_pages": _("This catalogue would run to more than {0} pages. Narrow the selection.").format(number),
		"too_many_rows": _(
			"This file would hold more than {0} lines (a product with several variants is one line for each). Narrow the selection."
		).format(number),
		"busy": _("A catalogue is still being made. Wait for it to finish."),
		"daily_limit": _("You have asked for {0} catalogues in the last 24 hours. Try again later.").format(number),
		"no_brand": _("Save your brand first: a catalogue carries your name, your logo and your colours."),
		"no_brand_prices": _("Save your brand first: it keeps your markup, your rounding and whether your prices include VAT."),
		"no_engine": _("This server cannot make PDF documents."),
		"failed": _("The catalogue could not be made. The team has been told."),
		"stalled": _("The catalogue took too long and was stopped. Try again, with a smaller selection."),
	}
	return messages.get(reason, _("The catalogue could not be made."))


def feed_message(reason, number=None):
	"""Why a feed was not saved or refreshed, in a sentence."""
	messages = {
		"no_brand": _("Save your brand first: your feed carries prices with your markup, and your brand keeps it."),
		"busy": _("The feed is being refreshed. Wait for it to finish."),
		"refresh_limit": _("The feed was refreshed {0} times in the last 24 hours. Try again later.").format(number),
		"none": _("You have no feed."),
		"not_offered": _("The reseller catalogue is no longer available for your account."),
		"failed": _("The feed could not be made. The team has been told."),
		"stalled": _("The feed took too long and was stopped. Try again, with a smaller selection."),
	}
	return messages.get(reason, _("The feed could not be made."))


def api_message(reason, number=None):
	"""The words of the partner API's portal page and desk buttons (the API itself answers in English)."""
	messages = {
		"use_case_required": _("Say in a sentence what you want to do with the API."),
		"use_case_invalid": _("The description is too long ({0} characters at most) or contains the characters < and >.").format(number),
		"volume_invalid": _("The expected volume is too long: {0} characters at most.").format(number),
		"already": _("You already have an access, or a request waiting for an answer."),
		"too_many_requests": _("You asked several times today. Try again tomorrow."),
		"not_active": _("This access is not active."),
		"too_many_keys": _("You made several keys in the last hour. Try again later."),
		"no_access": _("There is no access to decide on."),
		"not_requested": _("This access is not waiting for a decision."),
		"not_suspended": _("This access is not suspended."),
		"calls_invalid": _("Calls per minute must be between 1 and {0}.").format(number),
	}
	return messages.get(reason, _("This could not be done."))
