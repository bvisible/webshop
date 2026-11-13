# //// Neoffice — added file (no upstream equivalent). A gift card sold without VAT pays as a payment, not as a discount (maintenance#2639).
"""A shop order paid in part by a gift card.

A card is spent in one of two ways, and which one depends on how it was SOLD (the same rule as the till's, pos_next.gift_card_vat):

- sold with VAT, or offered: a DISCOUNT on the order, as it always was (the VAT of a card sold with VAT was taken when it was sold; an
  offered card never brought money in);
- sold without VAT: a PAYMENT. The sale credited a debt account (or revenue, for a card sold before the change) and the VAT is due when the
  card buys something. A discount takes the VAT off the order a second time and leaves that debt on the books for ever.

For a payment, the order keeps its full price and VAT, and says what the card pays (`gift_card_paid_amount`). Once the order is submitted a journal
entry books the card's part: debit the account the sale credited, credit the customer, with the order as its reference, which is how ERPNext
records an advance. The invoice made from the order takes it as an advance, so it shows the full price, what the card paid, and what is left to
pay. Cancelling the journal, alone or through the order, gives the card its balance back.

The columns that say how a card was sold (`pos_next_origin`, `pos_next_sale_account`) belong to POS Next, which defines them on Coupon Code. A site
without them keeps the discount: this module answers "discount" whenever it cannot find them.
"""

import json

import frappe
from frappe import _
from frappe.utils import flt, today

# Defined by POS Next on Coupon Code. Copied on purpose: the shop must hold on a site without POS Next (see is_gift_card_coupon in cart.py).
ORIGIN = "pos_next_origin"
SALE_ACCOUNT = "pos_next_sale_account"
SOLD_WITH_VAT = "Sold with VAT"
SOLD_WITHOUT_VAT = "Sold without VAT"

# What the shop adds to a Sales Order (patches/add_gift_card_payment_fields_to_sales_order.py)
ORDER_COLUMNS = ("gift_card_paid_with", "gift_card_paid_amount", "gift_card_journal")


def order_has_the_columns() -> bool:
	return all(frappe.get_meta("Sales Order").has_field(field) for field in ORDER_COLUMNS)


def the_account_that_pays(card_name, company):
	"""The account to debit when the card pays part of an order of `company`; None when the card is spent as a discount."""
	meta = frappe.get_meta("Coupon Code")
	if not card_name or not (meta.has_field(ORIGIN) and meta.has_field(SALE_ACCOUNT)) or not order_has_the_columns():
		return None
	card = frappe.db.get_value("Coupon Code", card_name, [ORIGIN, SALE_ACCOUNT], as_dict=True)
	if not card or card.get(ORIGIN) != SOLD_WITHOUT_VAT or not card.get(SALE_ACCOUNT):
		return None
	account = frappe.db.get_value("Account", card[SALE_ACCOUNT], ["company", "disabled", "is_group", "freeze_account"], as_dict=True)
	# an account of another company's books, a group, a closed or frozen account cannot take the entry: the card is a discount
	if not account or account.company != company or account.disabled or account.is_group or account.freeze_account == "Yes":
		return None
	return card[SALE_ACCOUNT]


def was_taxed(invoice, line) -> bool:
	"""Whether the VAT was charged on a sale line: its item tax template names a rate, or leaves an account the invoice charges VAT on to the invoice's own rate."""
	try:
		rates = json.loads(line.get("item_tax_rate") or "{}")
	except ValueError:
		rates = {}
	if not isinstance(rates, dict):
		rates = {}
	if any(flt(rate) > 0 for rate in rates.values()):
		return True
	return any(row.account_head not in rates for row in invoice.get("taxes") or [] if flt(row.rate) > 0)


def origin_of_a_new_card(invoice, line) -> dict:
	"""The columns of a card the shop has just sold on `line` of `invoice`: how it was sold, and the account its sale credited.

	A card sold with VAT has had its VAT taken; one sold without keeps the account that line credited (a debt account, or revenue for an item
	not yet moved to one), which spending the card must clear. Nothing without POS Next's columns.
	"""
	meta = frappe.get_meta("Coupon Code")
	if not (meta.has_field(ORIGIN) and meta.has_field(SALE_ACCOUNT)):
		return {}
	if was_taxed(invoice, line):
		return {ORIGIN: SOLD_WITH_VAT}
	return {ORIGIN: SOLD_WITHOUT_VAT, SALE_ACCOUNT: line.get("income_account")}


