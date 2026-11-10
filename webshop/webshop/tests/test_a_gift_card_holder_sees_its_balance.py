# //// Neoffice — added file (no upstream equivalent).
"""The one who spends a gift card sees what it paid and what is left on it (maintenance#651).

A gift card is a bearer card: whoever holds its code spends it, and /gift_cards lists the signed-in customer's own cards
only. The holder of a card offered by someone else saw its balance nowhere. The balance is now on the order's
confirmation page and in an e-mail queued when the card pays; nothing answers a typed code.
"""

from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.shopping_cart import cart

ORDER = "SO-GIFT-651"
CARD = "GIFT-CARD-651"
CODE = "GC-ABCD-9876"


def _database(order_type="Shopping Cart", discount=30.0, balance=70.0, contact="holder@example.com", owner=None):
	"""frappe.db.get_value answering for one shop order paid with one card; any other read goes to the database."""
	real = frappe.db.get_value
	order = frappe._dict(
		order_type=order_type,
		discount_amount=discount,
		currency="CHF",
		contact_email=contact,
		owner=owner or contact,
	)
	card = frappe._dict(coupon_code=CODE, gift_card_amount=balance, valid_upto="2027-12-31")

	def get_value(doctype, *args, **kwargs):
		fieldname = args[1] if len(args) > 1 else kwargs.get("fieldname")
		if doctype == "Sales Order":
			if isinstance(fieldname, str):
				return order.get(fieldname)
			return frappe._dict({field: order.get(field) for field in fieldname})
		if doctype == "Sales Order Item":
			return "QTN-GIFT-651"
		if doctype == "Quotation":
			return CARD
		if doctype == "Coupon Code":
			return frappe._dict({field: card.get(field) for field in fieldname})
		if doctype == "User":
			return "fr"
		return real(doctype, *args, **kwargs)

	return get_value


class TestTheBalanceOfAnOrdersCard(FrappeTestCase):
	def read(self, settled, **database):
		with (
			mock.patch.object(cart.frappe.db, "get_value", side_effect=_database(**database)),
			mock.patch.object(cart, "_spent_on", return_value=settled),
		):
			return cart.gift_card_of_order(ORDER)

	def test_an_order_whose_card_is_settled_shows_what_the_card_holds(self):
		seen = self.read(settled=True, discount=30.0, balance=70.0)

		self.assertEqual((seen.spent, seen.left, seen.currency), (30.0, 70.0, "CHF"))
		self.assertEqual(str(seen.valid_upto), "2027-12-31")

	def test_a_gateway_order_not_settled_yet_shows_what_will_be_left(self):
		# the invoice settles the card after the buyer reaches the page: the balance still holds this order
		seen = self.read(settled=False, discount=30.0, balance=100.0)

		self.assertEqual((seen.spent, seen.left), (30.0, 70.0))

	def test_a_card_that_paid_the_whole_order_and_more_is_never_below_zero(self):
		seen = self.read(settled=False, discount=30.0, balance=20.0)

		self.assertEqual(seen.left, 0)

	def test_the_code_is_shown_by_its_end_only(self):
		seen = self.read(settled=True)

		self.assertNotIn("ABCD", seen.code)
		self.assertTrue(seen.code.endswith("9876"))

	def test_an_order_without_a_card_or_from_the_desk_shows_nothing(self):
		self.assertIsNone(self.read(settled=True, discount=0))
		self.assertIsNone(self.read(settled=True, order_type="Sales"))


