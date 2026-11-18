# //// Neoffice — added file (no upstream equivalent).
"""A gift card the shop sold goes with the sale that created it (maintenance#2816, the shop's side of #2725).

The shop creates its cards when their sale is paid (cart.create_gift_cards_from_invoice) and ties each one to the
sale by `sales_invoice`; nothing took them back. A sale of a card cancelled, or taken back by a credit note, gave the
customer the money back and left the card full, to spend. The till had the same defect, fixed in POS Next
(pos_next/api/gift_cards.py, 34e8738d): the rule is the till's, so that the two say the same.

- A card nobody has spent goes with its sale (cancel or credit note): its balance to 0 and marked used, a comment on
  the card saying which document took it. Its Pricing Rule is left alone: the shop's cards of one amount share theirs,
  and disabling it would take every card of that amount.
- A card already spent, even in part, stops the cancel or the credit note and keeps what it holds: what to give back
  for the rest is the business's decision (asked to Jérémy, as for #2725), not the shop's.
- A credit note that takes back one card of several takes one of its amount, an unspent one.
- A cancelled credit note gives back the cards it had taken.
- An invoice amended from a cancelled sale keeps the codes of its cards on its line, so the shop makes no new card for
  it: once paid, it takes back the cards the cancel had voided (give_the_cards_to_the_amendment).

The comments end with a reference that is read back whatever the language of their sentence, as the shop does for a
card spent on an order (`(<order>)`, cart._spent_on): `(void <document>)` and `(back <document>)`.
"""

import json
import re

import frappe
from frappe import _
from frappe.utils import cint, flt

from webshop.webshop.shopping_cart.cart import is_gift_card_item
from webshop.webshop.utils.utils import format_currency_value

_CARD_FIELDS = ["name", "coupon_code", "gift_card_amount", "used"]
_MARK = re.compile(r"\((void|back) ([^()]+)\)")


def on_submit(doc, method=None):
	"""`on_submit` of Sales Invoice: a credit note that takes back the sale of a card takes the card back too."""
	if doc.get("is_return") and doc.get("return_against"):
		_take_back_the_cards_of_a_return(doc)


def on_cancel(doc, method=None):
	"""`on_cancel` of Sales Invoice: a cancelled sale takes its cards back, a cancelled credit note gives back the ones
	it had taken."""
	if doc.get("is_return") and doc.get("return_against"):
		_give_back_the_cards_of_a_cancelled_return(doc)
	else:
		_take_back_the_cards_of_a_cancelled_sale(doc)


# ---------------------------------------------------------------------------------------------------------------
# The cards of a sale
# ---------------------------------------------------------------------------------------------------------------


def _card_lines(invoice):
	"""(value, codes) of each line of `invoice` that sells gift cards: what one card of the line is worth, and the codes
	of its cards when the line kept them (cart writes them on the line since #953)."""
	lines = []
	for row in invoice.get("items") or []:
		if not row.get("item_code") or not is_gift_card_item(row.item_code):
			continue
		try:
			data = json.loads(row.get("gift_card_data") or "{}")
		except (TypeError, ValueError):
			data = {}
		codes = data.get("codes") if isinstance(data, dict) else None
		lines.append(
			(
				abs(flt(row.get("rate"), 2)),
				[code for code in (codes or []) if isinstance(code, str)],
				abs(cint(row.get("qty"))),
			)
		)
	return lines


def _cards_created_by(sale):
	"""The gift cards `sale` created, each under its row's lock, with what it was worth when it was sold and the
	documents that took it back and have not given it back."""
	if not sale or not sale.get("name"):
		return []
	lines = _card_lines(sale)
	by_code = {code: value for value, codes, _qty in lines for code in codes}
	values = sorted({value for value, _codes, _qty in lines})
	cards = []
	for name in frappe.get_all(
		"Coupon Code",
		filters={"sales_invoice": sale.name, "coupon_type": "Gift Card"},
		pluck="name",
		order_by="creation asc",
	):
		card = frappe.db.get_value("Coupon Code", name, _CARD_FIELDS, as_dict=True, for_update=True)
		card.value = by_code.get(card.coupon_code)
		if card.value is None:
			# A line of before #953 kept no codes: a balance that is one of the values the sale sold is that value
			balance = flt(card.gift_card_amount, 2)
			card.value = next((value for value in values if abs(value - balance) < 0.01), max(values or [0]))
		card.taken_by = _open_marks(name)
		cards.append(card)
	return cards


