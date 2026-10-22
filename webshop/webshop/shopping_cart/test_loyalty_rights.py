# //// Neoffice — added file (no upstream equivalent). The shop under upstream ERPNext v15.123.0's new checks.
"""A portal customer sees and spends their points, and the gateway's return books the money,
once ERPNext asks the session user for rights a customer does not have.

Upstream ERPNext v15.123.0 checks, on the SESSION user:

    get_loyalty_program_details(_with_points)   frappe.has_permission("Customer", doc=customer, throw=True)
    get_redeemption_factor                      a desk right on Sales or POS Invoice  (aea326869b)
    get_payment_entry                           create a Payment Entry, read the invoice (5289982059)

The CI runs on stock ERPNext, where the checks are real. The fleet's fork does not carry them
yet, so these tests put the same lines in place (upstream_loyalty_check,
upstream_payment_entry_check) and run the shop against them: on the cart, the points form, the
loyalty page, the order page, the invoice of an order paid with points, and the gateway's return.
The witness test calls ERPNext directly as the customer and is refused -- which is what proves
the checks sit on the shop's path.
"""

import contextlib
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, flt, today

import webshop.webshop.shopping_cart.cart as cart
from webshop.controllers.payment_handler import PaymentHandler
from webshop.templates.pages import loyalty_points as loyalty_page
from webshop.templates.pages import order as order_page
from webshop.webshop.doctype.website_item.website_item import make_website_item
from webshop.webshop.shopping_cart import loyalty_rights
from webshop.webshop.shopping_cart.test_shop_rights import upstream_check as upstream_item_check
from webshop.webshop.tests.utils import (
	PREFIX,
	default_company,
	ensure_shop_settings,
	make_test_item,
	portal_customer,
	restore_webshop_settings,
	selling_price_list,
	snapshot_webshop_settings,
)

USER = "wstest-loyalty-mine@yopmail.com"
CUSTOMER = f"{PREFIX} Loyalty Mine"
STRANGER = "wstest-loyalty-theirs@yopmail.com"
STRANGER_CUSTOMER = f"{PREFIX} Loyalty Theirs"
ITEM = f"{PREFIX} Loyalty Item"
PROGRAM = f"{PREFIX} Loyalty Program"
GATEWAY = f"{PREFIX} Loyalty Gateway"
COUPON = f"{PREFIX}-LOYALTY-COUPON"
COUPON_RULE = f"{PREFIX} Loyalty Coupon Rule"
PRICE = 50
POINTS = 120
CONVERSION = 0.1


@contextlib.contextmanager
def upstream_loyalty_check():
	"""ERPNext's loyalty functions as upstream v15.123.0 has them (aea326869b): the Customer is read
	by the session user before anything else, and the redemption factor needs a desk invoice right.

	Patched on the module: get_loyalty_program_details_with_points calls get_loyalty_program_details
	through the module, and so do the invoice's make_loyalty_point_entry and validate_loyalty_points
	-- every caller goes through the check, on the fork as on upstream (where it doubles a check that
	is already there)."""
	from erpnext.accounts.doctype.loyalty_program import loyalty_program as erpnext_loyalty

	details = erpnext_loyalty.get_loyalty_program_details
	factor = erpnext_loyalty.get_redeemption_factor

	def checked_details(customer, *args, **kwargs):
		frappe.has_permission("Customer", doc=customer, throw=True)
		return details(customer, *args, **kwargs)

	def checked_factor(loyalty_program=None, customer=None):
		if not (frappe.has_permission("Sales Invoice") or frappe.has_permission("POS Invoice")):
			frappe.throw("Not permitted", frappe.PermissionError)
		if customer:
			frappe.has_permission("Customer", doc=customer, throw=True)
		return factor(loyalty_program=loyalty_program, customer=customer)

	with (
		patch.object(erpnext_loyalty, "get_loyalty_program_details", checked_details),
		patch.object(erpnext_loyalty, "get_redeemption_factor", checked_factor),
	):
		yield


