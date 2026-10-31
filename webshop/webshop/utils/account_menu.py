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


# --- what the menu calls its entries, and when it offers them (2026-10-25) --------------------------
#
# The portal menu is the rows of Portal Settings, aggregated from five apps, and a row keeps the title
# and the route it was created with: `sync_menu` never renames one. A customer therefore read « Mes
# réservations » and « Assistance/Support » on two lines, French addresses (/sav, /mes-reservations) next
# to English ones, and an entry for courses on a site that has none. What a customer reads is said here,
# once, whatever the row says; the data of the instances is left as it is.

# An entry's old address and its address now (the old one redirects, so a row that still holds it works).
MOVED = {
	"/sav": "/my-requests",
	"/mes-reservations": "/my-bookings",
	"/gift_cards": "/gift-cards",
	"/loyalty_points": "/loyalty-points",
	"/addresses": "/my-addresses",
	"/my_addresses": "/my-addresses",
}


def N_(text: str) -> str:
	"""Marks a msgid for the extractor (gettext's own convention) and returns it: the sidebar's template
	translates `item.title` when it draws it, so the catalogue needs the word, not a translated copy."""
	return text


def shop_is_on() -> bool:
	"""The e-commerce is active: the shopping cart of Webshop Settings is on."""
	return bool(frappe.db.get_single_value("Webshop Settings", "enabled"))


def support_title() -> str:
	"""The word for the support. After the sale in a shop (« SAV »); a ticket anywhere else.

	English msgids, translated where the menu is drawn. The support page names itself the same way
	(neoffice_theme.support.support_label): change both together.
	"""
	return N_("After-sales") if shop_is_on() else N_("Tickets")


def support_is_offered() -> bool:
	try:
		from neoffice_theme.support import support_enabled
	except ImportError:
		return True
	return support_enabled()


def courses_are_offered() -> bool:
	"""Courses are offered when the site shows them and one is published (LMS's own rule for its public page)."""
	if not frappe.db.exists("DocType", "LMS Course"):
		return False
	if frappe.get_meta("LMS Settings").has_field("neo_show_on_website") and not frappe.db.get_single_value(
		"LMS Settings", "neo_show_on_website"
	):
		return False
	return bool(frappe.db.exists("LMS Course", {"published": 1}))


def reseller_catalogue_is_offered() -> bool:
	"""The brand and catalogues pages of the reseller catalogue: the customers of the groups the shop allowed, nobody else."""
	from webshop.webshop.catalogue.access import is_offered

	return is_offered()


def switch_is_on(field: str):
	return lambda: bool(frappe.db.get_single_value("Webshop Settings", field))


# route -> (title, is it offered). A title is an English msgid, or a function that returns one.
ENTRIES = {
	"/my-requests": (support_title, support_is_offered),
	"/my-bookings": (N_("Bookings"), None),
	# "Courses" is « Plats » in the catalogue of the site (ERPNext's restaurant meals): a word of its own.
	"/lms/courses": (N_("Trainings"), courses_are_offered),
	"/my-projects": (N_("Projects"), None),
	"/gift-cards": (N_("Gift cards"), switch_is_on("enable_gift_cards")),
	"/loyalty-points": (N_("Loyalty"), switch_is_on("enable_loyalty_points")),
	"/my-brand": (N_("Brand"), reseller_catalogue_is_offered),
	"/my-catalogues": (N_("Catalogues"), reseller_catalogue_is_offered),
}


def adapt_menu(items) -> list:
	"""The portal's rows as the customer reads them: new addresses, short titles, only what the site offers.

	Each row is copied (the cached list is shared by every page of the user), an entry two rows give is
	drawn once, and an entry the site does not offer is left out.
	"""
	seen, adapted = set(), []
	for item in items or []:
		route = MOVED.get(item.get("route"), item.get("route"))
		if route in seen:
			continue
		title, offered = ENTRIES.get(route, (None, None))
		if offered is not None and not offered():
			continue
		seen.add(route)
		row = frappe._dict(item)
		row["route"] = route
		if title:
			row["title"] = title() if callable(title) else title
		adapted.append(row)
	return adapted


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

	context["sidebar_items"] = adapt_menu(context.get("sidebar_items"))
