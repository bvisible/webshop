# //// Neoffice — added file (no upstream equivalent).
"""A gift card sold without VAT pays an order as a payment, not as a discount (maintenance#2639).

A discount takes the VAT off the order a second time (the card was sold without VAT, so its VAT is due when it buys something) and leaves the
debt account the card was sold on credited for ever. A payment keeps the order at its full price, and a journal entry books the card's part:
debit the account the sale credited, credit the customer, with the order as reference, which is how ERPNext records an advance.

Two kinds of test. The decisions (which way a card is spent, what the order says, how a new card is described) are checked on stand-ins. The books
are checked on real documents, on a site where POS Next defines how a card was sold: the full price, the card's journal, the invoice that takes it
as an advance, the payment of what is left, then the cancellation in every order the desk allows, each leaving every account at zero.
"""

import json
import unittest
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, nowdate

from webshop.webshop.shopping_cart import cart
from webshop.webshop.shopping_cart import gift_card_payment as card_payment

CARD = "CARD-2639"
COMPANY = "Test Company 2639"
ACCOUNT = "2020 - Gift cards - T2639"


def _card_columns(origin="Sold without VAT", account=ACCOUNT):
	return frappe._dict({card_payment.ORIGIN: origin, card_payment.SALE_ACCOUNT: account})


class _Meta:
	def __init__(self, *fields):
		self.fields = fields

	def has_field(self, fieldname):
		return fieldname in self.fields


class _Order(frappe._dict):
	"""An order being built: it recalculates to the full price when asked."""

	def run_method(self, name):
		self.rounded_total = self.get("full_price")


class TestWhichWayACardIsSpent(FrappeTestCase):
	def decide(self, card=None, account=None, columns=True, order_columns=True):
		card = _card_columns() if card is None else card
		account = frappe._dict(company=COMPANY, disabled=0, is_group=0, freeze_account="No") if account is None else account
		meta = {
			"Coupon Code": _Meta(card_payment.ORIGIN, card_payment.SALE_ACCOUNT) if columns else _Meta(),
			"Sales Order": _Meta(*card_payment.ORDER_COLUMNS) if order_columns else _Meta(),
		}

		def get_value(doctype, name, fieldname=None, **kwargs):
			return {"Coupon Code": card, "Account": account}.get(doctype)

		with (
			mock.patch.object(card_payment.frappe, "get_meta", side_effect=lambda doctype: meta[doctype]),
			mock.patch.object(card_payment.frappe.db, "get_value", side_effect=get_value),
		):
			return card_payment.the_account_that_pays(CARD, COMPANY)

	def test_a_card_sold_without_vat_pays_on_the_account_its_sale_credited(self):
		self.assertEqual(self.decide(), ACCOUNT)

	def test_a_card_sold_with_vat_or_offered_stays_a_discount(self):
		self.assertIsNone(self.decide(card=_card_columns(origin="Sold with VAT")))
		self.assertIsNone(self.decide(card=_card_columns(origin="Given for free")))
		self.assertIsNone(self.decide(card=_card_columns(origin=None)), "a card whose origin was never said keeps the old way")

	def test_a_card_with_no_sale_account_stays_a_discount(self):
		self.assertIsNone(self.decide(card=_card_columns(account=None)))

	def test_an_account_that_cannot_take_the_entry_leaves_the_card_a_discount(self):
		for change in ({"company": "Another company"}, {"disabled": 1}, {"is_group": 1}, {"freeze_account": "Yes"}):
			account = frappe._dict({"company": COMPANY, "disabled": 0, "is_group": 0, "freeze_account": "No", **change})
			self.assertIsNone(self.decide(account=account), change)

	def test_a_site_without_the_columns_keeps_the_discount(self):
		self.assertIsNone(self.decide(columns=False))
		self.assertIsNone(self.decide(order_columns=False), "before the patch made the order's fields")


