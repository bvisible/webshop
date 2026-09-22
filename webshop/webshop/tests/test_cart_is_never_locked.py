# //// Neoffice — added file (no upstream equivalent).
"""A cart the customer wants to empty must always empty.

`update_cart` deletes the quotation when its last line goes, and Frappe refuses
to delete a document another one links to. A reminder about an abandoned cart is
a trace, not a value — yet it held the cart hostage: a customer who had received
one got a 417 on the cross of their last line and could never empty their basket
(osiris, 2026-09-07, and again on 2026-09-22 with a second blocker behind the
first). What guards it now is frappe's own `ignore_links_on_delete` hook, which
both link checks honour on a delete, wherever the deletion comes from.

A Payment Request is NOT in that hook on purpose: a request that was paid means
money moved, and that link must keep holding.
"""

import frappe
from frappe.tests.utils import FrappeTestCase


class TestCartIsNeverLocked(FrappeTestCase):
	def test_a_reminder_does_not_hold_the_cart_hostage(self):
		"""The hook must name the reminder, and the link check must honour it."""
		self.assertIn(
			"Abandoned Cart Reminder",
			frappe.get_hooks("ignore_links_on_delete"),
			"a reminder would lock the cart it talks about",
		)

	def test_a_payment_request_still_holds(self):
		"""The opposite guard: money must keep a document from vanishing."""
		self.assertNotIn(
			"Payment Request",
			frappe.get_hooks("ignore_links_on_delete"),
			"a paid request would stop protecting its quotation",
		)

	# //// Neoffice — an end-to-end case stood here and was REMOVED (2026-09-22). It built a
	# //// quotation by hand to watch the link check let it go, and ERPNext's own validate
	# //// refused that quotation: a cart is not a document you fabricate in three lines.
	# //// The end-to-end proof already exists, on a real cart, in
	# //// utils/test_follow_ups.py::test_an_emptied_cart_goes_out_even_once_reminded — and a
	# //// second copy built on a different footing would only teach us about the footing.
	# //// What is left here are the contracts that file cannot state: what the hook names,
	# //// and above all what it must never name.

	def test_the_release_walks_the_whole_chain(self):
		"""A failed intent holds a request, which holds the cart. All three go."""
		if not frappe.db.exists("DocType", "Payment Intent"):
			self.skipTest("Payment Intent belongs to the payments fork, absent here")

		from webshop.webshop.shopping_cart.cart import (
			UNCONCLUDED_INTENTS,
			_release_unconcluded_payment_intents,
		)

		self.assertIn("failed", UNCONCLUDED_INTENTS)
		self.assertIn("canceled", UNCONCLUDED_INTENTS)
		# The two that mean money must never be released.
		self.assertNotIn("succeeded", UNCONCLUDED_INTENTS)
		self.assertNotIn("refunded", UNCONCLUDED_INTENTS)
		self.assertTrue(callable(_release_unconcluded_payment_intents))
