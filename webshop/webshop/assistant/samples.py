# //// Neoffice — added file (shop assistant, no upstream equivalent).
"""Anonymised samples of conversations, kept to improve the service later (lot E of the 2026-10-30 audit).

Nothing happens while `Webshop Settings.assistant_collect_samples` is off, which is its default. When it is on, once a day:

- the pairs of question and answer that a visitor who was NOT signed in rated (useful, not useful) are taken, and nothing else:
  a signed-in customer's words come with orders and addresses, a conversation handed to the team with contact details, an
  answer nobody judged tells nothing about its worth;
- both texts are cleaned (`anonymise.clean`), and a pair that still looks like it names somebody is left out;
- the sample holds the day, the language, the opinion, the prompt's version and the two texts. No link to the conversation, no
  user, no cookie, no address; the key that stops a pair being kept twice is a one-way fingerprint of the message;
- it is kept for a time of its own and forgotten after it, the conversations' ninety days notwithstanding;
- it is not used for anything until a person has read it and ticked "approved".

The legal side (the visitor told, the merchant's contract, nLPD and RGPD) is the merchant's to settle before the switch.
"""

import hashlib

import frappe
from frappe.utils import add_days, cint, getdate, nowdate

from webshop.webshop.assistant import anonymise

DEFAULT_RETENTION_DAYS = 365
BATCH = 500

# the number of pairs the last `collect` left out because they still looked like they named somebody (read by the tests)
last_skipped = 0


def _fingerprint(message):
	"""A one-way key of a message, only so that the same pair is not kept twice."""
	site = getattr(frappe.local, "site", "") or ""
	return hashlib.sha256(f"{site}:{message}".encode()).hexdigest()[:40]


def collect(settings=None):
	"""Keep the new rated pairs of visitors who were not signed in. Returns how many samples were written."""
	global last_skipped
	last_skipped = 0
	settings = settings or frappe.get_cached_doc("Webshop Settings")
	if not cint(settings.get("assistant_collect_samples")):
		return 0
	retention = cint(settings.get("assistant_sample_retention_days")) or DEFAULT_RETENTION_DAYS
	rows = frappe.db.sql(
		"""select m.name, m.content as answer, m.feedback, m.prompt_version, m.sent_on,
			(select u.content from `tabShop Assistant Message` u
				where u.parent = m.parent and u.parenttype = 'Shop Assistant Conversation' and u.role = 'user' and u.idx < m.idx
				order by u.idx desc limit 1) as question,
			(select u.language from `tabShop Assistant Message` u
				where u.parent = m.parent and u.parenttype = 'Shop Assistant Conversation' and u.role = 'user' and u.idx < m.idx
				order by u.idx desc limit 1) as language
		from `tabShop Assistant Message` m
		join `tabShop Assistant Conversation` c on c.name = m.parent
		where m.parenttype = 'Shop Assistant Conversation' and m.role = 'assistant'
			and (m.tool_calls is null or m.tool_calls = '')
			and m.feedback in ('Useful', 'Not useful')
			and (c.user is null or c.user = '') and c.guest_session is not null and c.guest_session != ''
			and c.status != 'Escalated'
		order by m.sent_on asc
		limit %(batch)s""",
		{"batch": BATCH},
		as_dict=True,
	)
	if not rows:
		return 0
	keys = {row.name: _fingerprint(row.name) for row in rows}
	known = set(frappe.get_all("Shop Assistant Sample", filters={"source_key": ["in", list(keys.values())]}, pluck="source_key"))
	written = 0
	for row in rows:
		if keys[row.name] in known or not row.question:
			continue
		names = anonymise.names_in(row.question)
		question, answer = anonymise.clean(row.question, names), anonymise.clean(row.answer, names)
		if not (anonymise.looks_clean(question) and anonymise.looks_clean(answer)):
			last_skipped += 1
			continue
		sample = frappe.get_doc(
			{
				"doctype": "Shop Assistant Sample",
				"day": getdate(row.sent_on),
				"language": row.language or "fr",
				"opinion": row.feedback,
				"prompt_version": row.prompt_version,
				"question": question,
				"answer": answer,
				"kept_until": add_days(nowdate(), retention),
				"reviewed": 0,
				"source_key": keys[row.name],
			}
		)
		sample.flags.ignore_permissions = True
		sample.insert()
		written += 1
	return written


def purge_expired():
	"""Forget the samples whose time is up. Returns how many."""
	names = frappe.get_all("Shop Assistant Sample", filters={"kept_until": ["<", nowdate()]}, pluck="name", limit_page_length=0)
	for name in names:
		frappe.delete_doc("Shop Assistant Sample", name, force=True, ignore_permissions=True)
	return len(names)


def daily():
	"""Daily job: collect (only when switched on), then forget what has expired. The scheduler commits when it ends."""
	collect()
	purge_expired()
