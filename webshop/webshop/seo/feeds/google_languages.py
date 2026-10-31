# //// Neoffice — added file (no upstream equivalent): one Merchant Center feed per language of a site
# //// (multilingual lot 5, neoffice-maintenance#2033).
"""A site that sells in German has two feeds: the French one, and ``google-de.xml`` that says the same thing in German.

Merchant Center takes the language of a feed from the feed's own setting, and compares each item with the page it links: so
the German feed links the German pages (``/de/...``), carries the German title and description, and holds only the products
whose page is fully translated (an untranslated one would send French text into a German feed). A text the machine translated
and no person read is declared as such (``structured_title`` and ``structured_description``, ``trained_algorithmic_media``): the
merchant is told which of their products Google will read as made by a model.

Merchant Center asks for the whole journey in the language before it accepts a feed: ``readiness`` says what is still French
(the products, the legal pages, the shop's own strings), and the report of Webshop Settings prints it beside the address.
"""

import os
from urllib.parse import urlsplit, urlunsplit

import frappe
from frappe import _

from webshop.webshop.utils import localized

FEED_ROUTE = "feeds/google-{language}.xml"
TRANSLATED_FIELDS = ("web_item_name", "web_long_description", "short_description")


def in_language(url: str, language: str) -> str:
	"""``url`` (absolute) under the language's prefix: ``https://shop.test/products/a`` -> ``https://shop.test/de/products/a``."""
	parts = urlsplit(url)
	path = parts.path if parts.path.startswith("/") else "/" + parts.path
	prefixed = f"/{language}" + ("" if path == "/" else path)
	return urlunsplit((parts.scheme, parts.netloc, prefixed, parts.query, parts.fragment))


def translations_of(names: list[str], language: str) -> dict:
	"""``{(name, fieldname): (text, by_a_person)}`` of the translations the feed may send, one query."""
	rows = localized.translation_rows("Website Item", names, TRANSLATED_FIELDS, language)
	return {(row["ref_name"], row["fieldname"]): (row["text"], row["human"]) for row in rows}


def localize_entry(entry: dict, doc, language: str, texts: dict) -> dict:
	"""The feed's item for a product, said in ``language``: title, description, address, and the machine's mark."""
	from webshop.webshop.seo.feeds import google
	from webshop.webshop.seo.text import html_to_text

	name, name_human = texts.get((doc.name, "web_item_name"), (None, True))
	title = (name or doc.web_item_name or doc.item_code)[: google.MAX_TITLE]
	long_text, long_human = texts.get((doc.name, "web_long_description"), (None, True))
	short_text, short_human = texts.get((doc.name, "short_description"), (None, True))
	body = long_text or short_text
	body_human = long_human if long_text else short_human
	description = html_to_text(body or "", google.MAX_DESCRIPTION) or title
	entry = dict(entry)
	entry["title"], entry["description"] = title, description
	entry["link"] = in_language(entry["link"], language)
	if entry.get("canonical_link"):
		entry["canonical_link"] = in_language(entry["canonical_link"], language)
	entry.pop("structured_description", None)  # the French flag said the French text was made with a model
	if name and not name_human:
		entry["structured_title"] = {"digital_source_type": "trained_algorithmic_media", "content": title}
	if body and not body_human:
		entry["structured_description"] = {
			"digital_source_type": "trained_algorithmic_media",
			"content": description,
		}
	return entry


def readiness(language: str, sent: int, untranslated: int) -> list[str]:
	"""What keeps the feed of ``language`` from being ready for Merchant Center: empty when nothing does.

	Merchant Center wants the journey, not only the product: the products the French feed sends, the legal pages the footer links,
	and the shop's own strings (cart, checkout) in the language of the feed.
	"""
	missing = []
	if not sent:
		missing.append(_("no product is translated yet"))
	elif untranslated:
		missing.append(_("{0} products the French feed sends are not translated yet").format(untranslated))
	if not os.path.exists(frappe.get_app_path("webshop", "locale", f"{language}.po")):
		missing.append(_("the shop's own texts (cart, checkout) have no translation in this language"))
	pages = localized.untranslated_legal_pages(language)
	if pages:
		missing.append(_("legal pages still in the site's language: {0}").format(", ".join(pages)))
	return missing


