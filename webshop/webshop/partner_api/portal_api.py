# //// Neoffice — added file (no upstream equivalent).
"""The reseller's "Integration" page: ask for the API, read the state of the request, make or replace the key.

Open to the customers the reseller catalogue is offered to (`catalogue.access.require_reseller`) and to nobody
else; identity comes from the session, no endpoint takes a customer. The secret of a key comes back once, in the
answer that makes it, and is read nowhere else.
"""

import frappe

from webshop.webshop.catalogue import access as catalogue_access
from webshop.webshop.multi_site import site_url
from webshop.webshop.partner_api import access
from webshop.webshop.utils import throttle


def _state(customer, key=None):
	state = {
		"ok": True,
		"access": access.describe(customer),
		"base_url": site_url("/partner/v1"),
		"contract_url": site_url("/partner/v1/openapi.yaml"),
	}
	if key:
		state["key"] = key
	return state


@frappe.whitelist()
@throttle.throttle("integration-state", 60, 60)
def get_integration():
	return _state(catalogue_access.require_reseller())


@frappe.whitelist(methods=["POST"])
@throttle.throttle("integration-request", 10, 3600)
def request_access(use_case=None, wants_orders=None, expected_volume=None):
	customer = catalogue_access.require_reseller()
	refusal = access.request(
		customer, frappe.session.user, use_case, frappe.utils.cint(wants_orders) == 1, expected_volume
	)
	return refusal or _state(customer)


@frappe.whitelist(methods=["POST"])
@throttle.throttle("integration-key", 20, 3600)
def new_key():
	"""Make a key and give it, once. The one it replaces stops working at this moment."""
	customer = catalogue_access.require_reseller()
	key, refusal = access.new_key(customer)
	return refusal or _state(customer, key)


@frappe.whitelist(methods=["POST"])
def revoke_key():
	customer = catalogue_access.require_reseller()
	access.revoke_key(customer)
	return _state(customer)
