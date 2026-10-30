# //// Neoffice — added file (no upstream equivalent). neoffice-maintenance#2012.
"""The WebP copies of the shop's pictures (/files/wsr) become readable by the web server (2026-10-30).

They were written through a temporary file made by `tempfile.mkstemp`, which is readable by its owner only (0600):
nginx runs as another user, found the copy, could not read it and answered 403 instead of handing the request to
Frappe, so every product card of a shop lost its picture. `make_rendition` sets the mode now; this puts it right
on the copies already written. It only adds the read bit for everyone, so it can run again."""

import os

import frappe

from webshop.webshop.utils.renditions import FOLDER


def execute():
	folder = frappe.get_site_path("public", "files", FOLDER)
	if not os.path.isdir(folder):
		return
	fixed = 0
	with os.scandir(folder) as entries:
		for entry in entries:
			if entry.is_file() and not entry.stat().st_mode & 0o004:
				os.chmod(entry.path, 0o644)
				fixed += 1
	if fixed:
		print(f"{fixed} picture copies made readable")
