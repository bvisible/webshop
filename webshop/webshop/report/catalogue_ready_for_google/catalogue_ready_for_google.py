# //// Neoffice — added file (no upstream equivalent): which products Google Shopping gets, and what
# //// would make them better (neoffice-maintenance#691, lot 6).
"""Every published product of a site as the Google feed sees it: sent, or left out and why, and
what would make a sent one's listing better. It runs the feed's own rules (seo/feeds/google.py,
item_entry) as a visitor of the site would get them, which only a background job may do: the
report is a prepared one, and refuses to run inside a web request."""

import frappe
from frappe import _
from frappe.website.doctype.website_slideshow.website_slideshow import get_slideshow

from webshop.webshop.seo.facts import gallery_images
from webshop.webshop.seo.feeds import google

SHOW = ("All", "Sent", "Left out", "Suggestions")


@frappe.whitelist()
def sites():
	"""The sites a feed is written for, for the report's filter."""
	frappe.only_for(("System Manager", "Website Manager"))
	return [
		{"key": site.key, "label": (site.profile or {}).get("name") or _("This site")}
		for site in google.feed_sites()
	]


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if getattr(frappe.local, "session_obj", None):
		frappe.throw(_("This report runs in the background: open it from its page."))
	language = frappe.local.lang
	# a job starts in English: the labels are for the person who asked
	frappe.set_user_lang(frappe.session.user)
	try:
		return report(filters)
	finally:
		frappe.local.lang = language


def report(filters):
	from webshop.webshop.doctype.webshop_settings.webshop_settings import get_shopping_cart_settings

	sites_ = google.feed_sites()
	site = next((s for s in sites_ if s.key == filters.get("site")), sites_[0])
	show = filters.get("show") if filters.get("show") in SHOW else "All"
	rows, sent, left_out, suggested = [], 0, 0, 0
	with google.serving(site):
		settings = get_shopping_cart_settings()
		refusal = google.site_refusal(settings)
		if refusal:
			return columns(), [], _("This site has no feed: {0}.").format(refusal)
		excluded = google.excluded_groups()
		mapping = google.attribute_map(settings)
		candidates = google.feed_candidates()
		if filters.get("website_item"):
			candidates = [name for name in candidates if name == filters.website_item]
		for name in candidates:
			doc = frappe.get_cached_doc("Website Item", name)
			try:
				entry, reason = google.item_entry(doc, settings, excluded, mapping)
			except Exception:
				frappe.log_error(f"Catalogue Ready for Google: {doc.item_code}", frappe.get_traceback())
				entry, reason = None, "error"
			warnings = google.entry_warnings(entry, doc, first_picture(doc)) if entry else []
			sent += bool(entry)
			left_out += not entry
			suggested += bool(warnings)
			if (
				(show == "Sent" and not entry)
				or (show == "Left out" and entry)
				or (show == "Suggestions" and not warnings)
			):
				continue
			rows.append(row(doc, entry, reason, warnings))
	summary = [
		{"value": sent, "label": _("Sent to Google"), "indicator": "Green", "datatype": "Int"},
		{"value": left_out, "label": _("Left out"), "indicator": "Red", "datatype": "Int"},
		{"value": suggested, "label": _("With suggestions"), "indicator": "Orange", "datatype": "Int"},
	]
	return columns(), rows, None, None, summary


def first_picture(doc):
	"""The picture the feed sends first: the gallery's (seo/facts.py gallery_images)."""
	context = frappe._dict(get_slideshow(doc)) if doc.get("slideshow") else frappe._dict()
	images = gallery_images(doc, context)
	return images[0] if images else None


def row(doc, entry, reason, warnings):
	entry = entry or {}
	return {
		"website_item": doc.name,
		"item_code": doc.item_code,
		"item_name": doc.web_item_name,
		"status": _("Sent to Google") if entry else _("Left out"),
		"reason": google.reason_label(reason) if reason else "",
		"suggestions": "; ".join(google.warning_label(code) for code in warnings),
		"price": entry.get("sale_price") or entry.get("price") or "",
		"availability": entry.get("availability") or "",
		"gtin": entry.get("gtin") or "",
		"pictures": (1 + len(entry.get("additional_image_link") or [])) if entry else 0,
	}


def columns():
	return [
		{"fieldname": "website_item", "label": _("Website Item"), "fieldtype": "Link", "options": "Website Item", "width": 140},
		{"fieldname": "item_code", "label": _("Item Code"), "fieldtype": "Data", "width": 130},
		{"fieldname": "item_name", "label": _("Name"), "fieldtype": "Data", "width": 220},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 120},
		{"fieldname": "reason", "label": _("Why left out"), "fieldtype": "Data", "width": 220},
		{"fieldname": "suggestions", "label": _("To show it at its best"), "fieldtype": "Data", "width": 360},
		{"fieldname": "price", "label": _("Price sent"), "fieldtype": "Data", "width": 110},
		{"fieldname": "availability", "label": _("Availability sent"), "fieldtype": "Data", "width": 120},
		{"fieldname": "gtin", "label": _("GTIN"), "fieldtype": "Data", "width": 130},
		{"fieldname": "pictures", "label": _("Pictures"), "fieldtype": "Int", "width": 80},
	]