class TestWhatTheOrderSays(FrappeTestCase):
	def put(self, discount, full_price, account=ACCOUNT, code=CARD):
		order = _Order(company=COMPANY, discount_amount=discount, full_price=full_price)
		quotation = frappe._dict(gift_card_coupon=code, discount_amount=discount)
		with mock.patch.object(card_payment, "the_account_that_pays", return_value=account):
			return order, card_payment.put_the_card_on_the_order(order, quotation)

	def test_the_order_keeps_its_full_price_and_says_what_the_card_pays(self):
		order, account = self.put(discount=40, full_price=108.10)

		self.assertEqual(account, ACCOUNT)
		self.assertEqual(order.discount_amount, 0)
		self.assertEqual((order.gift_card_paid_with, order.gift_card_paid_amount), (CARD, 40))

	def test_a_card_cannot_pay_more_than_the_order_is_worth(self):
		order, _ = self.put(discount=130, full_price=108.05)

		self.assertEqual(order.gift_card_paid_amount, 108.05)

	def test_a_card_that_stays_a_discount_leaves_the_order_as_the_cart_made_it(self):
		order, account = self.put(discount=40, full_price=108.10, account=None)

		self.assertIsNone(account)
		self.assertEqual(order.discount_amount, 40)
		self.assertNotIn("gift_card_paid_amount", order)

	def test_an_order_in_another_currency_than_the_companys_keeps_the_discount(self):
		order = _Order(company=COMPANY, discount_amount=40, full_price=108.10, currency="EUR")
		quotation = frappe._dict(gift_card_coupon=CARD, discount_amount=40)
		with (
			mock.patch.object(card_payment, "the_account_that_pays", return_value=ACCOUNT),
			mock.patch.object(card_payment.frappe, "get_cached_value", return_value="CHF"),
		):
			account = card_payment.put_the_card_on_the_order(order, quotation)

		self.assertIsNone(account)
		self.assertEqual(order.discount_amount, 40)

	def test_no_card_or_nothing_taken_changes_nothing(self):
		order = _Order(company=COMPANY, discount_amount=0, full_price=108.10)
		self.assertIsNone(card_payment.put_the_card_on_the_order(order, frappe._dict(gift_card_coupon=CARD, discount_amount=0)))
		self.assertIsNone(card_payment.put_the_card_on_the_order(order, frappe._dict(gift_card_coupon="", discount_amount=40)))

	def test_the_part_of_the_card_is_the_discount_or_the_payment(self):
		self.assertEqual(card_payment.the_card_part(frappe._dict(discount_amount=30, gift_card_paid_amount=0)), 30)
		self.assertEqual(card_payment.the_card_part(frappe._dict(discount_amount=0, gift_card_paid_amount=40)), 40)
		self.assertEqual(card_payment.the_card_part(frappe._dict(discount_amount=0)), 0)


class TestHowANewCardIsDescribed(FrappeTestCase):
	def describe(self, line, taxes=(), columns=True):
		invoice = frappe._dict(taxes=[frappe._dict(account_head=account, rate=rate) for account, rate in taxes])
		meta = _Meta(card_payment.ORIGIN, card_payment.SALE_ACCOUNT) if columns else _Meta()
		with mock.patch.object(card_payment.frappe, "get_meta", return_value=meta):
			return card_payment.origin_of_a_new_card(invoice, frappe._dict(**line))

	def test_a_card_sold_on_a_line_with_a_rate_was_taxed(self):
		rates = json.dumps({"VAT 8.1%": 8.1, "VAT 2.6%": 0})
		seen = self.describe({"item_tax_rate": rates, "income_account": "3200 - Sales"})

		self.assertEqual(seen, {card_payment.ORIGIN: "Sold with VAT"})

	def test_a_card_sold_on_a_line_with_no_rate_was_not_and_keeps_the_account_it_credited(self):
		seen = self.describe({"item_tax_rate": json.dumps({"VAT 8.1%": 0}), "income_account": ACCOUNT})

		self.assertEqual(seen, {card_payment.ORIGIN: "Sold without VAT", card_payment.SALE_ACCOUNT: ACCOUNT})

	def test_a_line_with_no_template_is_charged_at_the_rate_of_the_invoice(self):
		taxed = self.describe({"item_tax_rate": None, "income_account": "3200 - Sales"}, taxes=[("VAT 8.1%", 8.1)])
		untaxed = self.describe({"item_tax_rate": None, "income_account": ACCOUNT}, taxes=[("VAT 8.1%", 0)])

		self.assertEqual(taxed[card_payment.ORIGIN], "Sold with VAT")
		self.assertEqual(untaxed[card_payment.ORIGIN], "Sold without VAT")

	def test_a_template_that_leaves_the_invoice_account_out_does_not_exempt_the_line(self):
		seen = self.describe({"item_tax_rate": json.dumps({"VAT 2.6%": 0}), "income_account": "3200 - Sales"}, taxes=[("VAT 8.1%", 8.1)])

		self.assertEqual(seen[card_payment.ORIGIN], "Sold with VAT")

	def test_a_site_without_the_columns_describes_nothing(self):
		self.assertEqual(self.describe({"item_tax_rate": None, "income_account": ACCOUNT}, columns=False), {})


