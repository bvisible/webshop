# //// Neoffice — added file (no upstream equivalent).
"""Which payment methods a shopper is offered, and on whose terms.

Upstream offers every configured method to everybody. A shop selling to
businesses cannot: a customer approved yesterday pays in advance by transfer, an
established reseller buys on account, a consumer pays by card. The rule is on the
row — a customer group, covering its sub-groups — and when two rows of the same
gateway match, the more specific one wins, because its payment terms are what
that group was promised.

Nothing here touches Webshop Settings: the rows are built in memory, so a run
cannot reconfigure a live shop (a Single survives `frappe.db.rollback()`).
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.utils.payment_methods import (
	customer_group_of,
	group_lineage,
	row_for_gateway,
	rows_for_group,
)

ROOT = "_WSTEST PM All"
BUSINESS = "_WSTEST PM Business"
NEWCOMER = "_WSTEST PM Newcomer"
RESELLER = "_WSTEST PM Reseller"
CONSUMER = "_WSTEST PM Consumer"


def settings_with(*rows):
	"""An in-memory stand-in for Webshop Settings holding just these rows."""
	return frappe._dict(payment_methods=[frappe._dict(row) for row in rows])


class TestPaymentMethods(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.purge()
		# All (root) → Business → {Newcomer, Reseller}, and All → Consumer
		root = frappe.db.get_value("Customer Group", {"lft": 1}, "name")
		cls.make_group(ROOT, root, is_group=1)
		cls.make_group(BUSINESS, ROOT, is_group=1)
		cls.make_group(NEWCOMER, BUSINESS)
		cls.make_group(RESELLER, BUSINESS)
		cls.make_group(CONSUMER, ROOT)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cls.purge()
		super().tearDownClass()

	@classmethod
	def purge(cls):
		frappe.set_user("Administrator")
		# children first: a group with descendants cannot be dropped
		for name in (NEWCOMER, RESELLER, CONSUMER, BUSINESS, ROOT):
			frappe.delete_doc_if_exists("Customer Group", name, force=True)
		frappe.db.commit()

	@classmethod
	def make_group(cls, name, parent, is_group=0):
		if frappe.db.exists("Customer Group", name):
			return name
		doc = frappe.get_doc(
			{
				"doctype": "Customer Group",
				"customer_group_name": name,
				"parent_customer_group": parent,
				"is_group": is_group,
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
		return name

	# --- the tree ---------------------------------------------------------------------

	def test_a_group_answers_for_itself_and_its_ancestors_closest_first(self):
		self.assertEqual(group_lineage(NEWCOMER)[:3], [NEWCOMER, BUSINESS, ROOT])

	def test_a_visitor_with_no_group_has_no_lineage(self):
		self.assertEqual(group_lineage(None), [])
		self.assertEqual(group_lineage(""), [])

	# --- who is offered what ----------------------------------------------------------

	def test_a_row_aimed_at_nobody_is_offered_to_everybody(self):
		settings = settings_with({"payment_gateway_account": "Card", "only_customer_group": None})
		for group in (NEWCOMER, CONSUMER, None):
			self.assertEqual(
				[row.payment_gateway_account for row in rows_for_group(settings, group)],
				["Card"],
				group,
			)

	def test_a_row_aimed_at_a_group_reaches_its_sub_groups(self):
		settings = settings_with({"payment_gateway_account": "OnAccount", "only_customer_group": BUSINESS})
		self.assertTrue(rows_for_group(settings, NEWCOMER))
		self.assertTrue(rows_for_group(settings, RESELLER))
		self.assertTrue(rows_for_group(settings, BUSINESS))

	def test_a_row_aimed_at_a_group_is_hidden_from_the_others(self):
		settings = settings_with({"payment_gateway_account": "OnAccount", "only_customer_group": BUSINESS})
		self.assertEqual(rows_for_group(settings, CONSUMER), [])
		self.assertEqual(rows_for_group(settings, None), [], "a visitor is in no group")

	def test_each_group_gets_its_own_set_of_tiles(self):
		settings = settings_with(
			{"payment_gateway_account": "Card", "only_customer_group": None},
			{"payment_gateway_account": "Transfer", "only_customer_group": NEWCOMER},
			{"payment_gateway_account": "OnAccount", "only_customer_group": RESELLER},
		)
		def offered(group):
			return {row.payment_gateway_account for row in rows_for_group(settings, group)}

		self.assertEqual(offered(NEWCOMER), {"Card", "Transfer"})
		self.assertEqual(offered(RESELLER), {"Card", "OnAccount"})
		self.assertEqual(offered(CONSUMER), {"Card"})

	# --- and on whose terms -----------------------------------------------------------

	def test_the_closest_group_wins_and_brings_its_own_terms(self):
		"""The whole point: one gateway, two groups, two sets of payment terms."""
		settings = settings_with(
			{"payment_gateway_account": "OnAccount", "only_customer_group": BUSINESS, "payment_terms_template": "Net 30"},
			{"payment_gateway_account": "OnAccount", "only_customer_group": RESELLER, "payment_terms_template": "2% 10 days"},
		)
		self.assertEqual(row_for_gateway("OnAccount", settings, RESELLER).payment_terms_template, "2% 10 days")
		self.assertEqual(row_for_gateway("OnAccount", settings, NEWCOMER).payment_terms_template, "Net 30")

	def test_a_group_specific_row_beats_the_one_aimed_at_nobody(self):
		settings = settings_with(
			{"payment_gateway_account": "OnAccount", "only_customer_group": None, "payment_terms_template": "Net 30"},
			{"payment_gateway_account": "OnAccount", "only_customer_group": RESELLER, "payment_terms_template": "2% 10 days"},
		)
		self.assertEqual(row_for_gateway("OnAccount", settings, RESELLER).payment_terms_template, "2% 10 days")
		self.assertEqual(row_for_gateway("OnAccount", settings, CONSUMER).payment_terms_template, "Net 30")

	def test_the_order_the_shop_set_is_kept(self):
		settings = settings_with(
			{"payment_gateway_account": "Card", "only_customer_group": None},
			{"payment_gateway_account": "Transfer", "only_customer_group": BUSINESS},
			{"payment_gateway_account": "OnAccount", "only_customer_group": None},
		)
		self.assertEqual(
			[row.payment_gateway_account for row in rows_for_group(settings, NEWCOMER)],
			["Card", "Transfer", "OnAccount"],
		)

	def test_one_tile_per_gateway_even_when_several_rows_match(self):
		settings = settings_with(
			{"payment_gateway_account": "OnAccount", "only_customer_group": None},
			{"payment_gateway_account": "OnAccount", "only_customer_group": BUSINESS},
			{"payment_gateway_account": "OnAccount", "only_customer_group": RESELLER},
		)
		self.assertEqual(len(rows_for_group(settings, RESELLER)), 1)

	def test_a_gateway_the_shopper_may_not_use_answers_nothing(self):
		settings = settings_with({"payment_gateway_account": "OnAccount", "only_customer_group": BUSINESS})
		self.assertIsNone(row_for_gateway("OnAccount", settings, CONSUMER))
		self.assertIsNone(row_for_gateway("Unknown", settings, RESELLER))

	# --- reading the group off the document -------------------------------------------

	def test_the_group_is_read_from_the_link_field_not_from_the_label(self):
		"""`customer_name` is the label and matches the id only while customers are
		named after themselves — a shop naming them by series resolves nothing."""
		self.assertIsNone(customer_group_of(None))
		self.assertIsNone(customer_group_of(frappe._dict(customer_name="Some Label")))
		self.assertIsNone(customer_group_of(frappe._dict(party_name=None, customer=None)))