def _open_marks(card_name):
	"""The documents that took the card back and have not given it back, read from the card's comments in their
	order."""
	taken = []
	for content in frappe.get_all(
		"Comment",
		filters={"reference_doctype": "Coupon Code", "reference_name": card_name, "comment_type": "Info"},
		or_filters=[["content", "like", "%(void %"], ["content", "like", "%(back %"]],
		pluck="content",
		order_by="creation asc",
	):
		for kind, document in _MARK.findall(content or ""):
			if kind == "void" and document not in taken:
				taken.append(document)
			elif kind == "back" and document in taken:
				taken.remove(document)
	return taken


def _unspent(card):
	return flt(card.gift_card_amount) >= flt(card.value) - 0.005


def _card_units_returned(credit_note):
	"""The value of each card a credit note takes back, one entry per card."""
	units = []
	for value, _codes, qty in _card_lines(credit_note):
		units.extend([value] * qty)
	return units


# ---------------------------------------------------------------------------------------------------------------
# Taking a card back, and giving it back
# ---------------------------------------------------------------------------------------------------------------


def _comment(card, sentence, mark):
	frappe.get_doc(
		{
			"doctype": "Comment",
			"comment_type": "Info",
			"reference_doctype": "Coupon Code",
			"reference_name": card.name,
			# the reference _open_marks reads back, whatever the language of the sentence
			"content": f"{sentence} {mark}",
		}
	).insert(ignore_permissions=True)


def _void(card, document, sentence):
	# The balance and the used mark, as a card spent to nothing has them (cart.settle_till_card): never the Pricing
	# Rule, which every shop card of this amount shares
	frappe.db.set_value("Coupon Code", card.name, {"gift_card_amount": 0, "used": 1}, update_modified=False)
	_comment(card, sentence, f"(void {document})")


def _restore(card, document, sentence):
	frappe.db.set_value(
		"Coupon Code", card.name, {"gift_card_amount": flt(card.value, 2), "used": 0}, update_modified=False
	)
	_comment(card, sentence, f"(back {document})")


def _refuse_a_spent_card(card, invoice):
	currency = invoice.get("currency")
	frappe.throw(
		_(
			"Gift card {0} has already been used: {1} of {2} is left on it. The sale that created it cannot be"
			" cancelled or returned while the card holds less than it was sold for."
		).format(
			card.coupon_code or card.name,
			format_currency_value(card.gift_card_amount, currency=currency),
			format_currency_value(card.value, currency=currency),
		),
		title=_("Gift card already used"),
	)


def _take_back_the_cards_of_a_cancelled_sale(sale):
	cards = [card for card in _cards_created_by(sale) if not card.taken_by]
	for card in cards:
		if not _unspent(card):
			_refuse_a_spent_card(card, sale)
	sentence = _("Voided: the sale {0} that created this gift card was cancelled.").format(sale.name)
	for card in cards:
		_void(card, sale.name, sentence)


def _take_back_the_cards_of_a_return(credit_note):
	original = frappe.get_doc(credit_note.doctype, credit_note.return_against)
	units = _card_units_returned(credit_note)
	pool = [card for card in _cards_created_by(original) if not card.taken_by]
	if not pool or not units:
		return
	sentence = _("Voided: the credit note {0} took back the sale {1} that created this gift card.").format(
		credit_note.name, original.name
	)
	for value in units:
		same = [card for card in pool if abs(flt(card.value) - value) < 0.01] or pool
		if not same:
			return
		unspent = [card for card in same if _unspent(card)]
		if not unspent:
			_refuse_a_spent_card(same[0], credit_note)
		card = unspent[0]
		pool.remove(card)
		_void(card, credit_note.name, sentence)


def _give_back_the_cards_of_a_cancelled_return(credit_note):
	original = frappe.get_doc(credit_note.doctype, credit_note.return_against)
	sentence = _("Given back: the credit note {0} that had voided this gift card was cancelled.").format(
		credit_note.name
	)
	for card in _cards_created_by(original):
		if credit_note.name in card.taken_by:
			_restore(card, credit_note.name, sentence)



def give_the_cards_to_the_amendment(invoice):
	"""Called by cart.create_gift_cards_from_invoice once `invoice` is paid: when it was amended from a sale whose cancel
	voided its cards, those cards come back to it, whole and tied to it, instead of none (its line names their codes,
	which stops a new card being made)."""
	cancelled = invoice.get("amended_from")
	if not cancelled or not frappe.db.exists("Sales Invoice", {"name": cancelled, "docstatus": 2}):
		return
	sentence = _("Given back: the invoice {0} amended from the cancelled sale {1} holds this gift card now.").format(
		invoice.name, cancelled
	)
	for card in _cards_created_by(frappe.get_doc("Sales Invoice", cancelled)):
		if cancelled in card.taken_by:
			_restore(card, cancelled, sentence)
			frappe.db.set_value("Coupon Code", card.name, "sales_invoice", invoice.name, update_modified=False)