@contextlib.contextmanager
def upstream_payment_entry_check():
	"""get_payment_entry as upstream v15.123.0 has it (5289982059): the session user creates a
	Payment Entry and reads the invoice. payment_handler imports it at call time, so the patched
	function is the one it runs."""
	from erpnext.accounts.doctype.payment_entry import payment_entry as erpnext_payment_entry

	original = erpnext_payment_entry.get_payment_entry

	def checked(dt, dn, *args, **kwargs):
		frappe.has_permission("Payment Entry", ptype="create", throw=True)
		frappe.get_doc(dt, dn).check_permission()
		return original(dt, dn, *args, **kwargs)

	with patch.object(erpnext_payment_entry, "get_payment_entry", checked):
		yield


UPSTREAM_PAYMENT_REQUEST_DOCTYPES = (
	"Sales Order",
	"Purchase Order",
	"Sales Invoice",
	"Purchase Invoice",
	"POS Invoice",
	"Fees",
)


@contextlib.contextmanager
def upstream_payment_request_check():
	"""Payment Request.validate as upstream v15.12x has it: raised only on a Sales Order, a Purchase Order, an
	invoice or Fees (`Payment Requests cannot be created against: Quotation`), on a document the SESSION user may
	read, of the request's own company.

	The CI runs on stock ERPNext, where all of this is real; the fleet's fork does not carry it yet, so this puts the
	same lines in place, and a test of the checkout proves it on the fork as on upstream."""
	from erpnext.accounts.doctype.payment_request.payment_request import PaymentRequest

	original = PaymentRequest.validate_reference_document

	def checked(self):
		original(self)
		if self.reference_doctype not in UPSTREAM_PAYMENT_REQUEST_DOCTYPES:
			frappe.throw(
				"Payment Requests cannot be created against: {0}".format(frappe.bold(self.reference_doctype))
			)
		document = frappe.get_doc(self.reference_doctype, self.reference_name)
		document.check_permission("read")
		if self.company != document.company:
			frappe.throw("Company {0} does not match the company {1}".format(self.company, document.company))

	with patch.object(PaymentRequest, "validate_reference_document", checked):
		yield


@contextlib.contextmanager
def upstream_checks():
	"""Every check of upstream v15.123.0 a customer's order meets: the loyalty functions, the
	payment entry, the Payment Request's reference, and the Item read inside the pricing of each line
	(test_shop_rights)."""
	with (
		upstream_loyalty_check(),
		upstream_payment_entry_check(),
		upstream_payment_request_check(),
		upstream_item_check(),
	):
		yield


@contextlib.contextmanager
def no_gateway():
	"""The PSP is not under test: a Payment Request of this test gateway is submitted without
	asking a gateway controller (there is none behind it)."""
	from erpnext.accounts.doctype.payment_request.payment_request import PaymentRequest

	with patch.object(PaymentRequest, "payment_gateway_validation", return_value=False):
		yield


def _account(company, **filters):
	return frappe.db.get_value("Account", {"company": company, "is_group": 0, "disabled": 0, **filters}, "name")


def _purge_vouchers(customer):
	"""What an order of `customer` left: payment entries, invoices, orders, carts, their ledgers."""
	frappe.set_user("Administrator")
	invoices = frappe.get_all("Sales Invoice", filters={"customer": customer}, pluck="name")
	entries = frappe.get_all("Payment Entry", filters={"party_type": "Customer", "party": customer}, pluck="name")
	orders = frappe.get_all("Sales Order", filters={"customer": customer}, pluck="name")
	quotations = frappe.get_all("Quotation", filters={"party_name": customer}, pluck="name")
	for doctype, names in (
		("Payment Entry", entries),
		("Sales Invoice", invoices),
		("Sales Order", orders),
		("Quotation", quotations),
	):
		for name in names:
			doc = frappe.get_doc(doctype, name)
			if doc.docstatus == 1:
				doc.flags.ignore_permissions = True
				doc.flags.ignore_links = True
				doc.cancel()
			frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
			for ledger in ("GL Entry", "Payment Ledger Entry"):
				frappe.db.delete(ledger, {"voucher_no": name})
	for name in frappe.get_all("Payment Request", filters={"party": customer}, pluck="name"):
		frappe.db.delete("Payment Request", {"name": name})
	frappe.db.delete("Loyalty Point Entry", {"customer": customer})
	frappe.db.commit()


