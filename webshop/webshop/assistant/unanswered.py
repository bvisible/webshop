# //// Neoffice — added file (shop assistant, no upstream equivalent).
"""The questions the shop assistant left without an answer, and the weekly mail that sends them to the team (lot D of the 2026-10-30 audit).

A question went unanswered when the assistant said it did not know (the `unanswered` signal of the log), when the visitor was
handed to the team (`escalated`), when the visitor said the answer did not help, or reported it. A refusal of another subject
is not one: nobody expects a shop's catalogue to hold a recipe.
"""

import html
import re

import frappe
from frappe import _
from frappe.utils import add_days, cint, get_url, nowdate

WEEKLY_ROWS = 20


def _why(row):
	"""Why an answer counts as unanswered, in the order a person reads them."""
	signals = row.signals or ""
	found = []
	if ",unanswered," in signals:
		found.append(_("No answer"))
	if ",escalated," in signals:
		found.append(_("Handed to the team"))
	if row.feedback == "Not useful":
		found.append(_("Marked not useful"))
	if cint(row.reported):
		found.append(_("Reported"))
	return found


def find(from_date, to_date, limit=1000):
	"""`[{question, count, why, last_asked, conversation}]`: each question once, the most asked first.

	The question of an answer is the visitor's message that came just before it in the thread. Two spellings of the same
	question (case, punctuation) are one; the first one written is the one shown.
	"""
	rows = frappe.db.sql(
		"""select m.parent as conversation, m.sent_on, m.signals, m.feedback, m.reported,
			(select u.content from `tabShop Assistant Message` u
				where u.parent = m.parent and u.parenttype = 'Shop Assistant Conversation'
					and u.role = 'user' and u.idx < m.idx
				order by u.idx desc limit 1) as question
		from `tabShop Assistant Message` m
		where m.parenttype = 'Shop Assistant Conversation' and m.role = 'assistant'
			and (m.tool_calls is null or m.tool_calls = '')
			and date(m.sent_on) between %(first)s and %(last)s
			and (m.signals like '%%,unanswered,%%' or m.signals like '%%,escalated,%%'
				or m.feedback = 'Not useful' or m.reported = 1)
		order by m.sent_on asc
		limit %(limit)s""",
		{"first": from_date, "last": to_date, "limit": cint(limit)},
		as_dict=True,
	)
	grouped = {}
	for row in rows:
		if not row.question:
			continue
		key = re.sub(r"\W+", " ", row.question.lower()).strip()
		entry = grouped.setdefault(
			key, {"question": row.question.strip()[:300], "count": 0, "why": [], "last_asked": row.sent_on, "conversation": row.conversation}
		)
		entry["count"] += 1
		entry["last_asked"], entry["conversation"] = row.sent_on, row.conversation
		for reason in _why(row):
			if reason not in entry["why"]:
				entry["why"].append(reason)
	found = sorted(grouped.values(), key=lambda entry: entry["last_asked"], reverse=True)
	found.sort(key=lambda entry: -entry["count"])  # the most asked first, the newest first among equals
	for entry in found:
		entry["why"] = ", ".join(entry["why"])
	return found


def send_weekly_digest(settings=None, send=None):
	"""Mail the week's unanswered questions to the team; returns how many it listed, None when it sent nothing.

	Off until the merchant switches it on: a shop that migrated must not start mailing. It goes to the support address
	the escalations already use, and not at all when the week had none or no address is known.
	"""
	from webshop.webshop.assistant import escalation

	settings = settings or frappe.get_cached_doc("Webshop Settings")
	if not cint(settings.get("assistant_weekly_digest")):
		return None
	recipient = escalation._support_email(settings)
	if not recipient:
		return None
	rows = find(add_days(nowdate(), -7), nowdate())[:WEEKLY_ROWS]
	if not rows:
		return None
	lines = "".join(
		f"<tr><td>{html.escape(row['question'])}</td><td style='text-align:right'>{row['count']}</td>"
		f"<td>{html.escape(row['why'])}</td></tr>"
		for row in rows
	)
	link = get_url("/app/query-report/Shop Assistant Unanswered Questions")
	message = (
		f"<p>{html.escape(_('Questions visitors asked the assistant this week that it could not answer. They show what the shop’s knowledge or catalogue lacks.'))}</p>"
		f"<table cellpadding='6' border='0'><tr><th align='left'>{html.escape(_('Question'))}</th>"
		f"<th>{html.escape(_('Times asked'))}</th><th align='left'>{html.escape(_('Why'))}</th></tr>{lines}</table>"
		f"<p><a href='{html.escape(link)}'>{html.escape(_('Open the report'))}</a></p>"
	)
	(send or escalation._send_quietly)(
		recipients=[recipient],
		subject=_("Questions your shop assistant could not answer this week"),
		message=message,
	)
	return len(rows)


def weekly_digest():
	"""Weekly job. A job starts in English whatever the site speaks: the mail is written in the site's language."""
	language = frappe.local.lang
	frappe.local.lang = frappe.db.get_single_value("System Settings", "language") or "en"
	try:
		return send_weekly_digest()
	finally:
		frappe.local.lang = language
