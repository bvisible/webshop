# //// Neoffice — added file (no upstream equivalent)
"""The shop's door to the theme's localized content (multilingual lot 1, neoffice-maintenance#2029).

Translations of the shop's data (product names and texts) live in the theme (`neoffice_theme.localized`),
which also decides the language of the request. The shop calls this façade only: without the theme, or
on a site that enabled no additional language, every function is a no-op and the page is the source's.

A failure of the translation layer costs the translation, never the page.
"""

import frappe


def _engine():
	try:
		from neoffice_theme import localized
	except ImportError:
		return None
	return localized


def content_language():
	"""The additional language of this request, or None for the site's own."""
	engine = _engine()
	if engine is None:
		return None
	try:
		return engine.content_language()
	except Exception:  # noqa: BLE001 — see the module docstring
		frappe.log_error("Localized content: language resolution failed", frappe.get_traceback())
		return None


def cache_suffix():
	"""Append to the key of any cache that holds localized text. Empty in the site's own language."""
	lang = content_language()
	return f":{lang}" if lang else ""


def localize_rows(doctype, rows, fieldnames, name_field="name"):
	"""Replace, in place, the listed fields of each row by their translation when there is one to show."""
	engine = _engine()
	if engine is None or not rows:
		return rows
	try:
		return engine.localize_rows(doctype, rows, fieldnames, name_field)
	except Exception:  # noqa: BLE001 — see the module docstring
		frappe.log_error("Localized content: bulk read failed", frappe.get_traceback())
		return rows


def localize_value(doctype, name, fieldname, default=None):
	engine = _engine()
	if engine is None:
		return default
	try:
		return engine.localize_value(doctype, name, fieldname, default)
	except Exception:  # noqa: BLE001 — see the module docstring
		frappe.log_error("Localized content: read failed", frappe.get_traceback())
		return default


def localize_items(rows, fieldnames=("web_item_name", "short_description")):
	"""Like localize_rows, for rows that name a Website Item by its item code (recommendations, carousels)."""
	if not rows or content_language() is None:
		return rows
	codes = [r.get("item_code") for r in rows if r.get("item_code")]
	if not codes:
		return rows
	names = dict(frappe.get_all("Website Item", filters={"item_code": ["in", codes]}, fields=["item_code", "name"], as_list=True))
	for row in rows:
		row["_website_item"] = names.get(row.get("item_code"))
	try:
		localize_rows("Website Item", rows, list(fieldnames), name_field="_website_item")
	finally:
		for row in rows:
			row.pop("_website_item", None)
	return rows


def label(doctype, name):
	"""The display name of a record whose name IS its label (item group, brand, attribute): never a value to look up."""
	return localize_value(doctype, name, "name", name)


def localize_labels(doctype, rows, key="name"):
	"""Display copies of rows that carry such a name under `key`. Never hand the result back to a lookup by name."""
	if not rows or content_language() is None:
		return rows
	try:
		return localize_rows(doctype, rows, ["name"], name_field=key)
	except Exception:  # noqa: BLE001 — see the module docstring
		frappe.log_error("Localized content: labels failed", frappe.get_traceback())
		return rows


def search_condition(doctype, name_sql, fieldnames, word):
	"""``(sql, values)`` matching a search word against the visible translations, or None."""
	engine = _engine()
	if engine is None or content_language() is None:
		return None
	try:
		return engine.search_condition(doctype, name_sql, fieldnames, word)
	except Exception:  # noqa: BLE001 — see the module docstring
		frappe.log_error("Localized content: search clause failed", frappe.get_traceback())
		return None


def site_languages():
	"""``{language: {"hreflang", "publication"}}`` of the additional languages the site enabled; empty when none."""
	engine = _engine()
	if engine is None:
		return {}
	try:
		return engine.site_languages()
	except Exception:  # noqa: BLE001 — see the module docstring
		frappe.log_error("Localized content: site languages failed", frappe.get_traceback())
		return {}


def hreflang_of(language):
	return (site_languages().get(language) or {}).get("hreflang") or language


def source_hreflang():
	engine = _engine()
	return engine.source_hreflang() if engine is not None else ""


