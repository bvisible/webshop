# //// Neoffice — added file (no upstream equivalent).
"""What a reseller may write in the settings of their brand, checked once for the doctype and the page.

Everything that comes from the browser goes through `clean_brand`: a field not named here is dropped
(a form cannot reach `customer` or `logo` by adding a key), a text is stripped of anything that is
not printable and bounded, a colour is six hexadecimal digits, the website a plain web address, the
markup, rounding and VAT the same closed lists and bounds as the price arithmetic (`markup.py`).
The page prints these values on a catalogue, escaped; nothing here is HTML.
"""

import re

from webshop.webshop.catalogue import markup

TEXT_LIMITS = {
	"brand_name": 80,
	"contact_email": 120,
	"contact_phone": 40,
	"contact_website": 120,
	"vat_number": 40,
	"footer_text": 140,
}
ADDRESS_FIELD = "contact_address"
ADDRESS_MAX_LINES = 4
ADDRESS_MAX_CHARS = 300
COLOUR_FIELDS = ("primary_colour", "secondary_colour")
PRICE_DISPLAYS = ("Excluding VAT", "Including VAT")

DEFAULTS = {
	"primary_colour": "#1f2933",
	"secondary_colour": "#6b7280",
	"default_markup_percent": 0.0,
	"price_rounding": "0.05",
	"price_display": "Excluding VAT",
	"vat_rate": 8.1,
}

_COLOUR = re.compile(r"#[0-9a-fA-F]{6}")
_EMAIL = re.compile(r"[^@\s<>\"'\\,;]+@[^@\s<>\"'\\,;]+\.[^@\s<>\"'\\,;]+")
_HOST = r"(?:[^\W_](?:[\w\-]*[^\W_])?\.)+[^\W_]{2,}"
_WEBSITE = re.compile(rf"(?:https?://)?{_HOST}(?::\d{{1,5}})?(?:/[^\s\"'<>\\]*)?")
# every control character but the tab, the line feed and the carriage return, which count as spaces
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class BrandRefused(ValueError):
	"""A value the brand page does not accept. `field` and `reason` are codes; the caller words them."""

	def __init__(self, field, reason):
		super().__init__(f"{field}: {reason}")
		self.field = field
		self.reason = reason


def is_colour(value):
	"""Whether `value` is a colour written #rrggbb."""
	return isinstance(value, str) and bool(_COLOUR.fullmatch(value))


def _text(field, value, limit):
	value = "" if value is None else str(value)
	if _CONTROL.search(value):
		raise BrandRefused(field, "control_characters")
	value = " ".join(value.split())
	if len(value) > limit:
		raise BrandRefused(field, "too_long")
	return value


def _address(value):
	value = "" if value is None else str(value)
	if _CONTROL.search(value):
		raise BrandRefused(ADDRESS_FIELD, "control_characters")
	lines = [" ".join(line.split()) for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
	lines = [line for line in lines if line]
	if len(lines) > ADDRESS_MAX_LINES or len("\n".join(lines)) > ADDRESS_MAX_CHARS:
		raise BrandRefused(ADDRESS_FIELD, "too_long")
	return "\n".join(lines)


def clean_brand(values):
	"""The fields of `values` that belong to a brand, checked and normalised; the others are dropped."""
	clean = {}
	for field, limit in TEXT_LIMITS.items():
		if field not in values:
			continue
		text = _text(field, values[field], limit)
		if field == "contact_email" and text and not _EMAIL.fullmatch(text):
			raise BrandRefused(field, "bad_email")
		if field == "contact_website" and text and not _WEBSITE.fullmatch(text):
			raise BrandRefused(field, "bad_website")
		clean[field] = text
	if ADDRESS_FIELD in values:
		clean[ADDRESS_FIELD] = _address(values[ADDRESS_FIELD])
	for field in COLOUR_FIELDS:
		if field in values:
			colour = values[field]
			if not isinstance(colour, str) or not _COLOUR.fullmatch(colour):
				raise BrandRefused(field, "bad_colour")
			clean[field] = colour.lower()
	if "default_markup_percent" in values:
		try:
			clean["default_markup_percent"] = float(markup.clean_markup_percent(values["default_markup_percent"]))
		except ValueError:
			raise BrandRefused("default_markup_percent", "bad_markup") from None
	if "price_rounding" in values:
		if values["price_rounding"] not in markup.ROUNDINGS:
			raise BrandRefused("price_rounding", "bad_rounding")
		clean["price_rounding"] = values["price_rounding"]
	if "price_display" in values:
		if values["price_display"] not in PRICE_DISPLAYS:
			raise BrandRefused("price_display", "bad_display")
		clean["price_display"] = values["price_display"]
	if "vat_rate" in values:
		try:
			clean["vat_rate"] = float(markup.clean_vat_rate(values["vat_rate"]))
		except ValueError:
			raise BrandRefused("vat_rate", "bad_vat") from None
	return clean


def _channel(value):
	value = value / 255
	return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4


def _luminance(colour):
	red, green, blue = (_channel(int(colour[i : i + 2], 16)) for i in (1, 3, 5))
	return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(first, second):
	"""WCAG contrast ratio of two colours written #rrggbb: 1 for the same colour, 21 for black on white."""
	lighter, darker = sorted((_luminance(first), _luminance(second)), reverse=True)
	return (lighter + 0.05) / (darker + 0.05)


def readable_ink(colour):
	"""The ink, white or a dark grey, that reads better on `colour`: the brand colour is the reseller's
	choice and a yellow must not get white lettering."""
	white, dark = "#ffffff", "#111111"
	return white if contrast_ratio(colour, white) >= contrast_ratio(colour, dark) else dark
