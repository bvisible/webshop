# //// Neoffice — added file (no upstream equivalent).
"""A reseller's access to the partner API: asked for on their page, allowed by staff, opened by a key.

The study of 2026-09-17 (Obsidian, `Neoffice/API-Partenaires`) and its note 04 give the shape; the choices
that differ from it are named here.

- **One access a customer** (decision 3 of the study), in a record of its own: the request, what staff allowed
  (the scopes), the state (`Requested`, `Active`, `Suspended`, `Refused`), and the hash of the key. Suspending
  cuts the API and touches nothing else: the customer keeps their portal, their invoices, their feeds.
- **The key is its own, not a Frappe API key on the portal user.** A native key reaches every method that user
  may call, `/api/resource` included; this one opens `/partner/v1/` and nothing else, so a leaked key reads a
  catalogue and places draft orders, it cannot do what a customer's browser session can. It is sent in the
  `X-API-Key` header — never in `Authorization`, where Frappe tries it as OAuth or a native key first and
  answers 401 to anything it does not know.
- **The secret is shown once**, on the reseller's page, and kept nowhere: the record holds a public id and the
  SHA-256 of the secret. A new key replaces the old one at once; a lost key is replaced, not recovered.
- **Every refusal of a key is the same 401** whatever the reason (unknown id, wrong secret, suspended, revoked,
  customer no longer offered the catalogue), the reason in the error code only; a connection that sends many
  wrong keys is slowed.
"""

import hashlib
import hmac
import re
import secrets

import frappe
from frappe.utils import now_datetime

from webshop.webshop.catalogue import access as catalogue_access
from webshop.webshop.catalogue.refusals import api_message
from webshop.webshop.doctype.partner_api_access.partner_api_access import ACTIVE, REFUSED, REQUESTED, SUSPENDED
from webshop.webshop.utils import throttle

DOCTYPE = "Partner API Access"
KEY_PREFIX = "wsk_"
KEY_PATTERN = re.compile(r"^wsk_([0-9a-f]{12})\.([A-Za-z0-9_-]{20,64})$")
MAX_USE_CASE = 500
MAX_VOLUME = 100
MAX_CALLS_PER_MINUTE = 600
REQUESTS_PER_DAY = 3
LAST_USED_RECORDED_MINUTES = 60
STAFF = ("System Manager", "Sales Manager")
# What the API says: English, whatever the site speaks, and stable: a program reads the code, a person the sentence.
API_TEXT = {
	"invalid_key": "The API key is missing, wrong or no longer valid.",
	"too_many_attempts": "Too many wrong keys from this connection. Try again later.",
	"rate_limited": "Too many calls this minute for this access.",
}


class ApiError(Exception):
	"""An answer that is not a success: a status, a stable code a program can read, a sentence a person can."""

	def __init__(self, status, code, message, headers=None, details=None):
		super().__init__(message)
		self.status, self.code, self.message = status, code, message
		self.headers, self.details = headers or {}, details


def refused(field, message):
	return {"ok": False, "field": field, "message": message}


def digest(secret):
	return hashlib.sha256(secret.encode()).hexdigest()


def get(customer, lock=False):
	if not customer or not frappe.db.exists(DOCTYPE, customer):
		return None
	return frappe.get_doc(DOCTYPE, customer, for_update=True) if lock else frappe.get_doc(DOCTYPE, customer)


def describe(customer):
	"""The access as its owner's page shows it, or None when they never asked. No secret, no hash."""
	doc = get(customer)
	if not doc:
		return None
	return {
		"status": doc.status,
		"use_case": doc.use_case,
		"wants_orders": bool(doc.wants_orders),
		"expected_volume": doc.expected_volume,
		"requested_on": str(doc.requested_on or ""),
		"scope_products": bool(doc.scope_products),
		"scope_orders": bool(doc.scope_orders),
		"submit_orders": bool(doc.submit_orders),
		"calls_per_minute": doc.calls_per_minute,
		"decision_note": doc.decision_note or "",
		"decided_on": str(doc.decided_on or ""),
		"key_id": f"{KEY_PREFIX}{doc.key_id}" if doc.key_id else "",
		"key_created_on": str(doc.key_created_on or ""),
		"last_used_on": str(doc.last_used_on or ""),
	}


