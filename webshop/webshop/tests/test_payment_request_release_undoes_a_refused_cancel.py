# //// Neoffice — added file (no upstream equivalent). Emptying a cart that a payment was attempted on
# //// releases the payment requests that never succeeded; a cancel Frappe refuses was kept half done (#951).
# Copyright (c) 2026, Neoffice and Contributors
# License: MIT. See LICENSE
"""A payment request that Frappe refuses to cancel is put back as it was, with its payment intents (#951).

Frappe cancels a document by writing docstatus 2 to its row, running on_cancel and only then checking that no
submitted document still links to it. When that check raises LinkExistsError the row and what on_cancel wrote
are already there, and `_release_unsuccessful_payment_requests` carries on with the next request and lets the
operation commit: the refused request would stay cancelled, and the intents deleted just before it would be
gone with nothing to show for it.

The tests call the real function with Frappe replaced by stand-ins: a database with the savepoint semantics
over a few rows, documents whose cancel writes before it raises. No site, no database.
"""

from __future__ import annotations

import unittest
from unittest import mock

import frappe

from webshop.webshop.shopping_cart import cart


class FakeDatabase:
	"""A few rows and the transaction calls the function makes, with real savepoint semantics."""

	def __init__(self, requests):
		self.rows = {}
		for name, docstatus in requests:
			self.rows[("Payment Request", name)] = docstatus
			self.rows[("Payment Intent", f"PI-{name}")] = "failed"
		self.events = []
		self._savepoints = {}
		self.committed = None

	def savepoint(self, name):
		self.events.append(("savepoint", name))
		self._savepoints[name] = dict(self.rows)

	def rollback(self, save_point=None):
		assert save_point, "a whole rollback would also undo the requests that were released"
		self.events.append(("rollback", save_point))
		self.rows = dict(self._savepoints[save_point])

	def release_savepoint(self, name):
		self.events.append(("release", name))
		self._savepoints.pop(name)

	def commit(self):
		self.committed = dict(self.rows)


class FakePaymentRequest:
	"""A payment request. cancel() writes what Frappe writes, in Frappe's order, then may refuse."""

	def __init__(self, database, name, docstatus, refuses=False):
		self.database, self.name, self.docstatus, self.refuses = database, name, docstatus, refuses
		self.flags = frappe._dict()

	def cancel(self):
		self.database.rows[("Payment Request", self.name)] = 2  # docstatus 2, written first
		self.database.rows[("On cancel", self.name)] = "written by on_cancel"
		if self.refuses:  # the link check comes last
			raise frappe.LinkExistsError(f"Cannot cancel {self.name}: linked to a submitted Payment Entry")

	def delete(self):
		del self.database.rows[("Payment Request", self.name)]


def _release(requests, refusing=()):
	"""Call the real function; returns (database, log_error calls, clear_messages mock)."""
	database = FakeDatabase(requests)
	documents = {
		name: FakePaymentRequest(database, name, docstatus, name in refusing) for name, docstatus in requests
	}
	logged = []

	def log_error(title=None, message=None, **_ignored):
		logged.append((title, message))
		database.rows[("Error Log", len(logged))] = title  # a write: it must survive the rollback

	def release_intents(request_name):
		database.rows.pop(("Payment Intent", f"PI-{request_name}"), None)

	rows = [frappe._dict(name=name, docstatus=docstatus) for name, docstatus in requests]
	with (
		mock.patch.object(cart.frappe, "db", database),
		mock.patch.object(cart.frappe, "get_all", return_value=rows),
		mock.patch.object(cart.frappe, "get_doc", side_effect=lambda doctype, name: documents[name]),
		mock.patch.object(cart.frappe, "log_error", side_effect=log_error),
		mock.patch.object(cart.frappe, "clear_messages") as clear_messages,
		mock.patch.object(cart, "_release_unconcluded_payment_intents", side_effect=release_intents),
	):
		cart._release_unsuccessful_payment_requests("QTN-1")
	database.commit()
	return database, logged, clear_messages


class TestPaymentRequestReleaseUndoesARefusedCancel(unittest.TestCase):
	def test_a_request_frappe_refuses_to_cancel_is_put_back_as_it_was(self):
		database, _, _ = _release([("PR-1", 1), ("PR-2", 0)], refusing={"PR-1"})
		# submitted again, nothing of what on_cancel wrote is left
		self.assertEqual(database.committed[("Payment Request", "PR-1")], 1)
		self.assertNotIn(("On cancel", "PR-1"), database.committed)

	def test_its_intents_come_back_with_it(self):
		database, _, _ = _release([("PR-1", 1), ("PR-2", 0)], refusing={"PR-1"})
		self.assertIn(("Payment Intent", "PI-PR-1"), database.committed)

	def test_the_other_requests_are_still_released(self):
		database, _, _ = _release([("PR-1", 1), ("PR-2", 0)], refusing={"PR-1"})
		self.assertNotIn(("Payment Request", "PR-2"), database.committed)  # a draft: deleted
		self.assertNotIn(("Payment Intent", "PI-PR-2"), database.committed)

	def test_the_failure_is_logged_after_the_rollback_so_that_the_log_survives(self):
		database, logged, clear_messages = _release([("PR-1", 1), ("PR-2", 0)], refusing={"PR-1"})
		self.assertEqual(len(logged), 1)
		title, message = logged[0]
		self.assertEqual(title, "Webshop: could not release a payment request")
		self.assertIn("LinkExistsError", message)
		self.assertIn(("Error Log", 1), database.committed)
		clear_messages.assert_called_once_with()

	def test_the_operation_goes_on_it_never_fails_because_a_request_could_not_be_released(self):
		# _release returns: the function raised nothing, the caller's delete will say whether it still blocks
		database, _, _ = _release([("PR-1", 1)], refusing={"PR-1"})
		self.assertEqual(database.committed[("Payment Request", "PR-1")], 1)

	def test_each_request_runs_under_its_own_savepoint_and_none_is_left_open(self):
		database, _, _ = _release([("PR-1", 1), ("PR-2", 0), ("PR-3", 1)], refusing={"PR-1"})
		kinds = [kind for kind, _name in database.events]
		self.assertEqual(kinds, ["savepoint", "rollback", "savepoint", "release", "savepoint", "release"])
		self.assertEqual(database._savepoints, {})

	def test_a_submitted_request_that_cancels_fine_is_cancelled_and_its_intents_go(self):
		database, logged, _ = _release([("PR-1", 1)])
		self.assertEqual(database.committed[("Payment Request", "PR-1")], 2)
		self.assertEqual(database.committed[("On cancel", "PR-1")], "written by on_cancel")
		self.assertNotIn(("Payment Intent", "PI-PR-1"), database.committed)
		self.assertEqual(logged, [])
		self.assertNotIn("rollback", [kind for kind, _name in database.events])


if __name__ == "__main__":
	unittest.main()
