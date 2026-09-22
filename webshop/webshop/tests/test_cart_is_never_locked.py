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

	def test_the_link_check_lets_a_reminded_quotation_go(self):
		"""End to end: a quotation a reminder points at still deletes."""
		if not frappe.db.exists("DocType", "Abandoned Cart Reminder"):
			self.skipTest("the reminders doctype is not installed on this site")

		from frappe.model.delete_doc import check_if_doc_is_linked

		from webshop.webshop.tests.utils import make_test_item

		item = make_test_item()
		quotation = frappe.get_doc(
			{
				"doctype": "Quotation",
				"quotation_to": "Customer",
				"order_type": "Shopping Cart",
				"items": [{"item_code": item.name, "qty": 1}],
			}
		)
		quotation.flags.ignore_mandatory = True
		quotation.insert(ignore_permissions=True, ignore_mandatory=True)

		reminder = frappe.get_doc(
			{"doctype": "Abandoned Cart Reminder", "quotation": quotation.name}
		)
		reminder.flags.ignore_mandatory = True
		reminder.insert(ignore_permissions=True, ignore_mandatory=True)

		try:
			# Raises frappe.LinkExistsError when the reminder still counts.
			check_if_doc_is_linked(quotation)
		finally:
			frappe.delete_doc("Abandoned Cart Reminder", reminder.name, force=True, ignore_permissions=True)
			frappe.delete_doc("Quotation", quotation.name, force=True, ignore_permissions=True)
