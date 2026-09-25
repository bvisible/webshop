# //// Neoffice — added file (no upstream equivalent): an account opened at once in the shop, its
# //// address confirmed afterwards. neoffice-maintenance#691, decision D-9 of the SEO plan, 2026-09-25.
"""An account opened at once, confirmed afterwards (decision D-9 of the SEO plan).

A shopper who created an account in the shop was left signed out until they clicked the link of
the welcome email: the checkout's sign-in dialog came back, and a first order waited on a mailbox.
An agent buying for somebody, or a person in a hurry, stopped there.

The account is now opened and signed in at once, and the address is confirmed afterwards by the
same link. Until then the account is `email_confirmation_pending`:
- It has no password, so the only ways back in go through the mailbox: the welcome email's link,
  a sign-in link, a social login. The first of them confirms the address and closes every other
  session of the account, so whoever opened it without owning the address loses it.
- It is not offered payment on account (utils/payment_methods.py), the one way of paying that
  ships before the money is in.

Only an address the shop does not know is opened at once. get_party() attaches a new account to
the Customer whose Contact carries its address, with that customer's addresses and orders. Opening
such an address without proof would hand a stranger somebody else's account: those addresses keep
the confirmation first. So does a site that serves business accounts only, where an unconfirmed
account is still an anonymous visitor.
"""

import frappe
from frappe.utils import cint

FIELD = "email_confirmation_pending"


def _has_field() -> bool:
	# the field comes with a patch: until the site migrates, nothing is pending
	return frappe.get_meta("User").has_field(FIELD)


def pending(user=None) -> bool:
	"""Whether this account (the session's by default) was opened before its address was confirmed."""
	user = user or frappe.session.user
	if not user or user in ("Guest", "Administrator") or not _has_field():
		return False
	return bool(cint(frappe.db.get_value("User", user, FIELD)))


def opens_at_once(email: str, settings=None) -> bool:
	"""Whether an account created now for this address is opened and signed in at once."""
	from webshop.webshop.multi_site import site_is_business_only

	if settings is None:
		from webshop.webshop.doctype.webshop_settings.webshop_settings import get_shopping_cart_settings

		settings = get_shopping_cart_settings()
	if not cint(settings.get("open_account_at_once")) or not _has_field():
		return False
	if site_is_business_only():
		return False
	# an address a Contact already carries belongs to somebody the shop knows (see the module's note)
	return not frappe.db.exists("Contact Email", {"email_id": email})


def open_account(user: str):
	"""Mark the account pending and sign it in, in this request."""
	frappe.db.set_value("User", user, FIELD, 1, update_modified=False)
	frappe.flags.webshop_opening_account = True
	try:
		frappe.local.login_manager.login_as(user)
	finally:
		frappe.flags.webshop_opening_account = False


def on_login(login_manager):
	"""`on_login` hook (hooks.py): the first way back into a pending account confirms its address.

	It runs before the new session is made, while frappe.session is still the one the request came
	with: Guest, or the account itself in the browser that opened it. Staff signing in as the
	customer (impersonation, `bench browse`) come with their own session and prove nothing about
	the address."""
	user = login_manager.user
	if frappe.flags.get("webshop_opening_account") or not pending(user):
		return
	if frappe.session.user not in ("Guest", user):
		return
	from frappe.sessions import clear_sessions

	frappe.db.set_value("User", user, FIELD, 0, update_modified=False)
	# whoever opened the account without owning the address loses the session they kept
	clear_sessions(user, keep_current=False, force=True)