def translated_documents(doctype, names):
	"""``{language: {names}}`` of the documents a visitor can read in that language (one rule for a page and a sitemap)."""
	engine = _engine()
	if engine is None or not site_languages():
		return {}
	try:
		return engine.translated_documents(doctype, names)
	except Exception:  # noqa: BLE001 — see the module docstring
		frappe.log_error("Localized content: translated documents failed", frappe.get_traceback())
		return {}


def translated_languages(doctype, name):
	engine = _engine()
	if engine is None or not site_languages():
		return []
	try:
		return engine.translated_languages(doctype, name)
	except Exception:  # noqa: BLE001 — see the module docstring
		frappe.log_error("Localized content: translated languages failed", frappe.get_traceback())
		return []


def page_identity(path):
	engine = _engine()
	return engine.page_identity(path) if engine is not None and site_languages() else None


# --- multilingual lot 5 (neoffice-maintenance#2033): a buyer's cart, order and wishlist in the buyer's language ----------


def document_language(doc=None):
	"""The additional language a document is read in (the request's, else the document's own), or None."""
	engine = _engine()
	reader = getattr(engine, "document_language", None)
	if reader is None:
		return None
	try:
		return reader(doc)
	except Exception:  # noqa: BLE001 — see the module docstring
		frappe.log_error("Localized content: document language failed", frappe.get_traceback())
		return None


def stamp_language(doc):
	"""Remember on a document the language its buyer reads the shop in (``language``, the print language the desk, the PDFs
	and the e-mails read). Only a request that speaks stamps: a payment callback must not turn a German order French."""
	engine = _engine()
	speaker = getattr(engine, "explicit_language", None)
	if speaker is None or doc is None or not doc.meta.has_field("language"):
		return doc
	try:
		language = speaker()
		if language and doc.get("language") != language:
			doc.language = language
	except Exception:  # noqa: BLE001 — see the module docstring
		frappe.log_error("Localized content: stamping the language failed", frappe.get_traceback())
	return doc


def localize_lines(doc, fieldnames=("web_item_name", "short_description"), language=None):
	"""Give each line of a cart, an order or an invoice the product's name and short text in the language it is read in.

	The copies are ``display_name`` and ``display_description``, never ``item_name`` and ``description``: those say what was
	sold, stay the document's, and would be saved in the reader's language by the next ``save()``. A variant has no
	translation of its own and keeps the line's name. Without the theme or a language, nothing is added.
	"""
	rows = doc.get("items") if doc is not None and hasattr(doc, "get") else None
	language = language or (document_language(doc) if rows else None)
	if not language or not rows:
		return doc
	try:
		codes = [row.get("item_code") for row in rows if row.get("item_code")]
		names = dict(
			frappe.get_all(
				"Website Item", filters={"item_code": ["in", codes]}, fields=["item_code", "name"], as_list=True
			)
		)
		found = _engine().get_translations("Website Item", list(names.values()), list(fieldnames), language)
		for row in rows:
			site_item = names.get(row.get("item_code"))
			name = found.get((site_item, "", "web_item_name"))
			text = found.get((site_item, "", "short_description"))
			if name:
				row.display_name = name
			if text:
				row.display_description = text
	except Exception:  # noqa: BLE001 — see the module docstring
		frappe.log_error("Localized content: the lines of a document could not be translated", frappe.get_traceback())
	return doc


def translation_rows(doctype, names, fieldnames, language):
	"""``[{ref_name, fieldname, text, human}]`` of the translations of a document type's fields a visitor may read.

	``human`` says a person wrote or reviewed the text; the feed to Merchant Center declares the machine's.
	"""
	engine = _engine()
	names = [n for n in dict.fromkeys(names or []) if n]
	if engine is None or not names or not language:
		return []
	try:
		found = engine.get_translations(doctype, names, list(fieldnames), language)
		if not found:
			return []
		people = engine.HUMAN_STATUSES
		meta = {
			(row.ref_name, row.fieldname): row
			for row in frappe.get_all(
				"Content Translation",
				filters={
					"ref_doctype": doctype,
					"ref_name": ["in", names],
					"fieldname": ["in", list(fieldnames)],
					"language": language,
					"row_name": "",
				},
				fields=["ref_name", "fieldname", "status", "origin"],
				limit_page_length=0,
			)
		}
		rows = []
		for (name, _row, fieldname), text in found.items():
			row = meta.get((name, fieldname))
			human = bool(row and (row.status in people or row.origin == "Human"))
			rows.append({"ref_name": name, "fieldname": fieldname, "text": text, "human": human})
		return rows
	except Exception:  # noqa: BLE001 — see the module docstring
		frappe.log_error("Localized content: reading translations failed", frappe.get_traceback())
		return []


