# //// Neoffice — added file (no upstream equivalent). The brand of one reseller: logo, colours,
# //// contact details and the markup they apply to the prices of their catalogues (2026-10-30).
import frappe
from frappe import _
from frappe.model.document import Document

from webshop.webshop.catalogue import brand
from webshop.webshop.catalogue.refusals import brand_message

BRAND_FIELDS = (
	*brand.TEXT_LIMITS,
	brand.ADDRESS_FIELD,
	*brand.COLOUR_FIELDS,
	"default_markup_percent",
	"price_rounding",
	"price_display",
	"vat_rate",
)


class ResellerCatalogueProfile(Document):
	def validate(self):
		"""The same checks as the account page, for a profile written at the desk or by a script."""
		values = {}
		for field in BRAND_FIELDS:
			value = self.get(field)
			# an empty colour, markup, rounding… takes the neutral default rather than being refused
			if value in (None, "") and field in brand.DEFAULTS:
				value = brand.DEFAULTS[field]
			values[field] = value
		try:
			clean = brand.clean_brand(values)
		except brand.BrandRefused as refusal:
			frappe.throw(brand_message(refusal.field, refusal.reason), title=_("Brand"))
		self.update(clean)
		rows = [
			{"rule_type": row.rule_type, "target": row.target, "markup_percent": row.markup_percent}
			for row in self.get("markup_rules") or []
		]
		try:
			rules = brand.clean_brand({"markup_rules": rows})["markup_rules"]
		except brand.BrandRefused as refusal:
			frappe.throw(brand_message(refusal.field, refusal.reason), title=_("Brand"))
		for row, rule in zip(self.get("markup_rules") or [], rules, strict=True):
			row.target = rule["target"]
		if not self.brand_name:
			self.brand_name = frappe.db.get_value("Customer", self.customer, "customer_name") or self.customer


def application_defaults(customer):
	"""The brand fields the customer's approved account request already holds.

	A reseller filled in their company name, VAT number, website, address, phone and e-mail to be
	accepted: the brand form starts from that instead of an empty page. Each value is checked like
	any other; one that does not pass (a website typed as a sentence) is left out, not refused.
	"""
	if not frappe.db.exists("DocType", "B2B Account Request"):
		return {}
	request = frappe.db.get_value(
		"B2B Account Request",
		{"customer": customer, "status": "Approved"},
		[
			"company_name",
			"tax_id",
			"website",
			"email",
			"phone",
			"address_line1",
			"house_number",
			"pincode",
			"city",
			"country",
		],
		as_dict=True,
		order_by="modified desc",
	)
	if not request:
		return {}
	address = "\n".join(
		line
		for line in (
			f"{request.address_line1 or ''} {request.house_number or ''}".strip(),
			f"{request.pincode or ''} {request.city or ''}".strip(),
			request.country or "",
		)
		if line
	)
	found = {
		"brand_name": request.company_name,
		"vat_number": request.tax_id,
		"contact_website": request.website,
		"contact_email": request.email,
		"contact_phone": request.phone,
		"contact_address": address,
	}
	kept = {}
	for field, value in found.items():
		try:
			kept.update(brand.clean_brand({field: value}))
		except brand.BrandRefused:
			continue
	return {field: value for field, value in kept.items() if value}
