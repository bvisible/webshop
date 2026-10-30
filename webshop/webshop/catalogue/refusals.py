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
		"default_markup_percent": _("Markup"),
		"price_rounding": _("Rounding"),
		"price_display": _("Show prices"),
		"vat_rate": _("VAT rate"),
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