class TestTheBalanceOfAnOrderPaidByJournal(FrappeTestCase):
	def test_the_confirmation_page_reads_what_the_card_paid_from_the_order(self):
		real = frappe.db.get_value
		order = frappe._dict(order_type="Shopping Cart", discount_amount=0, currency="CHF", gift_card_paid_with=CARD, gift_card_paid_amount=40.0)
		card = frappe._dict(coupon_code="GC-ABCD-9876", gift_card_amount=60.0, valid_upto="2027-12-31")

		def get_value(doctype, *args, **kwargs):
			fieldname = args[1] if len(args) > 1 else kwargs.get("fieldname")
			if doctype == "Sales Order":
				return frappe._dict({field: order.get(field) for field in fieldname})
			if doctype == "Sales Order Item":
				return "QTN-2639"
			if doctype == "Coupon Code":
				return frappe._dict({field: card.get(field) for field in fieldname})
			return real(doctype, *args, **kwargs)

		with (
			mock.patch.object(cart.frappe.db, "get_value", side_effect=get_value),
			mock.patch.object(cart, "_spent_on", return_value=True),
			mock.patch.object(card_payment, "order_has_the_columns", return_value=True),
		):
			seen = cart.gift_card_of_order("SO-2639")

		self.assertEqual((seen.spent, seen.left), (40.0, 60.0))
		self.assertNotIn("ABCD", seen.code)


def _the_site_has_the_columns():
	return all(frappe.get_meta("Coupon Code").has_field(field) for field in (card_payment.ORIGIN, card_payment.SALE_ACCOUNT)) and card_payment.order_has_the_columns()


def _a_company_with_a_debt_account():
	"""The shop's company and a liability account a sale could have credited, or nothing."""
	company = frappe.db.get_single_value("Webshop Settings", "company") or frappe.db.get_value("Company", {}, "name")
	if not company:
		return None, None
	account = frappe.db.get_value(
		"Account",
		{"company": company, "root_type": "Liability", "is_group": 0, "disabled": 0, "account_type": ["in", ["", "Income Account"]]},
		"name",
	)
	return company, account