# ---------------------------------------------------------------------------------------------
# What the reseller does


def request(customer, user, use_case, wants_orders, expected_volume):
	"""A reseller asks for an access. None once written, else a refusal in their words."""
	use_case = " ".join(str(use_case or "").split())
	volume = " ".join(str(expected_volume or "").split())
	if not use_case:
		return refused("use_case", api_message("use_case_required"))
	if len(use_case) > MAX_USE_CASE or any(char in use_case + volume for char in "<>"):
		return refused("use_case", api_message("use_case_invalid", MAX_USE_CASE))
	if len(volume) > MAX_VOLUME:
		return refused("expected_volume", api_message("volume_invalid", MAX_VOLUME))
	frappe.db.get_value("Customer", customer, "name", for_update=True)
	doc = get(customer, lock=True)
	if doc and doc.status in (REQUESTED, ACTIVE, SUSPENDED):
		return refused(None, api_message("already"))
	if throttle.hit("partner-request", customer, 86400) > REQUESTS_PER_DAY:
		return refused(None, api_message("too_many_requests"))
	if not doc:
		doc = frappe.new_doc(DOCTYPE)
		doc.customer = customer
	doc.status = REQUESTED
	doc.requested_by = user
	doc.use_case = use_case
	doc.expected_volume = volume
	doc.wants_orders = 1 if wants_orders else 0
	doc.requested_on = now_datetime()
	doc.decision_note = ""
	doc.decided_by = doc.decided_on = None
	doc.flags.ignore_permissions = True
	doc.save()
	# staff open the desk on their to-dos: a request nobody sees would wait for ever
	frappe.get_doc(
		{
			"doctype": "ToDo",
			"allocated_to": "Administrator",
			"reference_type": DOCTYPE,
			"reference_name": customer,
			"description": f"Partner API access requested by {customer}",
		}
	).insert(ignore_permissions=True)
	return None


def new_key(customer):
	"""A new key for an access that is Active: the whole key, which nobody will read again. Or a refusal."""
	frappe.db.get_value("Customer", customer, "name", for_update=True)
	doc = get(customer, lock=True)
	if not doc or doc.status != ACTIVE:
		return None, refused(None, api_message("not_active"))
	if throttle.hit("partner-key", customer, 3600) > 10:
		return None, refused(None, api_message("too_many_keys"))
	key_id, secret = secrets.token_hex(6), secrets.token_urlsafe(30)
	doc.key_id, doc.secret_hash, doc.key_created_on = key_id, digest(secret), now_datetime()
	doc.last_used_on = None
	doc.flags.ignore_permissions = True
	doc.save()
	return f"{KEY_PREFIX}{key_id}.{secret}", None


def revoke_key(customer):
	doc = get(customer, lock=True)
	if doc and doc.key_id:
		doc.key_id = doc.secret_hash = None
		doc.key_created_on = doc.last_used_on = None
		doc.flags.ignore_permissions = True
		doc.save()


# ---------------------------------------------------------------------------------------------
# What staff do (the buttons of the form)


def _decide(customer, status, note="", **fields):
	frappe.only_for(STAFF)
	doc = get(customer, lock=True)
	if not doc:
		frappe.throw(api_message("no_access"))
	doc.status = status
	doc.decided_by, doc.decided_on = frappe.session.user, now_datetime()
	doc.decision_note = (note or "").strip()[:500]
	for field, value in fields.items():
		doc.set(field, value)
	doc.flags.ignore_permissions = True
	doc.save()
	for name in frappe.get_all(
		"ToDo", filters={"reference_type": DOCTYPE, "reference_name": customer, "status": "Open"}, pluck="name"
	):
		frappe.db.set_value("ToDo", name, "status", "Closed")
	return doc


