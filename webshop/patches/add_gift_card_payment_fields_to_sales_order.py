# //// Neoffice — added file (no upstream equivalent).
# //// Sales Order.gift_card_paid_with / gift_card_paid_amount / gift_card_journal: an order paid in part by a gift card sold without VAT keeps
# //// its full price, and says which card paid, how much, and the journal entry that books it (maintenance#2639, shopping_cart/gift_card_payment.py).
# //// Named apart from Quotation.gift_card_coupon on purpose: a field of the same name would be copied onto every order made from a cart.
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

FIELDS = (
	{
		"fieldname": "gift_card_paid_with",
		"label": "Paid with Gift Card",
		"fieldtype": "Link",
		"options": "Coupon Code",
		"insert_after": "coupon_code",
	},
	{
		"fieldname": "gift_card_paid_amount",
		"label": "Paid by Gift Card",
		"fieldtype": "Currency",
		"options": "currency",
		"insert_after": "gift_card_paid_with",
	},
	{
		"fieldname": "gift_card_journal",
		"label": "Gift Card Journal Entry",
		# Data, not a Link: a link from a submitted order would forbid cancelling the journal on its own (a back link blocks the cancellation)
		"fieldtype": "Data",
		"insert_after": "gift_card_paid_amount",
	},
)


def execute():
	"""Three read-only fields on Sales Order, shown only on an order a gift card paid in part."""
	for field in FIELDS:
		if frappe.db.exists("Custom Field", {"dt": "Sales Order", "fieldname": field["fieldname"]}):
			continue
		create_custom_field(
			"Sales Order",
			{
				**field,
				"read_only": 1,
				"no_copy": 1,
				"print_hide": 1,
				"translatable": 0,
				"depends_on": "eval:doc.gift_card_paid_with",
			},
		)
