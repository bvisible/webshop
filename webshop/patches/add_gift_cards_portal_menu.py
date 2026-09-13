# //// Neoffice — added file (no upstream equivalent).
"""The customer's gift cards page enters the account menu on existing sites.

`standard_portal_menu_items` (hooks.py) is read by Portal Settings' `sync_menu`, which a
fresh install runs and `bench migrate` does not: without this patch a shop that already
existed never showed the entry. Idempotent — `add_item` skips a route already listed.
"""

import frappe


def execute():
	if not frappe.db.exists("DocType", "Portal Settings"):
		return
	settings = frappe.get_single("Portal Settings")
	settings.sync_menu()