def untranslated_legal_pages(language):
	"""The routes of the site's legal pages (terms, privacy, legal notice, shipping and returns) not translated yet."""
	engine = _engine()
	if engine is None or "builder" not in frappe.get_installed_apps():
		return []
	try:
		from builder.hf_utils.header_footer import LEGAL_FOOTER_ROUTES

		profile = getattr(frappe.local, "website_profile", None)
		filters = {"published": 1, "route": ["in", list(LEGAL_FOOTER_ROUTES)]}
		pages = frappe.get_all("Builder Page", filters=filters, fields=["name", "route", "neo_website_profile"])
		pages = [p for p in pages if not p.neo_website_profile or p.neo_website_profile == profile]
		done = engine.translated_documents("Builder Page", [p.name for p in pages]).get(language, set())
		return sorted({p.route for p in pages if p.name not in done})
	except Exception:  # noqa: BLE001 — see the module docstring
		frappe.log_error("Localized content: legal pages check failed", frappe.get_traceback())
		return []


def translated_names(doctype, fieldnames, language, word):
	"""The names of the documents whose translation (in ``language``, readable by a visitor) of one of ``fieldnames`` holds ``word``."""
	engine = _engine()
	word = (word or "").strip()
	if engine is None or not language or len(word) < 2 or language not in (site_languages() or {}):
		return []
	try:
		people = engine.HUMAN_STATUSES
		visible = (*people, *engine.MACHINE_STATUSES)
		return frappe.get_all(
			"Content Translation",
			filters={
				"ref_doctype": doctype,
				"language": language,
				"row_name": "",
				"fieldname": ["in", list(fieldnames)],
				"status": ["in", list(visible)],
				"text": ["like", f"%{word}%"],
			},
			pluck="ref_name",
			limit_page_length=50,
		)
	except Exception:  # noqa: BLE001 — see the module docstring
		frappe.log_error("Localized content: searching translations failed", frappe.get_traceback())
		return []


def address_in(url, language):
	"""``url`` (absolute, or root-relative) under the prefix of ``language``: a link in a mail leads to the page in that language."""
	from urllib.parse import urlsplit, urlunsplit

	if not language or not url:
		return url
	parts = urlsplit(url)
	path = parts.path if parts.path.startswith("/") else "/" + parts.path
	prefixed = f"/{language}" + ("" if path == "/" else path)
	return urlunsplit((parts.scheme, parts.netloc, prefixed, parts.query, parts.fragment))


def mail_language(*candidates, profile=None):
	"""The additional language a mail is written in, or None for the site's own.

	The first of ``candidates`` (the language of the purchase or of the cart, the customer's, the user's) that the site speaks
	besides its own. A job has no request, hence no profile of the visitor: the site's languages are read from its profiles.
	"""
	try:
		from neoffice_theme.translation.units import enabled_languages
	except ImportError:
		return None
	try:
		spoken = set(enabled_languages(profile) or enabled_languages())
	except Exception:  # noqa: BLE001 — see the module docstring
		frappe.log_error("Localized content: the languages of the mails are unreadable", frappe.get_traceback())
		return None
	return next((code for code in candidates if code and code in spoken), None)


def mail_texts(template, language):
	"""``(subject, body)`` of an Email Template in ``language``; a part with no translation is None."""
	rows = translation_rows("Email Template", [template.name], ("subject", "response", "response_html"), language)
	found = {row["fieldname"]: row["text"] for row in rows}
	return found.get("subject"), found.get("response_html" if template.get("use_html") else "response")