class ShopFixture(FrappeTestCase):
	"""A portal customer with points, a published item, a test gateway and the shop's settings: what every test of the
	shop's checkout under upstream's checks needs (test_pending_order.py reuses it)."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.settings_written = ensure_shop_settings()
		cls.company = frappe.db.get_single_value("Webshop Settings", "company") or default_company()
		cls.purge()

		# a site may have no default unit (a bare site has none): name one it has
		uom = frappe.db.get_single_value("Stock Settings", "stock_uom") or frappe.db.get_value("UOM", {}, "name")
		make_website_item(make_test_item(ITEM, is_stock_item=0, stock_uom=uom))
		website_item = frappe.get_doc("Website Item", {"item_code": ITEM})
		website_item.published = 1
		website_item.save(ignore_permissions=True)
		price_list = selling_price_list()
		if not frappe.db.exists("Item Price", {"item_code": ITEM, "price_list": price_list}):
			frappe.get_doc(
				{"doctype": "Item Price", "item_code": ITEM, "price_list": price_list, "price_list_rate": PRICE}
			).insert(ignore_permissions=True)

		frappe.get_doc(
			{
				"doctype": "Loyalty Program",
				"loyalty_program_name": PROGRAM,
				"loyalty_program_type": "Single Tier Program",
				"company": cls.company,
				"from_date": add_days(today(), -30),
				"conversion_factor": CONVERSION,
				"expiry_duration": 365,
				"expense_account": _account(cls.company, root_type="Expense"),
				"cost_center": frappe.get_cached_value("Company", cls.company, "cost_center")
				or frappe.db.get_value("Cost Center", {"company": cls.company, "is_group": 0}, "name"),
				"collection_rules": [{"tier_name": "Base", "collection_factor": 1, "min_spent": 0}],
			}
		).insert(ignore_permissions=True)

		for email, customer in ((USER, CUSTOMER), (STRANGER, STRANGER_CUSTOMER)):
			portal_customer(email, customer)
			# the role the shop's sign-up gives (auth/api.py): ERPNext's website permission of an
			# order reads the customer through it
			frappe.get_doc("User", email).add_roles("Customer")
			frappe.db.set_value("Customer", customer, "loyalty_program", PROGRAM)
			frappe.get_doc(
				{
					"doctype": "Address",
					"address_title": customer,
					"address_type": "Billing",
					"address_line1": "Rue du Test 1",
					"city": "Lausanne",
					"pincode": "1000",
					"country": "Switzerland" if frappe.db.exists("Country", "Switzerland") else None,
					"is_primary_address": 1,
					"links": [{"link_doctype": "Customer", "link_name": customer}],
				}
			).insert(ignore_permissions=True)

		gateway_account = _account(cls.company, account_type="Bank") or _account(cls.company, account_type="Cash")
		frappe.get_doc({"doctype": "Payment Gateway", "gateway": GATEWAY}).insert(ignore_permissions=True)
		cls.gateway_account = (
			frappe.get_doc(
				{
					"doctype": "Payment Gateway Account",
					"payment_gateway": GATEWAY,
					"payment_account": gateway_account,
					"company": cls.company,
					# autoname reads it before validate fetches it
					"currency": frappe.get_cached_value("Account", gateway_account, "account_currency"),
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		cls.bank_account = gateway_account

		cls.settings_before = snapshot_webshop_settings(["enable_loyalty_points", "loyalty_program"])
		frappe.db.set_single_value("Webshop Settings", "enable_loyalty_points", 1)
		frappe.db.set_single_value("Webshop Settings", "loyalty_program", PROGRAM)
		frappe.local.shopping_cart_settings = None
		frappe.clear_cache()
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		restore_webshop_settings(cls.settings_before)
		cls.purge()
		if cls.settings_written:
			restore_webshop_settings(cls.settings_written)
		frappe.db.commit()
		super().tearDownClass()

	@classmethod
	def purge(cls):
		"""Only what this class creates, the vouchers first."""
		frappe.set_user("Administrator")
		for email, customer in ((USER, CUSTOMER), (STRANGER, STRANGER_CUSTOMER)):
			_purge_vouchers(customer)
			for name in frappe.get_all(
				"Dynamic Link",
				filters={"parenttype": "Address", "link_doctype": "Customer", "link_name": customer},
				pluck="parent",
			):
				frappe.delete_doc("Address", name, force=True, ignore_permissions=True)
			if frappe.db.exists("Customer", customer):
				frappe.delete_doc("Customer", customer, force=True, ignore_permissions=True)
			for name in frappe.get_all("Contact", filters={"email_id": email}, pluck="name"):
				frappe.delete_doc("Contact", name, force=True, ignore_permissions=True)
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, force=True, ignore_permissions=True)
		# //// Neoffice — the Stripe receipts `stripe_has_charged` lays (maintenance#1807).
		frappe.db.delete("Integration Request", {"request_description": ["like", f"{PREFIX}%"]})
		for name in frappe.get_all("Payment Gateway Account", filters={"payment_gateway": GATEWAY}, pluck="name"):
			frappe.delete_doc("Payment Gateway Account", name, force=True, ignore_permissions=True)
		if frappe.db.exists("Payment Gateway", GATEWAY):
			frappe.delete_doc("Payment Gateway", GATEWAY, force=True, ignore_permissions=True)
		for name in frappe.get_all("Coupon Code", filters={"coupon_code": COUPON}, pluck="name"):
			frappe.delete_doc("Coupon Code", name, force=True, ignore_permissions=True)
		for name in frappe.get_all("Pricing Rule", filters={"title": COUPON_RULE}, pluck="name"):
			frappe.delete_doc("Pricing Rule", name, force=True, ignore_permissions=True)
		if frappe.db.exists("Loyalty Program", PROGRAM):
			frappe.delete_doc("Loyalty Program", PROGRAM, force=True, ignore_permissions=True)
		frappe.db.delete("Item Price", {"item_code": ITEM})
		for name in frappe.get_all("Website Item", filters={"item_code": ITEM}, pluck="name"):
			frappe.delete_doc("Website Item", name, force=True, ignore_permissions=True)
		if frappe.db.exists("Item", ITEM):
			frappe.delete_doc("Item", ITEM, force=True, ignore_permissions=True)
		frappe.db.commit()

	def setUp(self):
		frappe.set_user("Administrator")
		for customer in (CUSTOMER, STRANGER_CUSTOMER):
			_purge_vouchers(customer)
			# earned on a Sales Invoice, as points are: ERPNext's invoice redeems only entries earned
			# on the same type of invoice (sales_invoice.apply_loyalty_points)
			grant = frappe.get_doc(
				{
					"doctype": "Loyalty Point Entry",
					"loyalty_program": PROGRAM,
					"loyalty_program_tier": "Base",
					"customer": customer,
					"invoice_type": "Sales Invoice",
					"invoice": f"{PREFIX}-EARNED",
					"loyalty_points": POINTS,
					"purchase_amount": POINTS,
					"posting_date": add_days(today(), -1),
					"expiry_date": add_days(today(), 300),
					"company": self.company,
				}
			)
			grant.flags.ignore_links = True
			grant.insert(ignore_permissions=True)
		frappe.db.commit()
		# set_cart_count writes a cookie; there is no request here
		self.had_cookie_manager = hasattr(frappe.local, "cookie_manager")
		if not self.had_cookie_manager:
			frappe.local.cookie_manager = MagicMock()
		frappe.local.website_profile_doc = None
		self.form_dict = frappe.local.form_dict

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.form_dict = self.form_dict
		if not self.had_cookie_manager:
			del frappe.local.cookie_manager
		frappe.local.website_profile_doc = None

	# --- helpers ------------------------------------------------------------------

	def balance(self, customer=CUSTOMER):
		from erpnext.accounts.doctype.loyalty_program.loyalty_program import get_loyalty_details

		return flt(get_loyalty_details(customer, PROGRAM, company=self.company).get("loyalty_points"))

	def place_an_order(self, user=USER):
		"""A submitted Sales Order of `user`'s customer, placed through the shop's own cart."""
		frappe.set_user(user)
		with upstream_checks():
			cart.update_cart(ITEM, 1)
			cart.get_cart_quotation()  # sets the customer's address on the cart, as the cart page does
			name = cart.place_order()
		frappe.set_user("Administrator")
		self.assertTrue(name)
		return name

	def last_error(self):
		row = frappe.get_all("Error Log", fields=["method", "error"], order_by="creation desc", limit=1)
		return row[0] if row else None

	def stripe_has_charged(self, request, amount=None, currency=None, status="Completed", bound_to=None):
		"""What the server holds once Stripe has captured the charge of `request`: the receipt `Stripe Settings` writes
		(payments.utils.stripe_receipt), here from a stand-in for Stripe's answer. The shop concludes a card payment on
		this, not on who asks (maintenance#1807). `amount` (in cents) and `currency` default to what the request asks;
		`bound_to` names another request, or None to bind it to `request`."""
		try:
			from payments.utils import stripe_receipt
		except ImportError:
			self.skipTest("payments app not installed")
		row = frappe.db.get_value("Payment Request", request, ["grand_total", "currency"], as_dict=True)
		if not row:
			return None
		integration_request = frappe.get_doc(
			{
				"doctype": "Integration Request",
				"integration_request_service": stripe_receipt.RECEIPT_SERVICE,
				"request_description": f"{PREFIX}-receipt",
				"status": status,
				"data": "{}",
			}
		).insert(ignore_permissions=True)
		charge = frappe._dict(
			id=f"ch_{frappe.generate_hash(length=16)}",
			amount=stripe_receipt.stripe_minor_units(row.grand_total) if amount is None else amount,
			currency=(currency or row.currency).lower(),
			captured=True,
			paid=True,
		)
		stripe_receipt.write(integration_request, charge, bound_to or request)
		frappe.db.commit()
		return integration_request


class TestLoyaltyAndPaymentUnderUpstreamChecks(ShopFixture):
	# --- the witness --------------------------------------------------------------

	def test_erpnext_itself_refuses_the_customer_under_the_upstream_checks(self):
		"""Without the shop's rights the customer is refused: the checks sit on the shop's path."""
		from erpnext.accounts.doctype.loyalty_program import loyalty_program as erpnext_loyalty

		frappe.set_user(USER)
		with upstream_loyalty_check():
			with self.assertRaises(frappe.PermissionError):
				erpnext_loyalty.get_loyalty_program_details_with_points(CUSTOMER, PROGRAM)
			with self.assertRaises(frappe.PermissionError):
				erpnext_loyalty.get_redeemption_factor(customer=CUSTOMER)
		self.assertEqual(frappe.session.user, USER)

	# --- a portal customer sees their points --------------------------------------

	def test_the_cart_shows_their_balance(self):
		frappe.set_user(USER)
		with upstream_checks():
			cart.update_cart(ITEM, 1)
			info = cart.get_cart_quotation()
		self.assertEqual(info["available_loyalty_points"], POINTS)
		self.assertEqual(info["loyalty_program_details"]["loyalty_program"], PROGRAM)
		self.assertEqual(frappe.session.user, USER, "the session must come back as the customer")

	def test_the_points_form_shows_their_balance(self):
		frappe.set_user(USER)
		with upstream_checks():
			cart.update_cart(ITEM, 1)
			html = cart.get_loyalty_points_html()
		self.assertIn(f'value="{POINTS}"', html)

	def test_the_loyalty_page_shows_their_balance(self):
		frappe.set_user(USER)
		context = frappe._dict()
		with upstream_checks():
			loyalty_page.get_context(context)
		self.assertEqual(context.customer, CUSTOMER)
		self.assertEqual(flt(context.total_points), POINTS)

	def test_the_order_page_shows_their_balance_and_redemption_factor(self):
		order = self.place_an_order()
		frappe.set_user(USER)
		frappe.local.form_dict = frappe._dict(doctype="Sales Order", name=order)
		context = frappe._dict()
		with upstream_checks():
			order_page.get_context(context)
			factor = order_page.get_redemption_factor("Sales Order", order)
		self.assertEqual(flt(context.available_loyalty_points), POINTS)
		self.assertEqual(flt(factor), CONVERSION)

	# --- and nobody else's ---------------------------------------------------------

	def test_another_customer_s_order_and_points_are_refused(self):
		order = self.place_an_order()
		frappe.set_user(STRANGER)
		with upstream_loyalty_check():
			with self.assertRaises(frappe.PermissionError):
				order_page.get_redemption_factor("Sales Order", order)
			self.assertIsNone(loyalty_rights.customer_loyalty_details(CUSTOMER, PROGRAM))
			with self.assertRaises(frappe.PermissionError):
				loyalty_rights.customer_redemption_factor(CUSTOMER)
		self.assertTrue(loyalty_rights.may_see_loyalty_of(STRANGER_CUSTOMER))
		self.assertFalse(loyalty_rights.may_see_loyalty_of(CUSTOMER))

	def test_only_an_order_names_the_customer_of_a_redemption(self):
		frappe.set_user(USER)
		for doctype in ("Customer", "Quotation", "Sales Invoice"):
			with self.subTest(doctype=doctype):
				with self.assertRaises(frappe.PermissionError):
					order_page.get_redemption_factor(doctype, CUSTOMER)

	def test_a_visitor_never_sees_or_spends_a_balance(self):
		"""A visitor stands for the shop's guest customer, the same record for every visitor."""
		frappe.set_user("Guest")
		self.assertIsNone(loyalty_rights.customer_loyalty_details(CUSTOMER, PROGRAM))
		quotation = frappe._dict(company=self.company, rounded_total=100, grand_total=100, taxes=[])
		with (
			patch.object(cart, "_get_cart_quotation", return_value=quotation),
			patch.object(cart, "get_party", return_value=frappe._dict(name=CUSTOMER)),
		):
			with self.assertRaises(frappe.ValidationError):
				cart.apply_loyalty_points(10)
		frappe.set_user("Administrator")
		self.assertEqual(self.balance(), POINTS, "nothing was spent")

	def test_staff_still_read_any_customer_s_points(self):
		details = loyalty_rights.customer_loyalty_details(STRANGER_CUSTOMER, PROGRAM)
		self.assertEqual(flt(details.loyalty_points), POINTS)

	# --- a portal customer spends their points ------------------------------------

	def test_they_spend_points_on_their_cart(self):
		frappe.set_user(USER)
		with upstream_checks():
			cart.update_cart(ITEM, 1)
			quotation = cart.apply_loyalty_points(50)
		self.assertEqual(flt(quotation.loyalty_points), 50)
		self.assertEqual(flt(quotation.loyalty_amount), 50 * CONVERSION)
		frappe.set_user("Administrator")
		self.assertEqual(self.balance(), POINTS - 50, "the points are held while the order is paid")

	def test_negative_points_are_refused(self):
		"""A negative number passed both checks and wrote a positive entry: the balance went up."""
		frappe.set_user(USER)
		with upstream_checks():
			cart.update_cart(ITEM, 1)
			with self.assertRaises(frappe.ValidationError):
				cart.apply_loyalty_points(-100)
		frappe.set_user("Administrator")
		self.assertEqual(self.balance(), POINTS)

	def test_points_applied_again_are_held_once(self):
		frappe.set_user(USER)
		with upstream_checks():
			cart.update_cart(ITEM, 1)
			cart.apply_loyalty_points(50)
			cart.apply_loyalty_points(30)
		frappe.set_user("Administrator")
		self.assertEqual(self.balance(), POINTS - 30, "the first hold is dropped, not orphaned")

	def standing_rule(self, settings_field, role, customer_change):
		"""Accounts Settings names the role that may override a rule; the buyer does not hold it."""
		before = frappe.db.get_single_value("Accounts Settings", settings_field)
		frappe.db.set_single_value("Accounts Settings", settings_field, role)
		customer_change()
		frappe.clear_document_cache("Customer", CUSTOMER)
		frappe.db.commit()

		def restore():
			frappe.set_user("Administrator")
			frappe.db.set_single_value("Accounts Settings", settings_field, before)
			frappe.db.set_value("Customer", CUSTOMER, "is_frozen", 0)
			frappe.db.delete("Customer Credit Limit", {"parent": CUSTOMER, "parenttype": "Customer"})
			frappe.clear_document_cache("Customer", CUSTOMER)
			frappe.db.commit()

		self.addCleanup(restore)

	def assert_no_order(self):
		frappe.set_user("Administrator")
		self.assertFalse(frappe.get_all("Sales Order", filters={"customer": CUSTOMER, "docstatus": 1}))

	def test_a_frozen_customer_still_cannot_order_on_the_shop_s_rights(self):
		"""Administrator holds the role that may override a frozen customer; the buyer does not."""
		self.standing_rule(
			"frozen_accounts_modifier",
			"Accounts Manager",
			lambda: frappe.db.set_value("Customer", CUSTOMER, "is_frozen", 1),
		)
		frappe.set_user(USER)
		with upstream_checks():
			cart.update_cart(ITEM, 1)
			cart.get_cart_quotation()
			with self.assertRaises(frappe.ValidationError):
				cart.place_order()
		self.assert_no_order()

	def test_a_customer_over_their_credit_limit_still_cannot_order_on_the_shop_s_rights(self):
		def limit():
			frappe.get_doc(
				{
					"doctype": "Customer Credit Limit",
					"parent": CUSTOMER,
					"parenttype": "Customer",
					"parentfield": "credit_limits",
					"company": self.company,
					"credit_limit": 1,
				}
			).db_insert()

		self.standing_rule("credit_controller", "Accounts Manager", limit)
		frappe.set_user(USER)
		with upstream_checks():
			cart.update_cart(ITEM, 1)
			cart.get_cart_quotation()
			with self.assertRaises(frappe.ValidationError):
				cart.place_order()
		self.assert_no_order()

	def test_they_take_their_points_back(self):
		frappe.set_user(USER)
		with upstream_checks():
			cart.update_cart(ITEM, 1)
			cart.apply_loyalty_points(50)
			quotation = cart.remove_loyalty_points()
		self.assertFalse(flt(quotation.loyalty_points))
		self.assertFalse(flt(quotation.loyalty_amount))
		frappe.set_user("Administrator")
		self.assertEqual(self.balance(), POINTS, "the points are theirs again")

	def test_a_coupon_goes_on_and_off_their_cart(self):
		"""Not loyalty, the same save: the cart is saved again, and upstream reads the Item there."""
		rule = frappe.get_doc(
			{
				"doctype": "Pricing Rule",
				"title": COUPON_RULE,
				"apply_on": "Transaction",
				"price_or_product_discount": "Price",
				"selling": 1,
				"coupon_code_based": 1,
				"rate_or_discount": "Discount Percentage",
				"discount_percentage": 10,
				"company": self.company,
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "Coupon Code",
				"coupon_name": COUPON,
				"coupon_code": COUPON,
				"coupon_type": "Promotional",
				"pricing_rule": rule.name,
				"maximum_use": 10,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		frappe.set_user(USER)
		with upstream_checks():
			cart.update_cart(ITEM, 1)
			applied = cart.apply_coupon_code(COUPON, None)
			removed = cart.remove_coupon_code()
		self.assertTrue(applied.coupon_code)
		self.assertFalse(removed.coupon_code)
		self.assertEqual(frappe.session.user, USER)

	def test_the_invoice_of_their_order_redeems_the_points(self):
		"""The pay-on-invoice path: the order and its invoice are made in the customer's session,
		and ERPNext's invoice reads the customer's balance to redeem and to book points."""
		frappe.set_user(USER)
		with upstream_checks():
			cart.update_cart(ITEM, 1)
			cart.get_cart_quotation()  # sets the customer's address on the cart, as the cart page does
			cart.apply_loyalty_points(50)
			result = PaymentHandler().handle_direct_order()
		frappe.set_user("Administrator")
		self.assertEqual(result.get("status"), "success", (result, self.last_error()))
		order = result["redirect_to"].split("sales_order=")[1]
		invoices = frappe.get_all(
			"Sales Invoice Item", filters={"sales_order": order, "docstatus": 1}, pluck="parent", distinct=True
		)
		self.assertEqual(len(invoices), 1, invoices)
		invoice = frappe.get_doc("Sales Invoice", invoices[0])
		self.assertEqual(invoice.customer, CUSTOMER)
		self.assertEqual(flt(invoice.loyalty_points), 50)
		self.assertEqual(invoice.owner, USER, "the invoice stays the buyer's")
		redeemed = frappe.get_all(
			"Loyalty Point Entry",
			filters={"invoice_type": "Sales Invoice", "invoice": invoice.name, "loyalty_points": ["<", 0]},
			pluck="loyalty_points",
		)
		self.assertEqual(sum(redeemed), -50, "the invoice redeemed the points")

	# --- the gateway's return books the money -------------------------------------

	def payment_request_for_the_cart(self):
		"""The request the checkout raises for the cart: through the shop's own handler, as the buyer, under
		upstream's checks (which, for a Payment Request, only accept a Sales Order, an invoice...)."""
		frappe.set_user(USER)
		with upstream_checks():
			cart.update_cart(ITEM, 1)
			cart.get_cart_quotation()
			quotation = cart._get_cart_quotation()
			result = PaymentHandler().create_payment_request(
				quotation_id=quotation.name, payment_gateway=GATEWAY
			)
		frappe.set_user("Administrator")
		self.assertEqual(result.get("status"), "success", (result, self.last_error()))
		frappe.db.commit()
		return result["payment_request_id"], quotation.name

	def assert_invoiced_and_paid(self, order, reference_no):
		invoices = frappe.get_all(
			"Sales Invoice Item", filters={"sales_order": order, "docstatus": 1}, pluck="parent", distinct=True
		)
		self.assertEqual(len(invoices), 1, (invoices, self.last_error()))
		entries = frappe.get_all(
			"Payment Entry Reference",
			filters={"reference_doctype": "Sales Invoice", "reference_name": invoices[0], "docstatus": 1},
			pluck="parent",
		)
		self.assertEqual(len(entries), 1, (entries, self.last_error()))
		entry = frappe.get_doc("Payment Entry", entries[0])
		self.assertEqual(entry.paid_to, self.bank_account)
		self.assertEqual(entry.reference_no, reference_no)
		self.assertEqual(flt(frappe.db.get_value("Sales Invoice", invoices[0], "outstanding_amount")), 0)

	def test_the_gateway_return_creates_the_invoice_and_the_payment_entry(self):
		request, quotation = self.payment_request_for_the_cart()
		self.stripe_has_charged(request)  # the gateway's word; the buyer's identity concludes nothing (#1807)
		frappe.set_user(USER)
		with upstream_checks(), no_gateway():
			result = PaymentHandler().handle_payment_success(payment_request_id=request)
		frappe.set_user("Administrator")
		self.assertEqual(result.get("status"), "success", (result, self.last_error()))
		order = frappe.db.get_value("Payment Request", request, "reference_name")
		self.assertEqual(frappe.db.get_value("Sales Order", order, "docstatus"), 1)
		self.assert_invoiced_and_paid(order, request)
		self.assertEqual(frappe.db.get_value("Payment Request", request, "status"), "Paid")

	def test_invoicing_a_paid_order_does_not_depend_on_an_administrator_session(self):
		"""_invoice_paid_order books the money with the shop's rights whoever the session is:
		upstream's get_payment_entry refused the customer, and the failure was only logged."""
		order = self.place_an_order()
		request = frappe._dict(name=f"{PREFIX}-REQ", payment_gateway_account=self.gateway_account)
		frappe.set_user(USER)
		with upstream_checks():
			PaymentHandler()._invoice_paid_order(order, request)
		self.assertEqual(frappe.session.user, USER, "the session must come back as the customer")
		frappe.set_user("Administrator")
		self.assert_invoiced_and_paid(order, request.name)
