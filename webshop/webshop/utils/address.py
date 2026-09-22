# //// Neoffice — added file (no upstream equivalent).
"""One rule for writing a street and its number on one line.

The address model is structured: `address_line1` carries the street ALONE and the
number lives in `custom_house_number` (erpnextswiss ADR-002). Every surface that
prints an address therefore has to put the two back together — and webshop did it
twice, inline in two templates, each with its own concatenation. Counting the
postal label, which had lost the number entirely by sending `address_line1` bare,
that made three copies of one rule across the fleet.

erpnextswiss owns the rule (`compose_address_line`). webshop does NOT depend on
that app — the CI installs a plain ERPNext, and a shop can run without it — so
this delegates when it is installed and composes identically when it is not. The
optional import is the same idiom the quick order uses for neoffice_theme.
"""

def compose_street_line(street, number=None):
	"""Street and number on one line, by erpnextswiss' rule wherever it is installed."""
	try:
		from erpnextswiss.erpnextswiss.common_functions import compose_address_line
	except ImportError:
		compose_address_line = None

	if compose_address_line:
		return compose_address_line(street, number)

	street = (street or "").strip()
	number = (number or "").strip()
	if street and number:
		return "{0} {1}".format(street, number)
	return street or number


def street_line(address):
	"""The same rule for a template holding an Address document or a dict."""
	if not address:
		return ""

	def read(fieldname):
		if hasattr(address, "get"):
			return address.get(fieldname)
		return getattr(address, fieldname, None)

	return compose_street_line(read("address_line1"), read("custom_house_number"))
