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
- An order it pays on account, the one way of paying that ships before the money is in, waits On
  Hold and marked (HELD_FIELD) until the address is confirmed, then is released
  (hold_until_confirmed, release_held_orders). Only the orders this module held are released: a
  merchant's own hold is never lifted by a customer signing in.

Only an address the shop does not know is opened at once. get_party() attaches a new account to
the Customer whose Contact carries its address, with that customer's addresses and orders. Opening
such an address without proof would hand a stranger somebody else's account: those addresses keep
the confirmation first. So does a site that serves business accounts only, where an unconfirmed
account is still an anonymous visitor.
"""

import frappe
from frappe import _
from frappe.utils import cint, strip_html

FIELD = "email_confirmation_pending"
# Sales Order: held because its account's address was not confirmed yet (patches/add_email_confirmation_hold_field)
HELD_FIELD = "awaiting_email_confirmation"


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
	customer prove nothing about the address: the desk's impersonation comes with the staff's own
	session, and `bench browse` signs in from outside any HTTP request, after resuming a Guest
	session of its own (LoginManager() outside a request), so it looked exactly like a visitor
	coming back through the mailbox and confirmed the account (measured on osiris, 2026-09-26)."""
	user = login_manager.user
	if frappe.flags.get("webshop_opening_account") or not pending(user):
		return
	# a sign-in outside an HTTP request (bench browse, a console, a job) is never the mailbox's
	if not getattr(frappe.local, "http_request", None):
		return
	if frappe.session.user not in ("Guest", user):
		return
	from frappe.sessions import clear_sessions

	frappe.db.set_value("User", user, FIELD, 0, update_modified=False)
	# whoever opened the account without owning the address loses the session they kept
	clear_sessions(user, keep_current=False, force=True)
	# the orders it paid on account were waiting for this; released in the background, where the
	# user can be switched (release_held_orders)
	if held_orders(user):
		frappe.enqueue(
			"webshop.webshop.auth.confirmation.release_held_orders", user=user, enqueue_after_commit=True
		)


def can_hold_orders() -> bool:
	# the marker comes with a patch: until the site migrates, payment on account is not offered
	return frappe.get_meta("Sales Order").has_field(HELD_FIELD)


def hold_until_confirmed(sales_order: str):
	"""Hold an order paid on account by an account whose address is not confirmed yet, marked so
	that the confirmation releases it (release_held_orders). The timeline says why the order waits:
	the desk's simple view does not show the mark."""
	from frappe.translate import get_user_lang

	frappe.db.set_value("Sales Order", sales_order, {"status": "On Hold", HELD_FIELD: 1})
	# written during the customer's request, read by the shop's staff: in the staff's language, as
	# release_held_orders writes its own note, and the response keeps the customer's
	lang = frappe.local.lang
	frappe.local.lang = get_user_lang("Administrator") or lang
	try:
		note = "{} — {}".format(
			_("On hold until the customer confirms their email address"),
			_(
				"Paid on account from an account opened in the shop whose address is not confirmed yet. "
				"The confirmation releases the order; resuming it by hand works too."
			),
		)
	finally:
		frappe.local.lang = lang
	frappe.get_doc("Sales Order", sales_order).add_comment("Info", note)


def held_orders(user: str) -> list:
	"""The orders of this account still held for its confirmation."""
	if not can_hold_orders():
		return []
	return frappe.get_all(
		"Sales Order",
		filters={HELD_FIELD: 1, "owner": user, "docstatus": 1, "status": "On Hold"},
		pluck="name",
	)


def release_held_orders(user: str):
	"""Background job (on_login): release the orders this account paid on account before its address
	was confirmed. Each is resumed as the desk's Resume button does it (update_status("Draft"), which
	restores the computed status and checks the credit limit). One the credit limit refuses stays
	held, and its timeline says why. Run as Administrator, as any status the system changes; the
	timeline names the customer's confirmation."""
	if getattr(frappe.local, "session_obj", None):
		raise RuntimeError("confirmation.release_held_orders() switches the user: never inside a web request")
	lang = frappe.local.lang
	# reviewed: a background job only, refused inside a web request just above
	frappe.set_user("Administrator")  # nosemgrep: frappe-semgrep-rules.rules.security.frappe-setuser
	# a job starts in English: the timeline is read by the shop's staff, in the site's language
	frappe.set_user_lang("Administrator")
	try:
		for name in held_orders(user):
			frappe.db.savepoint("release_held_order")
			try:
				frappe.get_doc("Sales Order", name).update_status("Draft")
			except Exception as error:
				frappe.db.rollback(save_point="release_held_order")
				frappe.log_error(
					"Webshop: an order held for an email confirmation was not released", frappe.get_traceback()
				)
				frappe.get_doc("Sales Order", name).add_comment(
					"Info",
					_("{0} confirmed the email address, but the order stays on hold: {1}").format(
						user, strip_html(str(error)) or _("see the Error Log")
					),
				)
				continue
			frappe.get_doc("Sales Order", name).add_comment(
				"Info", _("{0} confirmed the email address: the order is no longer on hold.").format(user)
			)
	finally:
		frappe.local.lang = lang


def on_sales_order_change(doc, method=None):
	"""`on_change` of Sales Order (hooks.py): the marker lives only while the order is On Hold. An
	order resumed by hand, closed or cancelled is no longer this module's to release, so a hold the
	merchant puts on it later is never lifted by the customer's confirmation."""
	if cint(doc.get(HELD_FIELD)) and doc.get("status") != "On Hold":
		frappe.db.set_value("Sales Order", doc.name, HELD_FIELD, 0, update_modified=False)
		doc.set(HELD_FIELD, 0)