@frappe.whitelist(methods=["POST"])
def approve(customer, scope_orders=0, submit_orders=0, calls_per_minute=60, note=""):
	"""Staff allow the access: reading the catalogue always, placing orders when ticked."""
	frappe.only_for(STAFF)
	doc = get(customer)
	if not doc or doc.status not in (REQUESTED, REFUSED):
		frappe.throw(api_message("not_requested"))
	calls = frappe.utils.cint(calls_per_minute)
	if not 1 <= calls <= MAX_CALLS_PER_MINUTE:
		frappe.throw(api_message("calls_invalid", MAX_CALLS_PER_MINUTE))
	orders = 1 if frappe.utils.cint(scope_orders) else 0
	_decide(
		customer,
		ACTIVE,
		note,
		scope_products=1,
		scope_orders=orders,
		submit_orders=1 if orders and frappe.utils.cint(submit_orders) else 0,
		calls_per_minute=calls,
	)


@frappe.whitelist(methods=["POST"])
def refuse(customer, note=""):
	frappe.only_for(STAFF)
	doc = get(customer)
	if not doc or doc.status not in (REQUESTED, REFUSED):
		frappe.throw(api_message("not_requested"))
	_decide(customer, REFUSED, note)
	revoke_key(customer)


@frappe.whitelist(methods=["POST"])
def suspend(customer, note=""):
	"""The key stops working at once; the portal, the invoices and the feeds of the customer are untouched."""
	frappe.only_for(STAFF)
	doc = get(customer)
	if not doc or doc.status != ACTIVE:
		frappe.throw(api_message("not_active"))
	_decide(customer, SUSPENDED, note)


@frappe.whitelist(methods=["POST"])
def resume(customer):
	frappe.only_for(STAFF)
	doc = get(customer)
	if not doc or doc.status != SUSPENDED:
		frappe.throw(api_message("not_suspended"))
	_decide(customer, ACTIVE, "")


# ---------------------------------------------------------------------------------------------
# What a call must show


def authenticate(header, peer=None):
	"""The access a key opens, as a plain dict, or an ApiError 401.

	The same answer whatever is wrong, so a probe learns nothing from it; a connection that sends many wrong
	keys in ten minutes is slowed (429) before it learns anything by volume either."""
	match = KEY_PATTERN.match((header or "").strip())
	row = None
	if match:
		row = frappe.db.get_value(
			DOCTYPE,
			{"key_id": match.group(1)},
			[
				"name",
				"customer",
				"status",
				"secret_hash",
				"scope_products",
				"scope_orders",
				"submit_orders",
				"calls_per_minute",
				"requested_by",
				"last_used_on",
			],
			as_dict=True,
		)
	# a hash is compared even when no row was found, so that the time taken does not tell the two cases apart
	expected = (row and row.secret_hash) or "0" * 64
	same = hmac.compare_digest(digest(match.group(2) if match else ""), expected)
	if not (row and same):
		if peer and throttle.hit("partner-miss", peer, 600) > 30:
			raise ApiError(429, "too_many_attempts", API_TEXT["too_many_attempts"], {"Retry-After": "600"})
		raise ApiError(401, "invalid_key", API_TEXT["invalid_key"])
	if row.status != ACTIVE:
		raise ApiError(401, "access_suspended" if row.status == SUSPENDED else "access_closed", API_TEXT["invalid_key"])
	if not catalogue_access.offered_to(row.customer):
		raise ApiError(401, "access_closed", API_TEXT["invalid_key"])
	return row


def record_use(row):
	"""Write when the key was last used, to the hour: a write for every call would be a lock for every call."""
	last = row.get("last_used_on")
	if last and frappe.utils.get_datetime(last) > frappe.utils.add_to_date(
		now_datetime(), minutes=-LAST_USED_RECORDED_MINUTES
	):
		return
	frappe.db.set_value(DOCTYPE, row.name, "last_used_on", now_datetime(), update_modified=False)
	frappe.db.commit()


def check_rate(row):
	"""Calls this minute against the access's allowance (429 with Retry-After when it is spent)."""
	if throttle.hit("partner-api", row.customer, 60) > (row.calls_per_minute or 60):
		raise ApiError(429, "rate_limited", API_TEXT["rate_limited"], {"Retry-After": "60"})
