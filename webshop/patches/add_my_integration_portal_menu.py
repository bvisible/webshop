# //// Neoffice — added file (no upstream equivalent).
"""The reseller's integration page enters the account menu on existing sites (2026-11-01).

`standard_portal_menu_items` (hooks.py) is read by Portal Settings' `sync_menu`, which a fresh install runs and
`bench migrate` does not. Idempotent: `add_item` skips a route already listed. The entry only shows to the customers
of the groups the shop allowed for the reseller catalogue (utils/account_menu.py), so a site that has not switched
the catalogue on shows nothing new.
"""

import frappe


def execute():
	if not frappe.db.exists("DocType", "Portal Settings"):
		return
	frappe.get_single("Portal Settings").sync_menu()