def put_the_card_on_the_order(order, quotation):
	"""While the order is built from its cart, before it is saved: a card that pays by payment leaves the order at its full price.

	Returns the account the card will be debited on, None when the card stays a discount (the order is then left as it is). The cart
	itself keeps the card as a discount: what a buyer pays is what the cart says, the order and the books are what the law reads.
	"""
	code = quotation.get("gift_card_coupon")
	amount = flt(quotation.get("discount_amount"), 2)
	if not code or amount <= 0:
		return None
	account = the_account_that_pays(code, order.company)
	if not account:
		return None
	# the journal is made in the company's currency: an order in another one keeps the discount
	if order.get("currency") and order.currency != frappe.get_cached_value("Company", order.company, "default_currency"):
		return None
	order.discount_amount = 0
	order.run_method("calculate_taxes_and_totals")
	total = flt(order.get("rounded_total") or order.get("grand_total"), 2)
	order.gift_card_paid_with = code
	# a card cannot pay more than the order is worth (a journal entry against an order may not exceed its total)
	order.gift_card_paid_amount = min(amount, total)
	return account


def the_card_part(order) -> float:
	"""What the card took off an order, whichever way: the discount of the order, or the part booked by journal."""
	return flt(order.get("discount_amount"), 2) or flt(order.get("gift_card_paid_amount"), 2)


def book_the_card(order, strict=True):
	"""After the order is submitted: take the card's part off its balance and book it.

	Returns the balance left on the card, None when nothing was taken (no payment by card on this order, or it was booked already).
	Strict, a card that no longer holds the amount refuses the order. Not strict (the money was taken at a gateway already), the card gives
	what it has, the journal books that, and the shortfall goes to the Error Log with the card's own message.
	"""
	from webshop.webshop.shopping_cart import cart

	card_name = order.get("gift_card_paid_with")
	paid = flt(order.get("gift_card_paid_amount"), 2)
	if not card_name or paid <= 0 or order.get("gift_card_journal"):
		return None
	account = the_account_that_pays(card_name, order.company)
	if not account:
		message = _("The account of this gift card's sale cannot take its payment. Ask the shop.")
		if strict:
			frappe.throw(message)
		frappe.log_error("Webshop: a gift card could not be booked", f"order={order.name} card={card_name} account missing")
		return None
	card = cart._locked_gift_card(card_name)
	actual = min(paid, flt(card.gift_card_amount, 2)) if card else 0
	left = cart.spend_gift_card(card_name, paid, order.name, strict=strict)
	if left is None or actual <= 0:
		return left
	_post_the_journal(order, card_name, account, actual)
	return left


def _post_the_journal(order, card_name, account, amount):
	from erpnext.accounts.party import get_party_account

	from webshop.webshop.shopping_cart.cart import _masked_code
	from webshop.webshop.shopping_cart.shop_rights import shop_rights

	code = frappe.db.get_value("Coupon Code", card_name, "coupon_code")
	with shop_rights():
		cost_center = frappe.get_cached_value("Company", order.company, "cost_center")
		receivable = get_party_account("Customer", order.customer, order.company)
		journal = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"voucher_type": "Journal Entry",
				"company": order.company,
				"posting_date": today(),
				"user_remark": _("Gift card {0} paid {1} of order {2}").format(_masked_code(code), f"{amount:.2f}", order.name),
				"accounts": [
					{"account": account, "debit_in_account_currency": amount, "cost_center": cost_center},
					{
						"account": receivable,
						"party_type": "Customer",
						"party": order.customer,
						"credit_in_account_currency": amount,
						"reference_type": "Sales Order",
						"reference_name": order.name,
						"is_advance": "Yes",
						"cost_center": cost_center,
					},
				],
			}
		)
		journal.flags.ignore_permissions = True
		journal.insert(ignore_permissions=True)
		journal.submit()
	# the order is submitted: written straight, and with what the card really paid (a short card paid less than the cart said)
	frappe.db.set_value("Sales Order", order.name, {"gift_card_journal": journal.name, "gift_card_paid_amount": amount}, update_modified=False)
	order.gift_card_journal = journal.name
	order.gift_card_paid_amount = amount


