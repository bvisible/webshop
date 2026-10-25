# //// Neoffice — added file (no upstream equivalent).
"""One menu on every page of the customer's account (2026-10-25, neoffice-maintenance sidebar audit).

The account's left menu is Frappe's portal menu: the enabled rows of Portal Settings, kept for the
roles of the signed-in user, cached per user. Three things made it vanish or lie:

- the three links of `/me` (edit profile, password, third-party apps) lead to pages that never asked
  for a sidebar, so the menu disappeared at the first click;
- a Web Form builds its `sidebar_items` only when it names a Website Sidebar (`web_form.py`), so
  the address form and the legacy issue list showed a column holding « My account » alone;
- both the roles and the menu are cached for good (no expiry) and only a `User.save()` drops
  them. A role row written another way (SQL, a script, a cache refilled between a clear and its
  commit) leaves the old roles in the cache: the menu then lists pages the account cannot open, or
  hides those it can, until somebody clears the cache of the whole site.
"""

import frappe

# What `frappe.permissions.get_roles` adds around the rows of `Has Role`: never stored there.
AUTOMATIC_ROLES = frozenset({"Administrator", "Guest", "All", "Desk User"})


def stored_roles(user: str) -> set[str]:
	"""The roles the database gives `user`, as `Has Role` holds them."""
	rows = frappe.get_all("Has Role", filters={"parenttype": "User", "parent": user}, pluck="role")
	return set(rows) - AUTOMATIC_ROLES


def heal_stale_roles(user: str) -> bool:
	"""Drop what the cache keeps of `user` when it says other roles than the database.

	True when it dropped it. The cache is cleared the way a save clears it (roles, portal menu,
	permissions derived from the roles), so the next reader computes everything from the rows.
	"""
	if not user or user in ("Guest", "Administrator"):
		return False

	cached = frappe.cache.hget("roles", user)
	if cached is None:
		return False

	known = set(cached) - AUTOMATIC_ROLES
	stored = stored_roles(user)
	if known == stored:
		return False

	# frappe's loggers start at ERROR (`frappe.log_level` is unset): a `warning` is dropped, and the
	# heal would leave no trace. A GET is never committed, so an Error Log row would be lost too.
	frappe.logger("webshop").error(
		"Stale roles cache for %s: cached %s, stored %s",
		user,
		sorted(known),
		sorted(stored),
	)
	frappe.clear_cache(user=user)
	return True


def give_the_account_its_menu(context) -> None:
	"""Make a page of the signed-in customer's account show the account's menu.

	Called from `update_website_context` for the pages `is_account_page` recognises, after the
	page has built its own context. A visitor has no account: nothing changes for them.
	"""
	user = frappe.session.user
	if not user or user == "Guest":
		return

	healed = heal_stale_roles(user)

	# A page of the account is a page with the menu, whichever way the page was reached.
	context["show_sidebar"] = True

	# A template page already carries the portal menu (Frappe falls back to it); a web form does
	# not. After a heal, the menu a page computed from the stale roles is replaced too.
	if healed or not context.get("sidebar_items"):
		from frappe.website.utils import get_portal_sidebar_items

		context["sidebar_items"] = get_portal_sidebar_items()
