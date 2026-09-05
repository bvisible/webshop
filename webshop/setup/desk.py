# //// Neoffice — added file (no upstream equivalent). Keeps the "Webshop" workspace on
# //// the desk: Frappe imports a workspace file once, and the Neoffice theme deletes,
# //// after every migrate, every workspace no App Customization lists (fa76f6b515,
# //// 2026-09-03 "l'espace Boutique en ligne survit au nettoyage du thème"; root page
# //// 01c6358b19). Upstream ships no workspace, so nothing there needs defending.
# Copyright (c) 2026, Neoffice. What keeps the Webshop workspace on the desk.
import os

import frappe

WORKSPACE = "Webshop"
PARENT_WORKSPACE = "Website"


def register_desk():
	"""Keep the Webshop workspace alive and reachable next to "Website".

	Two things can take it away. Frappe's sync only imports the workspace file
	once; a record deleted afterwards is not re-created. And the Neoffice theme
	removes, after every migrate, every workspace that no App Customization
	lists (its sidebar is built from those). So this runs after install and
	after migrate: re-import the file when the record is gone, and list the
	workspace in the customization that carries "Website" — whichever hook
	order the site has, the next cleanup then keeps it.
	"""
	ensure_workspace()
	ensure_app_customization_row()


def ensure_workspace():
	if frappe.db.exists("Workspace", WORKSPACE):
		return
	path = frappe.get_app_path("webshop", "webshop", "workspace", frappe.scrub(WORKSPACE), frappe.scrub(WORKSPACE) + ".json")
	if not os.path.exists(path):
		return
	from frappe.modules.import_file import import_file_by_path

	import_file_by_path(path, force=True)
	frappe.db.commit()


def ensure_app_customization_row():
	"""Add the workspace to the App Customization that lists "Website".

	A no-op on a site without the theme (the DocType does not exist) or on a
	site whose sidebar does not list "Website" at all: there is then nothing to
	attach to, and nothing that would delete the workspace either.
	"""
	if not frappe.db.exists("DocType", "App Customization"):
		return
	if frappe.db.exists("App Customization Workspace", {"workspace_name": WORKSPACE}):
		return
	parent_row = frappe.db.get_value(
		"App Customization Workspace",
		{"workspace_name": PARENT_WORKSPACE},
		["parent", "sort_order"],
		as_dict=True,
	)
	if not parent_row:
		return
	customization = frappe.get_doc("App Customization", parent_row.parent)
	# A root page on purpose: the theme's sidebar lists only the root pages of
	# a module (children never show), so the workspace sits next to "Website"
	# in the same module rather than under it.
	customization.append(
		"workspaces",
		{
			"workspace_name": WORKSPACE,
			"sort_order": (parent_row.sort_order or 0) + 1,
		},
	)
	customization.flags.ignore_permissions = True
	customization.save()
	frappe.db.commit()
