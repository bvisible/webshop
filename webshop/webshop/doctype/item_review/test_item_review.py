# -*- coding: utf-8 -*-
# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt
import unittest

import frappe
from frappe.core.doctype.user_permission.test_user_permission import create_user

from webshop.webshop.doctype.webshop_settings.test_webshop_settings import (
	setup_webshop_settings,
)
from webshop.webshop.doctype.item_review.item_review import (
	UnverifiedReviewer,
	add_item_review,
	get_item_reviews,
)
from webshop.webshop.doctype.website_item.website_item import make_website_item
from webshop.webshop.shopping_cart.cart import get_party
from webshop.webshop.tests.utils import (
	make_test_item,
	restore_webshop_settings,
	snapshot_webshop_settings,
)

# A Rating field holds a fraction of 1, not a number of stars: the column is
# decimal(3,2) and get_queried_reviews buckets on `rating = i/5`. Posting a bare
# 4 lands in no bucket at all, so every percentage comes back 0 — which is what
# this file used to do, and why it failed.
TROIS_ETOILES = 3 / 5
QUATRE_ETOILES = 4 / 5


class TestItemReview(unittest.TestCase):
	def setUp(self):
		item = make_test_item("Test Mobile Phone")
		if not frappe.db.exists("Website Item", {"item_code": "Test Mobile Phone"}):
			make_website_item(item, save=True)

		frappe.set_user("Administrator")
		# Webshop Settings is a Single, so put back what the shop had rather than
		# a hard-coded 0: this suite used to leave reviews switched OFF on the
		# site it ran against, whatever the setting was before it started.
		self._reglages_avant = snapshot_webshop_settings(("enable_reviews", "enabled"))
		self.addCleanup(restore_webshop_settings, self._reglages_avant)
		setup_webshop_settings({"enable_reviews": 1, "enabled": 1})
		frappe.local.shopping_cart_settings = None

		# Creating a User sends a welcome mail. Whether this suite passes must
		# not depend on an SMTP server being reachable from wherever it runs.
		self._emails_avant = frappe.flags.mute_emails
		frappe.flags.mute_emails = True

	def tearDown(self):
		frappe.flags.mute_emails = self._emails_avant
		frappe.set_user("Administrator")

		website_item_doc = frappe.get_cached_doc("Website Item", {"item_code": "Test Mobile Phone"})
		reviews = frappe.get_all("Item Review", {"website_item": website_item_doc.name})
		for review in reviews:
			frappe.delete_doc("Item Review", review.name)

		website_item_doc.delete()
		# The settings are put back by the cleanup registered in setUp.

	def test_add_and_get_item_reviews_from_customer(self):
		"Add / Get Reviews from a User that is a valid customer (has added to cart or purchased in the past)"
		# create user
		web_item = frappe.db.get_value("Website Item", {"item_code": "Test Mobile Phone"})
		test_user = create_user("test_reviewer@example.com", "Customer")
		frappe.set_user(test_user.name)

		# create customer and contact against user
		customer = get_party()
		# Undo it whatever happens below: leaving a Customer linked to this user
		# turns the non-customer test into a customer one, and it then fails for
		# a reason that has nothing to do with what it checks.
		self.addCleanup(self._delete_customer, customer.name)

		# get_party() creates the Customer, but item_review recognises a customer
		# through the CONTACT that links them — and on a site where that contact
		# does not already exist, posting the review is refused with
		# "You are not a verified customer yet". This suite passed on the server
		# only because the link was already in the database.
		self._lier_contact(test_user.name, customer.name)

		# post review on "Test Mobile Phone"
		try:
			add_item_review(web_item, "Great Product", QUATRE_ETOILES, "Would recommend this product")
			review_name = frappe.db.get_value("Item Review", {"website_item": web_item})
		except Exception as e:
			# Say WHAT went wrong: swallowing it leaves "Error while publishing
			# review for WEB-ITM-0001" and nothing to act on.
			self.fail(f"Error while publishing review for {web_item}: {type(e).__name__}: {e}")
		self.addCleanup(frappe.delete_doc, "Item Review", review_name, force=True)

		review_data = get_item_reviews(web_item, 0, 10)

		self.assertEqual(len(review_data.reviews), 1)
		self.assertTrue(review_data.average_rating)
		# Index 3 is the four-star bucket: the sole review is 100% of them.
		self.assertEqual(review_data.reviews_per_rating[3], 100)
		self.assertEqual(review_data.reviews_per_rating[0], 0)

		frappe.set_user("Administrator")

	def _lier_contact(self, email, customer):
		"""Make this user reachable as that customer, the way the portal does."""
		from frappe.contacts.doctype.contact.contact import get_contact_name

		nom = get_contact_name(email)
		if nom:
			contact = frappe.get_doc("Contact", nom)
		else:
			contact = frappe.get_doc(
				{
					"doctype": "Contact",
					"first_name": email.split("@")[0],
					"email_ids": [{"email_id": email, "is_primary": 1}],
				}
			)

		if not any(
			l.link_doctype == "Customer" and l.link_name == customer for l in contact.links
		):
			contact.append("links", {"link_doctype": "Customer", "link_name": customer})

		contact.flags.ignore_permissions = True
		contact.save(ignore_permissions=True) if nom else contact.insert(ignore_permissions=True)

	def _delete_customer(self, name):
		frappe.set_user("Administrator")
		if frappe.db.exists("Customer", name):
			frappe.delete_doc("Customer", name, force=True, ignore_permissions=True)

	def test_add_item_review_from_non_customer(self):
		"Check if logged in user (who is not a customer yet) is blocked from posting reviews."
		web_item = frappe.db.get_value("Website Item", {"item_code": "Test Mobile Phone"})
		test_user = create_user("test_non_customer_reviewer@example.com", "Customer")
		frappe.set_user(test_user.name)

		with self.assertRaises(UnverifiedReviewer):
			add_item_review(web_item, "Great Product", TROIS_ETOILES, "Would recommend this product")

		# tear down
		frappe.set_user("Administrator")

	def test_add_item_reviews_from_guest_user(self):
		"Check if Guest user is blocked from posting reviews."
		web_item = frappe.db.get_value("Website Item", {"item_code": "Test Mobile Phone"})
		frappe.set_user("Guest")

		with self.assertRaises(UnverifiedReviewer):
			add_item_review(web_item, "Great Product", 3, "Would recommend this product")

		# tear down
		frappe.set_user("Administrator")