def cancel_the_journal_of(order, method=None):
	"""`on_cancel` of a Sales Order: its card journal goes with it, and the journal gives the card back (give_the_card_back)."""
	journal = order.get("gift_card_journal")
	if not journal or frappe.db.get_value("Journal Entry", journal, "docstatus") != 1:
		return False
	from webshop.webshop.shopping_cart.shop_rights import shop_rights

	with shop_rights():
		entry = frappe.get_doc("Journal Entry", journal)
		entry.flags.ignore_permissions = True
		entry.cancel()
	return True


def give_the_card_back(journal, method=None):
	"""`on_cancel` of a Journal Entry: the card of the order it paid gets its balance back, however the journal was cancelled."""
	if not order_has_the_columns():
		return
	from webshop.webshop.shopping_cart import cart

	for order in frappe.get_all("Sales Order", filters={"gift_card_journal": journal.name}, fields=["name", "gift_card_paid_with", "gift_card_paid_amount"]):
		paid = flt(order.gift_card_paid_amount, 2)
		if not order.gift_card_paid_with or paid <= 0 or not cart._spent_on(order.gift_card_paid_with, order.name):
			continue
		card = cart._locked_gift_card(order.gift_card_paid_with)
		if not card:
			continue
		balance = flt(flt(card.gift_card_amount) + paid, 2)
		frappe.db.set_value("Coupon Code", order.gift_card_paid_with, {"gift_card_amount": balance, "used": 0}, update_modified=False)
		cart._rule_follows_the_balance(card, balance)
		frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Info",
				"reference_doctype": "Coupon Code",
				"reference_name": order.gift_card_paid_with,
				"content": _("Given back: {0}. Left on the card: {1}.").format(f"{paid:.2f}", f"{balance:.2f}") + f" ({order.name}, {journal.name})",
			}
		).insert(ignore_permissions=True)
		# the order no longer says the card paid: what it showed is not true any more, and the journal's name stays to trace it
		frappe.db.set_value("Sales Order", order.name, "gift_card_paid_amount", 0, update_modified=False)
		frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Info",
				"reference_doctype": "Sales Order",
				"reference_name": order.name,
				"content": _("The journal entry {0} that booked {1} paid by a gift card was cancelled: the card has its balance back.").format(journal.name, f"{paid:.2f}"),
			}
		).insert(ignore_permissions=True)


def pull_the_card_into_the_invoice(invoice, method=None):
	"""`before_validate` of a Sales Invoice made from a shop order: the card's journal is the advance of the order, the invoice takes it.

	ERPNext does not do it by itself when an invoice is made from an order, only when the user asks for the advances; the gateway's invoice
	asks (allocate_advances_automatically), the desk's does not. Without it the invoice would ask the customer for the whole price again.

	What an invoice can take is what no other invoice has: ERPNext points the row it allocates at that invoice (splitting the row when it
	takes only a part), and forgets the reference when that invoice is cancelled. So the rows of the journal that name the order, or nothing,
	are what is left to take, a cancelled invoice's included.
	"""
	if invoice.docstatus != 0 or invoice.get("is_return") or invoice.get("is_pos") or not order_has_the_columns():
		return
	taken = {row.reference_row for row in invoice.get("advances") or [] if row.get("reference_row")}
	left = flt(invoice.get("rounded_total") or invoice.get("grand_total"), 2)
	for order in sorted({row.sales_order for row in invoice.items if row.get("sales_order")}):
		journal = frappe.db.get_value("Sales Order", order, "gift_card_journal")
		if not journal or frappe.db.get_value("Journal Entry", journal, "docstatus") != 1:
			continue
		lines = frappe.db.sql(
			"""SELECT name, credit_in_account_currency AS credit FROM `tabJournal Entry Account`
			WHERE parent = %s AND party_type = 'Customer' AND credit_in_account_currency > 0
				AND IFNULL(reference_type, '') IN ('', 'Sales Order') AND IFNULL(reference_name, '') IN ('', %s)
			ORDER BY idx""",
			(journal, order),
			as_dict=True,
		)
		for line in lines:
			allocated = min(flt(line.credit, 2), left)
			if line.name in taken or allocated <= 0:
				continue
			invoice.append(
				"advances",
				{
					"reference_type": "Journal Entry",
					"reference_name": journal,
					"reference_row": line.name,
					"remarks": frappe.db.get_value("Journal Entry", journal, "user_remark"),
					"advance_amount": flt(line.credit),
					"allocated_amount": allocated,
					"ref_exchange_rate": 1,
				},
			)
			taken.add(line.name)
			left = flt(left - allocated, 2)
