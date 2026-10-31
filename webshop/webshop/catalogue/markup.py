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


# ---------------------------------------------------------------------------------------------
# Markups of their own for a category, a brand or a product (reseller catalogue, lot 5)

# What a rule can name, from the most specific: a product, a category, a brand. The most specific rule
# that names a product decides its markup; none names it, the catalogue's own markup does.
RULE_KINDS = ("Item", "Item Group", "Brand")
MAX_RULES = 200
MAX_TARGET = 140


class RuleRefused(ValueError):
	"""A rule the page does not accept. `reason` is a code the caller words; `index` is the row it is about."""

	def __init__(self, reason, index=None):
		super().__init__(f"{reason} (rule {index})" if index is not None else reason)
		self.reason = reason
		self.index = index


def clean_rules(raw):
	"""The rules as a list of {"rule_type", "target", "markup_percent"}, checked, or a RuleRefused.

	A closed list of kinds, a name that is not empty or long, a percentage between 0 and 300, and one rule for
	a target: two percentages for one category would leave the printed price to the order of the rows."""
	if raw in (None, ""):
		return []
	if not isinstance(raw, (list, tuple)):
		raise RuleRefused("not_a_list")
	if len(raw) > MAX_RULES:
		raise RuleRefused("too_many")
	clean, seen = [], set()
	for index, row in enumerate(raw):
		if not isinstance(row, dict):
			raise RuleRefused("not_a_list", index)
		kind = row.get("rule_type")
		if kind not in RULE_KINDS:
			raise RuleRefused("bad_kind", index)
		target = row.get("target")
		if not isinstance(target, str) or not target.strip() or len(target.strip()) > MAX_TARGET:
			raise RuleRefused("bad_target", index)
		target = target.strip()
		try:
			percent = float(clean_markup_percent(row.get("markup_percent")))
		except ValueError:
			raise RuleRefused("bad_percent", index) from None
		if (kind, target) in seen:
			raise RuleRefused("duplicate", index)
		seen.add((kind, target))
		clean.append({"rule_type": kind, "target": target, "markup_percent": percent})
	return clean


class Markups:
	"""The markup of each product: the most specific rule that names it, else `default`.

	`chain_of(group)` answers the group and the groups above it, nearest first, so that a rule on "Shoes" reaches
	a product of "Shoes > Trail" unless "Trail" has a rule of its own. A product is named by its own code, then
	by its model's (a rule on a model covers its variants), then by its category, then by its brand."""

	def __init__(self, rules, default, chain_of=None):
		self.default = default
		self.chain_of = chain_of or (lambda group: [group] if group else [])
		self._by_kind = {kind: {} for kind in RULE_KINDS}
		for rule in rules or ():
			self._by_kind[rule["rule_type"]][rule["target"]] = float(rule["markup_percent"])

	def __len__(self):
		return sum(len(rules) for rules in self._by_kind.values())

	def percent(self, item_codes=(), group=None, brand=None):
		for code in item_codes:
			if code in self._by_kind["Item"]:
				return self._by_kind["Item"][code]
		for name in self.chain_of(group):
			if name in self._by_kind["Item Group"]:
				return self._by_kind["Item Group"][name]
		if brand and brand in self._by_kind["Brand"]:
			return self._by_kind["Brand"][brand]
		return self.default
