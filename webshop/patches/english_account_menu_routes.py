# //// Neoffice — added file (no upstream equivalent).
"""The account's menu rows of the shop take their English hyphenated addresses (2026-10-25).

/gift_cards and /loyalty_points are /gift-cards and /loyalty-points now (the old addresses redirect), and
the loyalty entry joins the menu of every shop: it was only ever created by a patch that ran once, on the
instances where the setting was on that day. `sync_menu` adds a row by route and never renames one, so the
rows of the old routes are renamed first; otherwise each entry would be listed twice. The menu drawn for a
customer does not depend on this (utils/account_menu.py maps the old routes too): it keeps the data tidy.
"""

import frappe

RENAMED = {
	"/gift_cards": ("/gift-cards", "Gift cards"),
	"/loyalty_points": ("/loyalty-points", "Loyalty"),
}


def execute():
	if not frappe.db.exists("DocType", "Portal Settings"):
		return
	settings = frappe.get_single("Portal Settings")
	changed = False
	for row in settings.get("menu"):
		if row.route in RENAMED:
			row.route, row.title = RENAMED[row.route]
			changed = True
	if changed:
		settings.flags.ignore_permissions = True
		settings.save()
	settings.reload()
	settings.sync_menu()
