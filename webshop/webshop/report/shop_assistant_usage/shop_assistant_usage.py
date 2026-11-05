# //// Neoffice — added file (shop assistant, no upstream equivalent).
"""What the assistant did, day by day: conversations, messages, tokens, cost.

This is the report the service is billed from, so it counts what the model
was actually sent and returned (the usage the endpoint reports), not what the
visitor saw.
"""

import frappe
from frappe import _
# //// Neoffice — get_match_cond: see execute.
from frappe.desk.reportview import get_match_cond
from frappe.utils import add_days, cint, flt, getdate, nowdate

from webshop.webshop.assistant import usage

# //// Neoffice — see execute.
CONVERSATION = "Shop Assistant Conversation"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	from_date = getdate(filters.get("from_date") or add_days(nowdate(), -30))
	to_date = getdate(filters.get("to_date") or nowdate())
	price = flt(frappe.db.get_single_value("Webshop Settings", "assistant_token_price"))
	group = filters.get("group_by") or "Day"

	# //// Neoffice — no alias on the table: see the query.
	if group == "Customer":
		key, key_label, key_type = "coalesce(customer, `user`, 'Visiteur')", _("Customer"), "Data"
	else:
		# //// Neoffice — no alias on the table: see the query.
		key, key_label, key_type = "date(last_message_on)", _("Date"), "Date"

	match = get_match_cond(CONVERSATION)
	# //// Neoffice — this SQL went past what limits a seller: a User Permission on Customer hid a customer from
	# //// every list and not from here. The doctype's own conditions are in the query (they name the table,
	# //// hence no alias).
	rows = frappe.db.sql(
		f"""select {key} as grouping,
			count(distinct name) as conversations,
			coalesce(sum(message_count), 0) as messages,
			coalesce(sum(prompt_tokens), 0) as prompt_tokens,
			coalesce(sum(completion_tokens), 0) as completion_tokens,
			sum(case when status = 'Escalated' then 1 else 0 end) as escalated
		from `tabShop Assistant Conversation`
		where date(last_message_on) between %(from_date)s and %(to_date)s {match}
		group by {key}
		order by {key}""",
		{"from_date": from_date, "to_date": to_date},
		as_dict=True,
	)
	# //// Neoffice — lot D of the 2026-10-30 audit: the day's counters beside its conversations, so that a day on which
	# //// nobody was answered (a flood the rate limit turned away) is a line of the report like any other
	# //// Neoffice — and the site's own counters go to who may read them: the report also opens to a seller, who
	# //// has no right on Shop Assistant Usage Day.
	counters = group != "Customer" and frappe.has_permission("Shop Assistant Usage Day", "read")
	if counters:
		by_date = {str(row.grouping): row for row in rows}
		for day, mine in usage.by_day(from_date, to_date).items():
			row = by_date.get(day)
			if not row:
				row = frappe._dict(
					grouping=getdate(day), conversations=0, messages=0, prompt_tokens=0, completion_tokens=0, escalated=0
				)
				rows.append(row)
				by_date[day] = row
			row.requests, row.refused = mine["received"], mine["refused"]
		rows.sort(key=lambda row: str(row.grouping))
	for row in rows:
		row.tokens = cint(row.prompt_tokens) + cint(row.completion_tokens)
		row.estimated_cost = flt(row.tokens) / 1000.0 * price if price else 0
		row.requests, row.refused = cint(row.get("requests")), cint(row.get("refused"))

	columns = [
		{"fieldname": "grouping", "label": key_label, "fieldtype": key_type, "width": 160},
		{"fieldname": "conversations", "label": _("Conversations"), "fieldtype": "Int", "width": 120},
	]
	# //// Neoffice — see above.
	if counters:
		columns += [
			{"fieldname": "requests", "label": _("Requests received"), "fieldtype": "Int", "width": 130},
			{"fieldname": "refused", "label": _("Turned away"), "fieldtype": "Int", "width": 110},
		]
	columns += [
		{"fieldname": "messages", "label": _("Messages"), "fieldtype": "Int", "width": 100},
		{"fieldname": "prompt_tokens", "label": _("Prompt Tokens"), "fieldtype": "Int", "width": 120},
		{"fieldname": "completion_tokens", "label": _("Completion Tokens"), "fieldtype": "Int", "width": 130},
		{"fieldname": "tokens", "label": _("Tokens used"), "fieldtype": "Int", "width": 110},
		{"fieldname": "escalated", "label": _("Handed over to the team"), "fieldtype": "Int", "width": 130},
		{"fieldname": "estimated_cost", "label": _("Estimated cost"), "fieldtype": "Currency", "width": 120},
	]
	return columns, rows