class TestTheHolderIsToldWhenTheCardPays(FrappeTestCase):
	def test_spending_a_card_on_a_shop_order_queues_the_mail_after_the_commit(self):
		with (
			mock.patch.object(cart.frappe.db, "get_value", side_effect=_database()),
			mock.patch.object(cart.frappe, "enqueue") as enqueue,
		):
			cart._tell_the_holder(CARD, ORDER, 30.0, 70.0)

		self.assertEqual(enqueue.call_args.args[0], "webshop.webshop.shopping_cart.cart.send_gift_card_balance")
		self.assertTrue(enqueue.call_args.kwargs["enqueue_after_commit"])
		self.assertEqual((enqueue.call_args.kwargs["spent"], enqueue.call_args.kwargs["left"]), (30.0, 70.0))

	def test_no_mail_for_an_order_that_is_not_the_shops_or_a_card_that_paid_nothing(self):
		with mock.patch.object(cart.frappe, "enqueue") as enqueue:
			with mock.patch.object(cart.frappe.db, "get_value", side_effect=_database(order_type="Sales")):
				cart._tell_the_holder(CARD, ORDER, 30.0, 70.0)
			with mock.patch.object(cart.frappe.db, "get_value", side_effect=_database()):
				cart._tell_the_holder(CARD, ORDER, 0, 70.0)
		enqueue.assert_not_called()

	def test_a_mail_that_cannot_be_queued_never_fails_the_order(self):
		with (
			mock.patch.object(cart.frappe.db, "get_value", side_effect=_database()),
			mock.patch.object(cart.frappe, "enqueue", side_effect=RuntimeError("queue down")),
			mock.patch.object(cart.frappe, "log_error") as log,
		):
			cart._tell_the_holder(CARD, ORDER, 30.0, 70.0)
		self.assertLessEqual(len(log.call_args.args[0]), 140)

	def test_spend_gift_card_tells_what_a_short_card_really_paid(self):
		card = frappe._dict(name=CARD, coupon_type="Gift Card", pricing_rule=None, used=0, gift_card_amount=20.0)
		real_get_doc = frappe.get_doc

		def get_doc(*args, **kwargs):
			# the card's Comment is not written; anything else is read as it is
			return mock.MagicMock() if args and isinstance(args[0], dict) else real_get_doc(*args, **kwargs)

		with (
			mock.patch.object(cart, "_locked_gift_card", return_value=card),
			mock.patch.object(cart, "_spent_on", return_value=None),
			mock.patch.object(cart.frappe.db, "set_value"),
			mock.patch.object(cart, "_rule_follows_the_balance"),
			mock.patch.object(cart.frappe, "get_doc", side_effect=get_doc),
			mock.patch.object(cart, "format_currency_value", side_effect=lambda value, currency=None: f"{value:.2f}"),
			mock.patch.object(cart.frappe, "log_error"),
			mock.patch.object(cart, "_tell_the_holder") as told,
		):
			left = cart.spend_gift_card(CARD, 30.0, ORDER, strict=False)

		self.assertEqual(left, 0)
		told.assert_called_once_with(CARD, ORDER, 20.0, 0)


class TestTheMailSaysTheBalance(FrappeTestCase):
	def send(self, **database):
		with (
			mock.patch.object(cart.frappe.db, "get_value", side_effect=_database(**database)),
			mock.patch.object(cart.frappe, "sendmail") as sendmail,
		):
			cart.send_gift_card_balance(CARD, ORDER, 30.0, database.get("left", 70.0))
		return sendmail

	def test_the_holder_reads_what_was_paid_and_what_is_left_never_the_whole_code(self):
		sendmail = self.send()

		kwargs = sendmail.call_args.kwargs
		self.assertEqual(kwargs["recipients"], ["holder@example.com"])
		self.assertEqual((kwargs["reference_doctype"], kwargs["reference_name"]), ("Sales Order", ORDER))
		self.assertIn("70", kwargs["subject"])
		self.assertIn("9876", kwargs["message"])
		self.assertNotIn(CODE, kwargs["message"] + kwargs["subject"])

	def test_a_card_used_up_says_so(self):
		with (
			mock.patch.object(cart.frappe.db, "get_value", side_effect=_database()),
			mock.patch.object(cart.frappe, "sendmail") as sendmail,
			mock.patch.object(cart, "_", side_effect=lambda text, lang=None, context=None: text),
		):
			cart.send_gift_card_balance(CARD, ORDER, 30.0, 0)
		self.assertIn("used up", sendmail.call_args.kwargs["message"])
		self.assertNotIn("Valid until", sendmail.call_args.kwargs["message"])

	def test_an_order_with_no_address_to_write_to_sends_nothing(self):
		sendmail = self.send(contact=None, owner="Administrator")

		sendmail.assert_not_called()
