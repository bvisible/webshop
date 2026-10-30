# //// Neoffice — added file (no upstream equivalent).
"""A reseller's selling price: what they paid, a markup, a rounding, and the VAT if shown.

Pure functions, no database, no request. The server computes every price printed on a
reseller's catalogue; the browser only sends a percentage and a rounding chosen from a closed
list, never a price (same rule as the partner API: the price never comes from the caller).

Amounts are `Decimal` from the first line to the last: a float goes through `str()` first, so
0.1 + 0.2 enters as 0.30000000000000004 rather than whatever binary neighbour it stands for, and
a half step always rounds up — the way a till does, not to the even neighbour.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

# The roundings a reseller may pick. "none" keeps the centimes; the others snap to a step.
ROUNDINGS = ("0.05", "0.10", "1.00", "none")
MIN_MARKUP_PERCENT = Decimal("0")
MAX_MARKUP_PERCENT = Decimal("300")
CENT = Decimal("0.01")


def _number(value, what):
	"""A finite Decimal from a number or a numeric string, or a ValueError naming `what`."""
	try:
		number = Decimal(str(value).strip())
	except InvalidOperation:
		raise ValueError(f"{what} is not a number") from None
	if not number.is_finite():
		raise ValueError(f"{what} is not a finite number")
	return number


def clean_markup_percent(value):
	"""The markup as a Decimal, between 0 and 300 percent."""
	percent = _number(value, "markup")
	if not MIN_MARKUP_PERCENT <= percent <= MAX_MARKUP_PERCENT:
		raise ValueError(f"markup must be between {MIN_MARKUP_PERCENT} and {MAX_MARKUP_PERCENT} percent")
	return percent


def clean_vat_rate(value):
	"""The VAT rate as a Decimal, between 0 and 100 percent."""
	rate = _number(value, "VAT rate")
	if not Decimal("0") <= rate <= Decimal("100"):
		raise ValueError("VAT rate must be between 0 and 100 percent")
	return rate


def round_price(amount, rounding):
	"""`amount` rounded to the step `rounding` names, a half step going up."""
	if rounding not in ROUNDINGS:
		raise ValueError(f"rounding must be one of {', '.join(ROUNDINGS)}")
	if rounding == "none":
		return amount.quantize(CENT, ROUND_HALF_UP)
	step = Decimal(rounding)
	return ((amount / step).quantize(Decimal(1), ROUND_HALF_UP) * step).quantize(CENT)


def selling_price(cost, markup_percent, rounding="0.05", vat_rate=None, include_vat=False):
	"""What the reseller sells at: `cost` plus the markup, plus the VAT when shown, rounded last.

	`cost` is what the reseller pays the supplier — their own price, never anyone else's. None
	means the supplier has no price for the item, and the answer is None. Everything the caller
	chose is checked, a missing cost included, so a bad percentage is refused on every item.
	"""
	percent = clean_markup_percent(markup_percent)
	if rounding not in ROUNDINGS:
		raise ValueError(f"rounding must be one of {', '.join(ROUNDINGS)}")
	vat = clean_vat_rate(vat_rate) if include_vat else None
	if cost is None:
		return None
	base = _number(cost, "cost")
	if base < 0:
		raise ValueError("cost must not be negative")
	price = base * (1 + percent / 100)
	if vat is not None:
		price *= 1 + vat / 100
	return round_price(price, rounding)