def build_language_feed(site, language: str):
	"""The XML of a site's feed in ``language`` and its report (``sent``, ``left_out``, ``missing``, ``ready``)."""
	from webshop.webshop.doctype.webshop_settings.webshop_settings import get_shopping_cart_settings
	from webshop.webshop.multi_site import site_url
	from webshop.webshop.seo.feeds import google
	from webshop.webshop.seo.site import shop_name

	with google.serving(site):
		settings = get_shopping_cart_settings()
		report = frappe._dict(
			site=site.key,
			language=language,
			url=site_url("/" + FEED_ROUTE.format(language=language)),
			sent=0,
			left_out={},
			refusal=google.site_refusal(settings),
			missing=[],
			ready=False,
		)
		if report.refusal:
			return None, report
		excluded = google.excluded_groups()
		mapping = google.attribute_map(settings)
		names = google.feed_candidates()
		translated = localized.translated_documents("Website Item", names).get(language, set())
		texts = translations_of([n for n in names if n in translated], language)
		entries = []
		for name in names:
			doc = frappe.get_cached_doc("Website Item", name)
			try:
				entry, reason = google.item_entry(doc, settings, excluded, mapping)
			except Exception:
				frappe.log_error(
					f"Google feed ({language}): item {doc.item_code} failed", frappe.get_traceback()
				)
				entry, reason = None, "error"
			if not entry:
				report.left_out[reason] = report.left_out.get(reason, 0) + 1
			elif name not in translated:
				# the French feed sends it, the German one must not send French text
				report.left_out["not_translated"] = report.left_out.get("not_translated", 0) + 1
			else:
				entries.append(localize_entry(entry, doc, language, texts))
		report.sent = len(entries)
		report.missing = readiness(language, report.sent, report.left_out.get("not_translated", 0))
		report.ready = not report.missing
		title = shop_name() or site_url("/")
		return google.render_xml(entries, title, in_language(site_url("/"), language)), report


def feed_path(site_key: str, language: str) -> str:
	return frappe.get_site_path("private", "feeds", f"google-{site_key}-{language}.xml")


def write_language_feed(site, language: str) -> frappe._dict:
	xml, report = build_language_feed(site, language)
	path = feed_path(site.key, language)
	if xml is None:
		if os.path.exists(path):
			os.remove(path)
		return report
	os.makedirs(os.path.dirname(path), exist_ok=True)
	partial = f"{path}.partial"
	# the path is feed_path(): private/feeds/google-<site_key>-<language>.xml, nothing in it is caller-given
	with open(
		partial, "w", encoding="utf-8"
	) as handle:  # nosemgrep: frappe-semgrep-rules.rules.security.frappe-security-file-traversal
		handle.write(xml)
	os.replace(partial, path)
	return report


def site_languages_of(site) -> list[str]:
	"""The additional languages a site enabled, read as that site's visitor."""
	from webshop.webshop.seo.feeds import google

	with google.serving(site):
		return list(localized.site_languages())


def write_language_feeds(site) -> list:
	"""One feed per additional language of ``site``; a language that failed costs its feed, not the others."""
	reports = []
	for language in site_languages_of(site):
		try:
			reports.append(write_language_feed(site, language))
		except Exception:
			frappe.log_error(f"Google feed: site {site.key} in {language} failed", frappe.get_traceback())
	return reports


def served_file(site_key: str, language: str):
	"""The path of the feed of ``language`` the site being served may hand out, or None. The language is checked."""
	if language not in localized.site_languages():
		return None
	path = feed_path(site_key, language)
	return path if os.path.exists(path) else None


def describe(reports, token: str) -> list[str]:
	"""The lines the Webshop Settings report adds for the language feeds."""
	lines = []
	for report in reports:
		lines.append(f"{report.url}?token={token}")
		if report.refusal:
			lines.append("  " + _("No feed: {0}").format(report.refusal))
			continue
		lines.append("  " + _("{0} products sent").format(report.sent))
		for reason, count in sorted(report.left_out.items(), key=lambda pair: -pair[1]):
			lines.append("  " + _("{0} left out: {1}").format(count, _reason(reason)))
		if report.ready:
			lines.append("  " + _("Ready for Merchant Center"))
		else:
			lines.extend("  " + _("Not ready: {0}").format(text) for text in report.missing)
	return lines


def _reason(reason: str) -> str:
	if reason == "not_translated":
		return _("the product is not translated into this language yet")
	from webshop.webshop.seo.feeds import google

	return google.reason_label(reason)
