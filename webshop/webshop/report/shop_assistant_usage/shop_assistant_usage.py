# //// Neoffice — added file (shop assistant, no upstream equivalent).
"""What the assistant did, day by day: conversations, messages, tokens, cost.

This is the report the service is billed from, so it counts what the model
was actually sent and returned (the usage the endpoint reports), not what the
visitor saw.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, nowdate


def execute(filters=None):
	filters = frappe._dict(filters or {})
	from_date = getdate(filters.get("from_date") or add_days(nowdate(), -30))
	to_date = getdate(filters.get("to_date") or nowdate())
	price = flt(frappe.db.get_single_value("Webshop Settings", "assistant_token_price"))
	group = filters.get("group_by") or "Day"

	if group == "Customer":
		key, key_label, key_type = "coalesce(c.customer, c.user, 'Visiteur')", _("Customer"), "Data"
	else:
		key, key_label, key_type = "date(c.last_message_on)", _("Date"), "Date"

	rows = frappe.db.sql(
		f"""select {key} as grouping,
			count(distinct c.name) as conversations,
			coalesce(sum(c.message_count), 0) as messages,
			coalesce(sum(c.prompt_tokens), 0) as prompt_tokens,
			coalesce(sum(c.completion_tokens), 0) as completion_tokens,
			sum(case when c.status = 'Escalated' then 1 else 0 end) as escalated
		from `tabShop Assistant Conversation` c
		where date(c.last_message_on) between %(from_date)s and %(to_date)s
		group by {key}
		order by {key}""",
		{"from_date": from_date, "to_date": to_date},
		as_dict=True,
	)
	for row in rows:
		row.tokens = cint(row.prompt_tokens) + cint(row.completion_tokens)
		row.estimated_cost = flt(row.tokens) / 1000.0 * price if price else 0

	columns = [
		{"fieldname": "grouping", "label": key_label, "fieldtype": key_type, "width": 160},
		{"fieldname": "conversations", "label": _("Conversations"), "fieldtype": "Int", "width": 120},
		{"fieldname": "messages", "label": _("Messages"), "fieldtype": "Int", "width": 100},
		{"fieldname": "prompt_tokens", "label": _("Prompt Tokens"), "fieldtype": "Int", "width": 120},
		{"fieldname": "completion_tokens", "label": _("Completion Tokens"), "fieldtype": "Int", "width": 130},
		{"fieldname": "tokens", "label": _("Tokens used"), "fieldtype": "Int", "width": 110},
		{"fieldname": "escalated", "label": _("Handed over to the team"), "fieldtype": "Int", "width": 130},
		{"fieldname": "estimated_cost", "label": _("Estimated cost"), "fieldtype": "Currency", "width": 120},
	]
	return columns, rows
