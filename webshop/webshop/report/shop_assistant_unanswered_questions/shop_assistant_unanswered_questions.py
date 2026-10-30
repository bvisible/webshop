# //// Neoffice — added file (shop assistant, no upstream equivalent).
"""What visitors asked and the shop assistant left without an answer: the list of what the shop's knowledge or catalogue lacks.

Read by the team only (the questions are the visitors' own words). The same list goes to the team by mail every week when the
merchant switches that on (`assistant.unanswered.send_weekly_digest`).
"""

import frappe
from frappe import _
from frappe.utils import add_days, getdate, nowdate

from webshop.webshop.assistant import unanswered


def execute(filters=None):
	filters = frappe._dict(filters or {})
	from_date = getdate(filters.get("from_date") or add_days(nowdate(), -7))
	to_date = getdate(filters.get("to_date") or nowdate())
	columns = [
		{"fieldname": "question", "label": _("Question"), "fieldtype": "Data", "width": 420},
		{"fieldname": "count", "label": _("Times asked"), "fieldtype": "Int", "width": 100},
		{"fieldname": "why", "label": _("Why"), "fieldtype": "Data", "width": 220},
		{"fieldname": "last_asked", "label": _("Last asked"), "fieldtype": "Datetime", "width": 160},
		{
			"fieldname": "conversation",
			"label": _("Conversation"),
			"fieldtype": "Link",
			"options": "Shop Assistant Conversation",
			"width": 140,
		},
	]
	return columns, unanswered.find(from_date, to_date)
