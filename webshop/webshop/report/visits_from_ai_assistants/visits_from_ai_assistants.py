# //// Neoffice — added file (no upstream equivalent): the visits that came from an AI assistant
# //// (webshop/webshop/seo/ai_referrals.py, neoffice-maintenance#691 lot 4).
"""How many visits each assistant sent, and to which pages: the measure of the GEO work. It reads
Web Page View, which Frappe fills only once view tracking is on in Website Settings: the report
says so rather than showing an empty table as if nobody came."""

import frappe
from frappe import _
from frappe.utils import add_days, getdate, nowdate

from webshop.webshop.seo.ai_referrals import assistant_of, like_patterns

GROUPINGS = ("Assistant", "Page", "Day")


def execute(filters=None):
	filters = frappe._dict(filters or {})
	from_date = getdate(filters.get("from_date") or add_days(nowdate(), -30))
	to_date = getdate(filters.get("to_date") or nowdate())
	group_by = filters.get("group_by") if filters.get("group_by") in GROUPINGS else "Assistant"
	message = None
	if not frappe.db.get_single_value("Website Settings", "enable_view_tracking"):
		message = _("View tracking is off in Website Settings: no visit is recorded, from an assistant or from anyone else.")

	views = frappe.get_all(
		"Web Page View",
		filters={"creation": ["between", [from_date, to_date]]},
		or_filters=[["referrer", "like", pattern] for pattern in like_patterns()] + [["source", "is", "set"]],
		fields=["creation", "path", "referrer", "source", "visitor_id"],
		limit_page_length=0,
	)
	counted = {}
	for view in views:
		assistant = assistant_of(view.referrer, view.source)
		if not assistant:
			continue
		if group_by == "Page":
			key = (view.path or "/", assistant)
		elif group_by == "Day":
			key = (getdate(view.creation), assistant)
		else:
			key = (assistant,)
		entry = counted.setdefault(key, frappe._dict(visits=0, visitors=set()))
		entry.visits += 1
		if view.visitor_id:
			entry.visitors.add(view.visitor_id)
	return columns(group_by), rows(group_by, counted), message


def columns(group_by):
	first = {
		"Page": [{"fieldname": "path", "label": _("Page"), "fieldtype": "Data", "width": 320}],
		"Day": [{"fieldname": "date", "label": _("Day"), "fieldtype": "Date", "width": 110}],
	}.get(group_by, [])
	return [
		*first,
		{"fieldname": "assistant", "label": _("Assistant"), "fieldtype": "Data", "width": 140},
		{"fieldname": "visits", "label": _("Visits"), "fieldtype": "Int", "width": 100},
		{"fieldname": "visitors", "label": _("Visitors"), "fieldtype": "Int", "width": 100},
	]


def rows(group_by, counted):
	data = []
	for key, entry in counted.items():
		row = {"assistant": key[-1], "visits": entry.visits, "visitors": len(entry.visitors)}
		if group_by == "Page":
			row["path"] = key[0]
		elif group_by == "Day":
			row["date"] = key[0]
		data.append(row)
	if group_by == "Day":
		return sorted(data, key=lambda row: (row["date"], row["assistant"]))
	return sorted(data, key=lambda row: (-row["visits"], row.get("path", ""), row["assistant"]))
