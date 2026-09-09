# //// Neoffice — added file (no upstream equivalent). The guard of #277.
"""Price and save a customer's own cart with the shop's rights, then hand it back.

Why this exists (neoffice-maintenance#277). Upstream ERPNext version-15 now checks,
inside a quotation's validate:

    get_item_details       item = frappe.get_cached_doc("Item", ...); item.check_permission()
    get_party_account      frappe.has_permission(party_type, ptype, party, throw=True)

Both look at the SESSION user. A portal customer (Website User, role Customer) reads
neither Item nor Account -- and must not: granting Item read to Customer would expose
purchase and valuation fields through frappe.client.get_list. So the day the fork merges
upstream (41effcf754, 2026-07-28), every cart save, address change, shipping rule and
checkout of a signed-in customer raises PermissionError. `quotation.flags.ignore_permissions`
does not help: it covers the Quotation, not the Item and Account the session user is
asked about.

The shop therefore prices its own published items on the customer's behalf: run the
pricing and the save as Administrator, restore the session, and put the customer back
as owner and modified_by so the cart stays THEIRS (list views, `if_owner` permissions,
"my orders" all key on owner). quick_order/api.py carries the original of this pattern
(`_save_on_behalf`, 0928431668); this is the same thing for the classic cart.

Nothing here widens what a customer can READ. It only lets the shop compute a price.
"""

from contextlib import contextmanager

import frappe


@contextmanager
def shop_rights():
	"""Run the block as Administrator, put the session back EXACTLY as it was.

	🔴 Not `frappe.set_user(user)` on the way out. set_user does not switch a
	user, it rewrites the live session in place: `local.session.sid = username`
	and `local.session.data = {}`. Restoring "the user" that way left every
	customer with a session whose sid was their e-mail and whose data (csrf
	token, device, stamped expiry) was gone — and set_cart_count runs this
	block ON LOGIN, so the sid cookie handed to the browser named no session
	at all: a portal customer was signed out by the very act of signing in.
	Found 2026-09-09 on the pilot club's members (the sid cookie read
	"gym-a%40yopmail.com"). What Administrator's rights need is the user; what
	the customer needs back is their session, field by field.
	"""
	session = frappe.local.session
	user = session.user
	if user == "Administrator":
		yield
		return
	saved = {"sid": session.sid, "data": session.data}
	form_dict = frappe.local.form_dict
	frappe.set_user("Administrator")
	try:
		yield
	finally:
		session.user = user
		session.sid = saved["sid"]
		session.data = saved["data"]
		frappe.local.form_dict = form_dict
		# what set_user rightly drops on a switch, dropped again on the way back
		frappe.local.cache = {}
		frappe.local.jenv = None
		frappe.local.role_permissions = {}
		frappe.local.new_doc_templates = {}


def save_as_shop(doc, submit=False, **save_kwargs):
	"""Save (or submit) `doc` with the shop's rights, and give it back to the customer.

	owner is re-stamped only when the document was NEW: a cart created under the
	shop's rights would otherwise belong to Administrator, and the customer would
	stop seeing it. modified_by is re-stamped every time, so the audit trail keeps
	saying who acted.
	"""
	user = frappe.session.user
	was_new = doc.is_new()
	with shop_rights():
		if submit:
			doc.submit()
		else:
			doc.save(**save_kwargs)
	if user != "Administrator":
		stamp = {"modified_by": user}
		if was_new:
			stamp["owner"] = user
		frappe.db.set_value(doc.doctype, doc.name, stamp, update_modified=False)
		doc.update(stamp)
	return doc
