# //// Neoffice — added file (no upstream equivalent).
"""The language of the texts of a catalogue (reseller catalogue, lot 5c).

A reseller whose customers read German asks for the German texts: the name and the description of each product, as the
shop's own German visitors read them. The translations are the multilingual project's (`utils/localized.py`, the
theme's `Content Translation`): this module only asks for them, as a visitor of the site would, and puts them in place of
the source's. A product with no visible translation keeps its source text, and without the theme or a language the
catalogue is what it always was.

The language is chosen from the additional languages the site enabled (what its visitors can read), checked when it is
asked for; the job that makes the catalogue reads it back from the stored options.
"""

import re
from contextlib import contextmanager

import frappe

from webshop.webshop.utils import localized

FIELDS = ("web_item_name", "short_description", "web_long_description")
# a language code as Frappe writes it: de, fr, pt-BR
_CODE = re.compile(r"[a-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})?")


def clean(raw):
	"""The language option: "" (the site's own language) or a code. Anything else is a ValueError."""
	if raw in (None, ""):
		return ""
	if not isinstance(raw, str) or not _CODE.fullmatch(raw.strip()):
		raise ValueError("bad_language")
	return raw.strip()


def offered():
	"""[{"code", "name"}]: the additional languages the site enabled, as the request is served (empty when none)."""
	codes = list(localized.site_languages())
	names = dict(frappe.get_all("Language", filters={"name": ["in", codes]}, fields=["name", "language_name"], as_list=True)) if codes else {}
	return [{"code": code, "name": names.get(code) or code} for code in codes]


def is_offered(code):
	return code in localized.site_languages()


@contextmanager
def as_visitor():
	"""Read the translations as a visitor of the site would, in a job.

	The theme shows staff the machine translations a site holds back until they are reviewed (`can_preview`): a catalogue
	made by a job that runs as staff would print what the shop does not show yet. In a web request the identity is the
	caller's own (a reseller is no staff) and `frappe.set_user` would spoil the live session: nothing is switched there."""
	if getattr(frappe.local, "session_obj", None):
		yield
		return
	user = frappe.session.user
	frappe.set_user("Guest")  # nosemgrep: frappe-semgrep-rules.rules.security.frappe-setuser
	try:
		yield
	finally:
		frappe.set_user(user)  # nosemgrep: frappe-semgrep-rules.rules.security.frappe-setuser


def texts(names, language):
	"""{Website Item name: {field: text}} of what a visitor of the site reads in `language`; {} when there is none."""
	if not language or not names:
		return {}
	with as_visitor():
		found = localized.translation_rows("Website Item", list(names), FIELDS, language)
	by_name = {}
	for row in found:
		if (row.get("text") or "").strip():
			by_name.setdefault(row["ref_name"], {})[row["fieldname"]] = row["text"]
	return by_name


def in_language(url, language):
	"""A page of the shop under the prefix of `language`, as its visitors reach it."""
	return localized.address_in(url, language) if language else url
