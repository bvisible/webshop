# //// Neoffice — added file (shop assistant, no upstream equivalent).
"""The agent loop: one visitor message in, one assistant reply out.

The model gets the system prompt, the conversation's memory, its last turns
and the toolbox; when it asks for tools, they run here, in the visitor's own
Frappe session, and their results go back to the model — at most
MAX_TOOL_ROUNDS times. Every turn is written on the conversation with the
tokens it cost, which is what the usage figures and the invoice come from.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint

from webshop.webshop.assistant import llm, prompt, tools

MAX_TOOL_ROUNDS = 4
HISTORY_TURNS = 20
SUMMARY_EVERY = 10
FALLBACK = "Je n'arrive pas à répondre pour le moment. Voulez-vous que je transmette votre demande à l'équipe ?"


def respond(conversation, text, ctx):
	"""Answer `text` inside `conversation`. Returns the reply and what the call cost."""
	ctx.summary = conversation.summary
	conversation.add_message("user", text)
	messages = _messages(conversation, ctx)
	schemas = tools.schemas()
	rounds = 0
	reply = ""
	spent = []
	while True:
		out = llm.complete(messages, schemas, ctx.settings)
		spent.append(out)
		if out.tool_calls and rounds < MAX_TOOL_ROUNDS:
			messages.append({"role": "assistant", "content": out.content or None, "tool_calls": out.tool_calls})
			conversation.add_message(
				"assistant",
				out.content or "",
				tool_calls=json.dumps(out.tool_calls, ensure_ascii=False),
				model=out.model,
				prompt_tokens=out.prompt_tokens,
				completion_tokens=out.completion_tokens,
				duration_ms=out.duration_ms,
			)
			for call in out.tool_calls:
				name = (call.get("function") or {}).get("name")
				args = _arguments(call)
				result = tools.run(name, args, ctx)
				payload = tools.to_json(result)
				messages.append({"role": "tool", "tool_call_id": call.get("id"), "name": name, "content": payload})
				conversation.add_message("tool", payload, tool_name=name, tool_call_id=call.get("id"))
				if name in ("contact_team", "create_support_ticket") and isinstance(result, dict) and result.get("escalated"):
					conversation.status = "Escalated"
			rounds += 1
			continue
		reply = (out.content or "").strip() or FALLBACK
		conversation.add_message(
			"assistant",
			reply,
			model=out.model,
			prompt_tokens=out.prompt_tokens,
			completion_tokens=out.completion_tokens,
			duration_ms=out.duration_ms,
		)
		break
	_maybe_summarise(conversation, ctx)
	conversation.flags.ignore_permissions = True
	conversation.save()
	return frappe._dict(
		reply=reply,
		conversation=conversation.name,
		prompt_tokens=sum(o.prompt_tokens for o in spent),
		completion_tokens=sum(o.completion_tokens for o in spent),
		rounds=rounds,
	)


def _arguments(call):
	raw = (call.get("function") or {}).get("arguments") or "{}"
	if isinstance(raw, dict):
		return raw
	try:
		parsed = json.loads(raw)
		return parsed if isinstance(parsed, dict) else {}
	except ValueError:
		return {}


def _messages(conversation, ctx):
	"""System prompt, then the last turns the visitor and the assistant exchanged.

	Tool traffic of earlier turns is left out: the memory (`summary`) carries
	what mattered, and a tool result is only meaningful next to its call.
	"""
	messages = [{"role": "system", "content": prompt.build(ctx)}]
	visible = [m for m in conversation.messages if m.role in ("user", "assistant") and m.content and not m.tool_calls]
	for m in visible[-HISTORY_TURNS:]:
		messages.append({"role": m.role, "content": m.content})
	return messages


def _maybe_summarise(conversation, ctx):
	"""Every SUMMARY_EVERY user messages, ask the model for the short memory."""
	user_turns = [m for m in conversation.messages if m.role == "user"]
	if not user_turns or len(user_turns) % SUMMARY_EVERY:
		return
	try:
		recent = [{"role": m.role, "content": m.content} for m in conversation.messages if m.role in ("user", "assistant") and m.content][-2 * SUMMARY_EVERY :]
		out = llm.complete(prompt.summary_prompt(conversation.summary, recent), None, ctx.settings, max_tokens=300)
		if out.content:
			conversation.summary = out.content.strip()
			conversation.add_message(
				"system",
				_("Résumé mis à jour."),
				model=out.model,
				prompt_tokens=out.prompt_tokens,
				completion_tokens=out.completion_tokens,
				duration_ms=out.duration_ms,
			)
	except Exception:
		frappe.log_error("Shop assistant: summary failed", frappe.get_traceback())


def monthly_tokens():
	"""Prompt + completion tokens of every conversation touched this month."""
	row = frappe.db.sql(
		"""select coalesce(sum(prompt_tokens), 0) + coalesce(sum(completion_tokens), 0)
		from `tabShop Assistant Conversation`
		where last_message_on >= date_format(now(), '%%Y-%%m-01')""",
	)
	return cint(row[0][0]) if row else 0
