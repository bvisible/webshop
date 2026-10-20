# //// Neoffice — added file (no upstream equivalent). A portal customer's loyalty balance, read with the shop's rights.
"""A portal customer sees and spends their own loyalty points, and nobody else's.

Upstream ERPNext (v15.123.0, aea326869b) now asks the SESSION user, at the top of
get_loyalty_program_details and get_loyalty_program_details_with_points:

    frappe.has_permission("Customer", doc=customer, throw=True)

and get_redeemption_factor asks for a desk right on Sales or POS Invoice. A portal
customer (Website User, role Customer) has neither, and must not be given them:
Customer read for the Customer role would hand every customer record to
frappe.client.get_list. So the day the fork merges upstream, the cart, the checkout,
the order page and the loyalty page lose the balance, and spending points raises.
ERPNext's own invoice runs the same function when it books or redeems points
(make_loyalty_point_entry, validate_loyalty_points): an invoice the shop submits in
the customer's session is refused too (payment_handler.handle_direct_order).

The shop therefore decides whose balance a session may see, then asks ERPNext with
its own rights (shop_rights): the customer the session stands for on the portal, or
anyone the session could read on the desk anyway -- upstream's own test, unchanged
for staff. A visitor is never shown a balance: the shop's guest customer is the same
record for every visitor, so its points belong to none of them.

Works on both sides of the merge: before it, the fork checked the customer only when
the function was the request's entry point, and the shop's rights pass either check.
"""

import frappe
from frappe import _

from webshop.webshop.shopping_cart.shop_rights import shop_rights


def customer_of(doc):
	"""The Customer a sales document is for, by its link -- never by its label.

	`customer_name` is the customer's NAME FIELD (a label), while the record is found by
	its ID: they differ as soon as customers are named by series ("Acme Corp - 2"), and
	the loyalty block silently vanished for those. A Quotation carries the link in
	party_name, and only when it is addressed to a Customer.
	"""
	if not doc:
		return None
	if doc.get("customer"):
		return doc.get("customer")
	if doc.get("quotation_to") in (None, "Customer"):
		return doc.get("party_name")
	return None


def stands_for(customer, user=None):
	"""Whether `user` is this customer on the portal: a Portal User row.

	The row is what get_party() trusts first (and writes on the first cart of a signed-in
	user, at login), and what ERPNext's website permission of an order reads. A Contact is
	not enough: any signed-in user may create one, linked to any customer.
	"""
	user = user or frappe.session.user
	if not customer or user in ("Guest", "Administrator"):
		return False
	return bool(frappe.db.exists("Portal User", {"parenttype": "Customer", "parent": customer, "user": user}))


def may_see_loyalty_of(customer):
	"""Whether the session may see, and spend, this customer's points."""
	if not customer or frappe.session.user == "Guest":
		return False
	if not frappe.db.exists("Customer", customer):
		return False
	return stands_for(customer) or frappe.has_permission("Customer", doc=customer)


def customer_loyalty_details(customer, loyalty_program=None, **kwargs):
	"""ERPNext's get_loyalty_program_details_with_points for `customer`, asked with the
	shop's rights -- or None when the session may not see this customer's points.

	Looked up on the module at call time, so the function ERPNext really runs is the
	one called (and the one a test puts upstream's check on)."""
	if not may_see_loyalty_of(customer):
		return None
	from erpnext.accounts.doctype.loyalty_program import loyalty_program as erpnext_loyalty

	with shop_rights():
		return erpnext_loyalty.get_loyalty_program_details_with_points(customer, loyalty_program, **kwargs)


def customer_redemption_factor(customer):
	"""ERPNext's get_redeemption_factor for `customer`, asked with the shop's rights.

	Refused like a stranger's order when the session may not see this customer."""
	if not may_see_loyalty_of(customer):
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	from erpnext.accounts.doctype.loyalty_program import loyalty_program as erpnext_loyalty

	with shop_rights():
		return erpnext_loyalty.get_redeemption_factor(customer=customer)