@unittest.skipUnless(_the_site_has_the_columns(), "POS Next does not describe how a card was sold on this site")
class TestTheBooksOfAnOrderPaidInPartByACard(FrappeTestCase):
	PRICE = 108.10  # VAT included: 100.00 and 8.10
	CARD_AMOUNT = 40.00

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.company, cls.debt_account = _a_company_with_a_debt_account()
		if not cls.debt_account or not frappe.db.exists("Item Tax Template", {"company": cls.company, "name": ["like", "%8.1%Sales%"]}):
			raise unittest.SkipTest("no debt account or no 8.1 % sales template on this site")
		cls.tax_template = frappe.db.get_value("Item Tax Template", {"company": cls.company, "name": ["like", "%8.1%Sales%"]}, "name")

	def setUp(self):
		frappe.set_user("Administrator")
		self.customer = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": "_Test Card 2639 %s" % frappe.generate_hash(length=6),
				"customer_type": "Individual",
				"customer_group": frappe.db.get_value("Customer Group", {"is_group": 0}, "name"),
				"territory": frappe.db.get_value("Territory", {"is_group": 0}, "name"),
				"email_id": "card-2639-%s@yopmail.com" % frappe.generate_hash(length=6),
			}
		).insert(ignore_permissions=True)
		self.item = self._item()
		self.card = self._card(self.CARD_AMOUNT)

	def _item(self):
		code = "_Test Card 2639 item"
		if not frappe.db.exists("Item", code):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": code,
					"item_name": code,
					"item_group": frappe.db.get_value("Item Group", {"is_group": 0}, "name"),
					"stock_uom": frappe.db.get_value("UOM", {}, "name"),
					"is_stock_item": 0,
					"is_sales_item": 1,
				}
			).insert(ignore_permissions=True)
		return code

	def _card(self, amount, origin="Sold without VAT", account=None):
		return frappe.get_doc(
			{
				"doctype": "Coupon Code",
				"coupon_name": "Test card 2639 %s" % frappe.generate_hash(length=6),
				"coupon_type": "Gift Card",
				"pricing_rule": cart._gift_card_rule(amount),
				"customer": self.customer.name,
				"coupon_code": frappe.generate_hash(length=10).upper(),
				"valid_from": nowdate(),
				"valid_upto": add_days(nowdate(), 30),
				"maximum_use": 9999,
				"used": 0,
				"gift_card_amount": amount,
				card_payment.ORIGIN: origin,
				card_payment.SALE_ACCOUNT: account or self.debt_account,
			}
		).insert(ignore_permissions=True)

	def _order(self, card_pays=True, discount=0, qty=1, price=None):
		from erpnext.controllers.accounts_controller import get_taxes_and_charges

		template = frappe.db.get_value("Sales Taxes and Charges Template", {"company": self.company, "is_default": 1}, "name")
		order = frappe.get_doc(
			{
				"doctype": "Sales Order",
				"customer": self.customer.name,
				"company": self.company,
				"order_type": "Shopping Cart",
				"transaction_date": nowdate(),
				"delivery_date": nowdate(),
				"taxes_and_charges": template,
				"items": [{"item_code": self.item, "qty": qty, "rate": price or self.PRICE, "delivery_date": nowdate(), "item_tax_template": self.tax_template}],
			}
		)
		for row in get_taxes_and_charges("Sales Taxes and Charges Template", template):
			order.append("taxes", row)
		if discount:
			order.discount_amount = discount
			order.apply_discount_on = "Grand Total"
		if card_pays:
			quotation = frappe._dict(gift_card_coupon=self.card.name, discount_amount=self.CARD_AMOUNT)
			order.insert(ignore_permissions=True)
			order.discount_amount = self.CARD_AMOUNT
			card_payment.put_the_card_on_the_order(order, quotation)
			order.save(ignore_permissions=True)
		else:
			order.insert(ignore_permissions=True)
		order.submit()
		return order

	def _ledger(self, *vouchers):
		rows = frappe.db.sql(
			"select account, round(sum(debit) - sum(credit), 2) from `tabGL Entry` where voucher_no in %s group by account", (tuple(vouchers),), as_list=True
		)
		return {account: flt(net) for account, net in rows}

	def _sum_of(self, books, kind, value):
		return round(sum(net for account, net in books.items() if frappe.db.get_value("Account", account, kind) == value), 2)

	def _invoice_of(self, order):
		from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice

		invoice = make_sales_invoice(order.name)
		invoice.insert(ignore_permissions=True)
		invoice.submit()
		return invoice

	def _pay(self, invoice):
		from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

		entry = get_payment_entry("Sales Invoice", invoice.name)
		entry.reference_no = "TEST-2639"
		entry.reference_date = nowdate()
		entry.insert(ignore_permissions=True)
		entry.submit()
		return entry

	def test_the_order_keeps_its_full_price_and_vat(self):
		order = self._order()

		self.assertEqual((order.net_total, order.total_taxes_and_charges, order.grand_total), (100.0, 8.1, 108.1))
		self.assertEqual((order.discount_amount, order.gift_card_paid_amount, order.gift_card_paid_with), (0, 40.0, self.card.name))

	def test_booking_takes_the_card_off_and_books_the_part_the_card_paid(self):
		order = self._order()

		left = card_payment.book_the_card(order)

		self.assertEqual(left, 0)
		journal = frappe.get_doc("Journal Entry", order.gift_card_journal)
		self.assertEqual(journal.docstatus, 1)
		self.assertEqual(self._ledger(journal.name), {self.debt_account: 40.0, journal.accounts[1].account: -40.0})
		self.assertEqual(frappe.db.get_value("Sales Order", order.name, "advance_paid"), 40.0)
		self.assertEqual(frappe.db.get_value("Coupon Code", self.card.name, "used"), 1, "a card paid in full is used up")

	def test_the_invoice_takes_the_card_as_an_advance_and_asks_for_the_rest(self):
		order = self._order()
		card_payment.book_the_card(order)

		invoice = self._invoice_of(order)

		self.assertEqual((invoice.net_total, invoice.total_taxes_and_charges, invoice.grand_total), (100.0, 8.1, 108.1))
		self.assertEqual([(row.reference_name, row.allocated_amount) for row in invoice.advances], [(order.gift_card_journal, 40.0)])
		self.assertEqual((invoice.total_advance, invoice.outstanding_amount), (40.0, 68.1))

	def test_what_is_left_is_paid_and_the_card_leaves_no_debt_behind(self):
		order = self._order()
		card_payment.book_the_card(order)
		invoice = self._invoice_of(order)
		payment = self._pay(invoice)

		self.assertEqual(payment.paid_amount, 68.1)
		books = self._ledger(order.gift_card_journal, invoice.name, payment.name)
		# VAT and sales at the full price; the debt account debited by what the card paid; the customer's account is back to zero
		self.assertEqual(books.get(self.debt_account), 40.0)
		self.assertEqual(self._sum_of(books, "root_type", "Income"), -100.0)
		self.assertEqual(self._sum_of(books, "account_type", "Tax"), -8.1)
		self.assertEqual(self._sum_of(books, "account_type", "Receivable"), 0)
		self.assertEqual(self._sum_of(books, "account_type", "Bank"), 68.1)

	def test_the_desk_invoice_without_help_takes_the_advance_too(self):
		order = self._order()
		card_payment.book_the_card(order)
		from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice

		invoice = make_sales_invoice(order.name)
		self.assertFalse(invoice.advances, "ERPNext does not pull the advance when the invoice is made")
		invoice.insert(ignore_permissions=True)

		self.assertEqual(invoice.outstanding_amount, 68.1, "the hook pulls it at validation")

	def test_the_invoice_is_not_given_a_journal_twice(self):
		# two units, invoiced in two times: the card paid the first invoice, the second owes all its price
		order = self._order(qty=2)
		card_payment.book_the_card(order)
		from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice

		first = make_sales_invoice(order.name)
		first.items[0].qty = 1
		first.run_method("calculate_taxes_and_totals")
		first.insert(ignore_permissions=True)
		first.submit()
		second = make_sales_invoice(order.name)
		card_payment.pull_the_card_into_the_invoice(second)

		self.assertEqual((first.total_advance, first.outstanding_amount), (40.0, 68.1))
		self.assertFalse(second.advances, "the journal is allocated to the first invoice")

	def test_a_card_bigger_than_the_first_invoice_pays_the_rest_of_it_on_the_next(self):
		# 2 x 25.00: the card (40.00) pays the whole first invoice and 15.00 of the second
		order = self._order(qty=2, price=25.0)
		card_payment.book_the_card(order)
		from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice

		first = make_sales_invoice(order.name)
		first.items[0].qty = 1
		first.run_method("calculate_taxes_and_totals")
		first.insert(ignore_permissions=True)
		first.submit()
		second = make_sales_invoice(order.name)
		second.insert(ignore_permissions=True)

		self.assertEqual((first.total_advance, first.outstanding_amount), (25.0, 0))
		self.assertEqual((second.total_advance, second.outstanding_amount), (15.0, 10.0))

	def test_an_invoice_made_again_after_a_cancellation_takes_the_card_again(self):
		order = self._order()
		card_payment.book_the_card(order)
		first = self._invoice_of(order)
		frappe.get_doc("Sales Invoice", first.name).cancel()
		from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice

		again = make_sales_invoice(order.name)
		again.insert(ignore_permissions=True)

		self.assertEqual((again.total_advance, again.outstanding_amount), (40.0, 68.1), "ERPNext forgets which order the journal paid when its invoice is cancelled")

	def test_the_pieces_a_cancelled_invoice_leaves_of_a_card_are_taken_together(self):
		# 2 x 25.00, the card (40.00) split in two rows by the first invoice, which is then cancelled: both pieces are free again
		order = self._order(qty=2, price=25.0)
		card_payment.book_the_card(order)
		from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice

		first = make_sales_invoice(order.name)
		first.items[0].qty = 1
		first.run_method("calculate_taxes_and_totals")
		first.insert(ignore_permissions=True)
		first.submit()
		frappe.get_doc("Sales Invoice", first.name).cancel()
		again = make_sales_invoice(order.name)
		again.insert(ignore_permissions=True)

		self.assertEqual((again.total_advance, again.outstanding_amount), (40.0, 10.0))
		self.assertEqual(len(again.advances), 2, "the two rows the journal was split into")

	def test_the_pieces_of_a_card_are_taken_only_up_to_the_total_of_the_invoice(self):
		order = self._order(qty=2, price=25.0)
		card_payment.book_the_card(order)
		from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice

		first = make_sales_invoice(order.name)
		first.items[0].qty = 1
		first.run_method("calculate_taxes_and_totals")
		first.insert(ignore_permissions=True)
		first.submit()
		frappe.get_doc("Sales Invoice", first.name).cancel()
		again = make_sales_invoice(order.name)
		again.items[0].qty = 1
		again.run_method("calculate_taxes_and_totals")
		again.insert(ignore_permissions=True)

		self.assertEqual((again.total_advance, again.outstanding_amount), (25.0, 0))

	def test_cancelling_in_the_order_of_the_desk_leaves_every_account_at_zero_and_gives_the_card_back(self):
		order = self._order()
		card_payment.book_the_card(order)
		invoice = self._invoice_of(order)
		payment = self._pay(invoice)
		journal = order.gift_card_journal

		payment.cancel()
		frappe.get_doc("Sales Invoice", invoice.name).cancel()
		frappe.get_doc("Sales Order", order.name).cancel()

		self.assertEqual(frappe.db.get_value("Journal Entry", journal, "docstatus"), 2, "the order took its card journal with it")
		self.assertEqual(frappe.db.get_value("Coupon Code", self.card.name, ["gift_card_amount", "used"], as_dict=True), {"gift_card_amount": 40.0, "used": 0})
		self.assertTrue(all(value == 0 for value in self._ledger(journal, invoice.name, payment.name).values()))

	def test_cancelling_the_journal_alone_reopens_the_debt_and_gives_the_card_back_once(self):
		order = self._order()
		card_payment.book_the_card(order)
		invoice = self._invoice_of(order)
		self._pay(invoice)

		frappe.get_doc("Journal Entry", order.gift_card_journal).cancel()

		self.assertEqual(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount"), 40.0, "the customer owes the card's part again")
		self.assertEqual(frappe.db.get_value("Coupon Code", self.card.name, "gift_card_amount"), 40.0)
		self.assertEqual(frappe.db.get_value("Sales Order", order.name, "gift_card_paid_amount"), 0, "the order no longer says the card paid")

		# the order is then cancelled (after its invoice): the journal is already gone, the card is not given back a second time
		frappe.get_doc("Sales Invoice", invoice.name).cancel()
		frappe.get_doc("Sales Order", order.name).cancel()
		self.assertEqual(frappe.db.get_value("Coupon Code", self.card.name, "gift_card_amount"), 40.0)

	def test_a_card_that_holds_less_than_the_cart_said_pays_what_it_has_when_the_money_is_taken(self):
		order = self._order()
		frappe.db.set_value("Coupon Code", self.card.name, "gift_card_amount", 25.0)

		card_payment.book_the_card(order, strict=False)

		self.assertEqual(frappe.db.get_value("Sales Order", order.name, "gift_card_paid_amount"), 25.0)
		self.assertEqual(frappe.db.get_value("Journal Entry Account", {"parent": order.gift_card_journal, "account": self.debt_account}, "debit"), 25.0)

	def test_a_card_that_holds_less_than_the_cart_said_refuses_the_order_on_account(self):
		order = self._order()
		frappe.db.set_value("Coupon Code", self.card.name, "gift_card_amount", 25.0)

		with self.assertRaises(frappe.ValidationError):
			card_payment.book_the_card(order, strict=True)
		self.assertFalse(frappe.db.get_value("Sales Order", order.name, "gift_card_journal"))

	def test_an_order_that_has_its_journal_is_never_booked_again_whatever_the_card_says(self):
		order = self._order()
		card_payment.book_the_card(order)

		with mock.patch.object(cart, "spend_gift_card", return_value=10.0) as spend:
			self.assertIsNone(card_payment.book_the_card(order))
		spend.assert_not_called()

	def test_an_order_is_booked_once(self):
		order = self._order()
		card_payment.book_the_card(order)

		self.assertIsNone(card_payment.book_the_card(order), "booked already")
		self.assertEqual(frappe.db.count("Journal Entry", {"user_remark": ["like", "%" + order.name + "%"], "docstatus": 1}), 1)

	def test_a_card_sold_with_vat_stays_a_discount(self):
		self.card = self._card(self.CARD_AMOUNT, origin="Sold with VAT")

		order = self._order()

		self.assertEqual(order.discount_amount, 40.0)
		self.assertFalse(order.get("gift_card_paid_amount"))
