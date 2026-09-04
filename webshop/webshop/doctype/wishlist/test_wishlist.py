# -*- coding: utf-8 -*-
# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt
import unittest

import frappe
from frappe.core.doctype.user_permission.test_user_permission import create_user

from webshop.webshop.doctype.website_item.website_item import make_website_item
from webshop.webshop.doctype.wishlist.wishlist import add_to_wishlist, remove_from_wishlist
#//// Neoffice — fixtures resolved from the site rather than upstream's hard-coded
#//// English names (0971ecdb0a, 2026-08-29 "réparer la suite Python et trois défauts qu'elle cachait").
#//// TO REVIEW: helpers and constants in this file are named in French (_compter,
#//// _vider_liste, PROPRIETAIRE) — RULE #00.
from webshop.webshop.tests.utils import make_test_item

ARTICLES = ("Test Phone Series X", "Test Phone Series Y")

# Never Administrator: these tests count that user's wishlist rows outright, and
# on a live site Administrator has a real wishlist of their own — the count comes
# back 3 where 2 is asserted, and the run "fails" over real data it should not be
# reading in the first place.
PROPRIETAIRE = "test_wishlist_owner@example.com"


class TestWishlist(unittest.TestCase):
	def setUp(self):
		#//// Neoffice — creating a User sends a welcome mail; a test must not need SMTP.
		# Creating a User sends a welcome mail; a test must not need SMTP.
		self._emails_avant = frappe.flags.mute_emails
		frappe.flags.mute_emails = True
		self.addCleanup(self._restaurer_emails)

		frappe.set_user("Administrator")
		for code in ARTICLES:
			item = make_test_item(code)
			if not frappe.db.exists("Website Item", {"item_code": code}):
				make_website_item(item, save=True)

		#//// Neoffice — the two users are created with the Customer role, so the wishlist
		#//// endpoints they call are actually reachable.
		self.owner = create_user(PROPRIETAIRE, "Customer").name
		self._vider_liste(self.owner)
		frappe.set_user(self.owner)

	def _restaurer_emails(self):
		frappe.flags.mute_emails = self._emails_avant

	def _vider_liste(self, user):
		"""Start from a known empty wishlist for this user."""
		if frappe.db.exists("Wishlist", {"user": user}):
			frappe.delete_doc("Wishlist", user, force=True, ignore_permissions=True)

	def _compter(self, user):
		return frappe.db.count("Wishlist Item", {"parent": user})

	def tearDown(self):
		#//// Neoffice — the session is put back to Administrator between the phases; upstream's
		#//// version left it on the test user and the teardown then failed on permissions.
		frappe.set_user("Administrator")

		# Wishlist rows link to the Website Item, so they go first — otherwise
		# the delete below raises and every later test inherits the leftovers.
		for code in ARTICLES:
			for parent in frappe.get_all("Wishlist Item", filters={"item_code": code}, pluck="parent"):
				self._vider_liste(parent)

		for code in ARTICLES:
			nom = frappe.db.get_value("Website Item", {"item_code": code}, "name")
			if nom:
				frappe.delete_doc("Website Item", nom, force=True, ignore_permissions=True)
			if frappe.db.exists("Item", code):
				frappe.delete_doc("Item", code, force=True, ignore_permissions=True)
		frappe.db.commit()

	def test_add_remove_items_in_wishlist(self):
		"Check if items are added and removed from user's wishlist."
		# add first item
		add_to_wishlist("Test Phone Series X")

		# check if wishlist was created and item was added
		self.assertTrue(frappe.db.exists("Wishlist", {"user": frappe.session.user}))
		self.assertTrue(
			frappe.db.exists(
				"Wishlist Item", {"item_code": "Test Phone Series X", "parent": frappe.session.user}
			)
		)

		# add second item to wishlist
		add_to_wishlist("Test Phone Series Y")
		#//// Neoffice — the count is read through a helper rather than a raw query repeated in
		#//// each test.
		self.assertEqual(self._compter(frappe.session.user), 2)

		remove_from_wishlist("Test Phone Series X")
		remove_from_wishlist("Test Phone Series Y")
#//// Neoffice — see above.

		self.assertIsNone(frappe.db.exists("Wishlist Item", {"parent": frappe.session.user}))
		#//// Neoffice — see above.
		self.assertEqual(self._compter(frappe.session.user), 0)

	def test_add_remove_in_wishlist_multiple_users(self):
		"Check if items are added and removed from the correct user's wishlist."
		#//// Neoffice — setUp leaves us signed in as the customer, who may not create Users:
		#//// the switch back is explicit.
		# setUp leaves us signed in as the customer, who may not create Users.
		frappe.set_user("Administrator")
		test_user = create_user("test_reviewer@example.com", "Customer")
		test_user_1 = create_user("test_reviewer_1@example.com", "Customer")
		#//// Neoffice — both wishlists are emptied, whichever user owns them.
		self._vider_liste(test_user.name)
		self._vider_liste(test_user_1.name)

		# add to wishlist for first user
		frappe.set_user(test_user.name)
		add_to_wishlist("Test Phone Series X")

		# add to wishlist for second user
		frappe.set_user(test_user_1.name)
		add_to_wishlist("Test Phone Series X")

		# check wishlist and its content for users
		self.assertTrue(frappe.db.exists("Wishlist", {"user": test_user.name}))
		self.assertTrue(
			frappe.db.exists(
				"Wishlist Item", {"item_code": "Test Phone Series X", "parent": test_user.name}
			)
		)

		self.assertTrue(frappe.db.exists("Wishlist", {"user": test_user_1.name}))
		self.assertTrue(
			frappe.db.exists(
				"Wishlist Item", {"item_code": "Test Phone Series X", "parent": test_user_1.name}
			)
		)

		# remove item for second user
		remove_from_wishlist("Test Phone Series X")

		# make sure item was removed for second user and not first
		self.assertFalse(
			frappe.db.exists(
				"Wishlist Item", {"item_code": "Test Phone Series X", "parent": test_user_1.name}
			)
		)
		self.assertTrue(
			frappe.db.exists(
				"Wishlist Item", {"item_code": "Test Phone Series X", "parent": test_user.name}
			)
		)

		# remove item for first user
		frappe.set_user(test_user.name)
		remove_from_wishlist("Test Phone Series X")
		self.assertFalse(
			frappe.db.exists(
				"Wishlist Item", {"item_code": "Test Phone Series X", "parent": test_user.name}
			)
		#//// Neoffice — the teardown removes what the test created (9335b4dc83, 2026-08-26).
		)
