# //// Neoffice — added file (no upstream equivalent). The shop's half of signing in with a code
# //// (neoffice-maintenance#2192): the engine is the frappe fork's `frappe.passwordless` (code and link mailed
# //// to the person, the same answer for every address); this module opens the account when the address has none.
"""Signing in with a code, from the shop's dialog.

The dialog asks `frappe.passwordless.request_code` for a code and `verify_code` for the answer. An address that
already has an account is signed in there. An address that has none comes back with the PROOF of its mailbox, and
`complete_sign_up` below turns that proof and a name into an account that is open at once and already confirmed:
the person typed what only the owner of the mailbox could read, so there is nothing left to confirm by a welcome
email (D-9's `email_confirmation_pending` is for the path with no proof).

On a site that runs stock Frappe (the CI) the engine does not exist: `available()` is False, the dialog keeps the
password and nothing here is called.
"""

import frappe
from frappe import _
from frappe.utils import cint, strip_html

from webshop.webshop.utils.throttle import throttle

NAME_LENGTH = 80


def available() -> bool:
	"""Whether this site signs in with a code: the engine is installed, the switch is on and a mail can leave."""
	try:
		from frappe.passwordless import is_enabled
	except ImportError:  # stock frappe: the fork's engine is not there
		return False
	return bool(is_enabled())


def signup_closed() -> bool:
	"""Hook `passwordless_signup_closed`: on a site for business accounts only an account is opened by a person at the
	shop, never by a mailbox, so the engine offers no new account there."""
	from webshop.webshop.multi_site import site_is_business_only

	return bool(site_is_business_only())


def brand() -> str:
	"""Hook `passwordless_brand`: the name the mail speaks for is the shop being served (the site chrome's name, per
	site), not the bench's. Empty when the site was never named: the engine then says the site's own application name."""
	from webshop.webshop.seo.site import shop_name

	return shop_name()


def _clean_name(value) -> str:
	return strip_html(value).strip()[:NAME_LENGTH] if isinstance(value, str) else ""


def _refuse(reason_code: str, reason: str) -> dict:
	return {"message": "error", "reason": reason, "reason_code": reason_code}


# //// Neoffice — reviewed for guests (frappe's semgrep rule guest-whitelisted-method): it opens a Website User
# //// with the Customer role and nothing else, only for an address whose mailbox `frappe.passwordless` proved a
# //// moment ago (the proof is single-use and lives 15 minutes), refuses an address any staff account holds,
# //// and is limited per connection and per hour like `create_account`.
@frappe.whitelist(allow_guest=True, methods=["POST"])  # nosemgrep: frappe-semgrep-rules.rules.security.guest-whitelisted-method
@throttle("complete_sign_up", 10, 3600)
def complete_sign_up(proof=None, first_name=None, last_name=None, redirect_to=None):
	try:
		from frappe.passwordless import consume_proof, sign_in
	except ImportError:
		return _refuse("unavailable", _("Signing in with a code is not available on this site."))

	from webshop.webshop.auth.api import _count_sign_up, _sign_ups_so_far, SIGN_UPS_PER_HOUR, new_website_user, signups_disabled

	first_name, last_name = _clean_name(first_name), _clean_name(last_name)
	if not first_name or not last_name:
		return _refuse("missing_fields", _("Please enter your first and last name"))
	if signups_disabled() or signup_closed():
		return _refuse(
			"signup_disabled", _("New accounts cannot be created on this site. Please contact the shop.")
		)
	if _sign_ups_so_far() >= SIGN_UPS_PER_HOUR:
		frappe.local.response.http_status_code = 429
		return _refuse("too_many_signups", _("Too many accounts were created in the last hour. Please try again later."))

	# The proof is consumed only now, after every refusal that the person can fix without a new code
	address = consume_proof(proof)
	if not address:
		return _refuse("invalid_proof", _("This confirmation has expired. Ask for a new code."))

	existing_type = frappe.db.get_value("User", address, "user_type")
	if existing_type == "System User":
		return _refuse(
			"account_exists_system",
			_("This email is already linked to an administrator account. Please contact your administrator or use a different email."),
		)

	user_name = address
	if not existing_type:
		user = new_website_user(address, first_name, last_name)
		try:
			user.insert(ignore_permissions=True)
			_count_sign_up()
		except frappe.DuplicateEntryError:  # a parallel request opened it first; the mailbox is proven all the same
			frappe.clear_messages()
		else:
			user_name = user.name

	result = sign_in(user_name, redirect_to)
	if not result.get("ok"):
		return _refuse("not_allowed", _("Signing in with a code is not available for this account."))
	return {
		"message": "success",
		"signed_in": True,
		"redirect_to": result["redirect_to"],
		"notice": _("Your account is open and you are signed in."),
	}
