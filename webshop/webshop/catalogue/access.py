# //// Neoffice — added file (no upstream equivalent).
"""Who the reseller catalogue is offered to: a customer of a group the shop allowed, and nobody else.

The shop (the supplier) ticks the switch of Webshop Settings and lists the customer groups that may
use the catalogue — « Resellers », say. A group covers its sub-groups: customer groups are a tree,
and what is allowed to the parent has to reach the children (same rule as the payment methods).

The list of groups is shared, and each thing it opens has its own switch: the catalogue (`CATALOGUE`) and the
integration, the partner API (`INTEGRATION`). An instance can offer one without the other.

Identity comes from the session, never from an argument, and the customer is found through the
Portal User link — the authoritative one — without ever creating a Customer: get_party() mints one
for an account that has none, which a page view or an access check must never do.
"""

import frappe
from frappe import _

from webshop.webshop.utils.payment_methods import group_lineage


CATALOGUE = "enable_reseller_catalogue"
INTEGRATION = "enable_partner_api"


def shop_settings():
	return frappe.get_cached_doc("Webshop Settings")


def customer_of(user):
	"""The Customer behind `user`, through the Portal User link, or None. Creates nothing."""
	if not user or user in ("Guest", "Administrator"):
		return None
	return frappe.db.get_value(
		"Portal User", {"user": user, "parenttype": "Customer"}, "parent", order_by="creation asc"
	)


def allowed_groups(settings=None, switch=CATALOGUE):
	"""The customer groups the shop allowed, as a set; empty when the switch of what is asked for is off."""
	settings = settings or shop_settings()
	if not settings.get(switch):
		return set()
	return {
		row.get("allowed_customer_group")
		for row in settings.get("reseller_catalogue_groups") or []
		if row.get("allowed_customer_group")
	}


def offered_to(customer, settings=None, switch=CATALOGUE):
	"""Whether the catalogue (or, with `switch=INTEGRATION`, the integration) is offered to this customer:
	their group, or one above it, is allowed."""
	if not customer:
		return False
	groups = allowed_groups(settings, switch)
	if not groups:
		return False
	row = frappe.db.get_value("Customer", customer, ["customer_group", "disabled"], as_dict=True)
	if not row or row.disabled:
		return False
	return bool(groups.intersection(group_lineage(row.customer_group)))


def is_offered(user=None, settings=None, switch=CATALOGUE):
	"""For the links and the menu: True when require_reseller() would let `user` in."""
	return offered_to(customer_of(user or frappe.session.user), settings, switch)


def require_reseller(switch=CATALOGUE):
	"""The customer of the session, or a PermissionError. Every endpoint starts here."""
	customer = customer_of(frappe.session.user)
	if not offered_to(customer, shop_settings(), switch):
		if switch == INTEGRATION:
			frappe.throw(_("The integration is not available for your account."), frappe.PermissionError)
		frappe.throw(_("The reseller catalogue is not available for your account."), frappe.PermissionError)
	return customer
