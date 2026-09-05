# //// Neoffice — added file (shop assistant, no upstream equivalent).
"""What the bubble calls. Three public endpoints, all reading the identity from
the session and nothing else:

- `get_config`: is the assistant on, how it is called, the greeting, the last
  turns of this visitor's conversation, the labels of the widget;
- `send`: one message in, one reply out, within the visitor's limits;
- `reset`: close the conversation, start afresh next time.
"""

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
# //// Neoffice — the answering machine's "leave a message" form validates a guest's email before escalating (814347b504 "feat(assistant): un répondeur quand le modèle tombe ou la limite est atteinte")
from frappe.utils import add_days, cint, now_datetime, validate_email_address

from webshop.webshop.assistant import engine
from webshop.webshop.doctype.shop_assistant_conversation.shop_assistant_conversation import (
	ShopAssistantConversation,
)

MAX_MESSAGE_CHARS = 1000
RESUME_WITHIN_DAYS = 30
HISTORY_SHOWN = 12
DEFAULT_GUEST_DAILY = 30
DEFAULT_USER_DAILY = 200
# //// Neoffice — the answering machine: after the model fails, nobody is made to wait
# //// on the dead endpoint for OUTAGE_SECONDS; the notice is served at once from this flag.
OUTAGE_KEY = "webshop_assistant_outage"
OUTAGE_SECONDS = 120


def settings():
	return frappe.get_cached_doc("Webshop Settings")


def enabled(s=None):
	return bool(cint((s or settings()).get("enable_assistant")))


def signed_in(ctx):
	return bool(ctx.user and ctx.user != "Guest")


# //// Neoffice — the answering machine. When the model is unreachable or the visitor's
# //// quota is spent, the bubble does not apologise and stop: it says why, gives the
# //// shop's opening status and takes a message for the team — no model involved.
def _outage_key():
	return frappe.cache().make_key(OUTAGE_KEY)


def in_outage():
	"""True for OUTAGE_SECONDS after the model failed: nobody waits 25 s on a dead endpoint.

	Straight to Redis, not through get_value/set_value: the request-local cache keeps a
	miss as None, and a set with an expiry does not refresh it, so the flag armed a
	moment ago would read as "no outage" for the rest of the request.
	"""
	return bool(frappe.cache().get(_outage_key()))


def mark_outage():
	frappe.cache().setex(_outage_key(), OUTAGE_SECONDS, str(now_datetime()))


def clear_outage():
	frappe.cache().delete(_outage_key())


def store_status_line(s):
	"""What an answering machine says about the shop: open until when, or opens again when."""
	from webshop.webshop.utils.store_hours import opening_hours

	try:
		data = opening_hours(settings=s)
	except Exception:
		frappe.log_error("Shop assistant: store status failed", frappe.get_traceback())
		return ""
	if not data.configured:
		return ""
	line = " · ".join(p for p in (data.headline, data.detail) if p) + "."
	if data.is_open and data.phone:
		line += " " + _("Vous pouvez aussi nous appeler au {0}.").format(data.phone)
	return line


def unavailable(ctx, reason):
	"""The notice the visitor reads instead of an answer, and what the widget does with it.

	`reason` is "outage" (the model failed), "limit" (the visitor's messages for today)
	or "cap" (the shop's tokens for the month). The words are the merchant's when set.
	"""
	s = ctx.settings
	if reason == "limit":
		lead = labels()["limit"]
	else:
		lead = (s.get("assistant_offline_message") or "").strip() or _("L'assistant n'est pas disponible pour le moment.")
	invite = _("Laissez-nous votre message ci-dessous : l'équipe vous répond par email.")
	return {
		"reply": " ".join(p for p in (lead, store_status_line(s), invite) if p),
		"unavailable": reason,
		"leave_message": True,
		"email_required": not signed_in(ctx),
	}


def context(page_route=None, conversation=None):
	"""Who is asking, resolved on the server. The browser only says which page."""
	from webshop.webshop.shopping_cart.cart import get_party
	from webshop.webshop.shopping_cart.guest_cart import get_guest_session_id

	user = frappe.session.user
	customer = None
	guest_session = None
	if user and user != "Guest":
		try:
			party = get_party(user)
			if party and party.doctype == "Customer":
				customer = party.name
		except Exception:
			frappe.log_error("Shop assistant: party resolution failed", frappe.get_traceback())
	else:
		try:
			guest_session = get_guest_session_id()
		except Exception:
			guest_session = None
	return frappe._dict(
		user=user,
		customer=customer,
		guest_session=guest_session,
		settings=settings(),
		page_route=(page_route or "").strip()[:140],
		conversation=conversation,
		summary=None,
	)


def find_conversation(ctx, create=False):
	"""The visitor's open conversation, resumed for RESUME_WITHIN_DAYS."""
	since = add_days(now_datetime(), -RESUME_WITHIN_DAYS)
	filters = {"status": ["in", ("Open", "Escalated")], "last_message_on": [">=", since]}
	if ctx.user and ctx.user != "Guest":
		filters["user"] = ctx.user
	elif ctx.guest_session:
		filters["guest_session"] = ctx.guest_session
	else:
		return None
	name = frappe.db.get_value("Shop Assistant Conversation", filters, "name", order_by="last_message_on desc")
	if not name and ctx.user and ctx.user != "Guest" and ctx.guest_session is None:
		name = _adopt_guest_conversation(ctx, since)
	if name:
		return frappe.get_doc("Shop Assistant Conversation", name)
	if not create:
		return None
	doc = frappe.get_doc(
		{
			"doctype": "Shop Assistant Conversation",
			"user": ctx.user if ctx.user != "Guest" else None,
			"customer": ctx.customer,
			"guest_session": ctx.guest_session,
			"page_route": ctx.page_route,
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc


def _adopt_guest_conversation(ctx, since):
	"""A visitor who talked as a guest and then signed in keeps the thread."""
	from webshop.webshop.shopping_cart.guest_cart import get_guest_session_id

	try:
		guest = get_guest_session_id()
	except Exception:
		return None
	if not guest:
		return None
	name = frappe.db.get_value(
		"Shop Assistant Conversation",
		{"guest_session": guest, "user": ["in", ("", None)], "status": "Open", "last_message_on": [">=", since]},
		"name",
	)
	if name:
		frappe.db.set_value(
			"Shop Assistant Conversation", name, {"user": ctx.user, "customer": ctx.customer}, update_modified=False
		)
	return name


def greeting(ctx):
	s = ctx.settings
	name = (s.get("assistant_name") or "Nora").strip()
	welcome = (s.get("assistant_welcome") or "").strip()
	if ctx.user and ctx.user != "Guest":
		first_name = frappe.db.get_value("User", ctx.user, "first_name") or ""
		hello = _("Bonjour {0} !").format(first_name) if first_name else _("Bonjour !")
		return f"{hello} " + (welcome or _("Je suis {0}, l'assistant·e de la boutique. Une commande à suivre, un produit à trouver ?").format(name))
	return welcome or _("Bonjour ! Je suis {0}, l'assistant·e de la boutique. Un produit, nos horaires, une commande ? Je suis là.").format(name)


def labels():
	return {
		"title": _("Assistant"),
		"placeholder": _("Écrivez votre message…"),
		"send": _("Envoyer"),
		"typing": _("écrit…"),
		"talk_to_team": _("Parler à l'équipe"),
		"new_conversation": _("Nouvelle conversation"),
		"resume": _("On reprend où on en était ?"),
		"close": _("Fermer"),
		"open": _("Ouvrir l'assistant"),
		"error": _("Le message n'est pas parti. Réessayez dans un instant."),
		"limit": _("Vous avez atteint la limite de messages pour aujourd'hui."),
		# //// Neoffice — labels for the answering machine's "leave a message" form (814347b504 "feat(assistant): un répondeur quand le modèle tombe ou la limite est atteinte")
		"leave_title": _("Laisser un message à l'équipe"),
		"leave_placeholder": _("Votre message pour l'équipe…"),
		"leave_email": _("Votre adresse email"),
		"leave_send": _("Envoyer à l'équipe"),
		"leave_cancel": _("Annuler"),
		"leave_error": _("Le message n'a pas pu partir. Réessayez, ou écrivez-nous directement."),
		"suggestions": [
			_("Vos horaires ?"),
			_("Où en est ma commande ?"),
			_("Je cherche un produit"),
			_("Parler à quelqu'un"),
		],
	}


@frappe.whitelist(allow_guest=True)
def get_config(page_route=None):
	s = settings()
	if not enabled(s):
		return {"enabled": False}
	ctx = context(page_route)
	conversation = find_conversation(ctx)
	history = []
	if conversation:
		visible = [m for m in conversation.messages if m.role in ("user", "assistant") and m.content and not m.tool_calls]
		history = [{"role": m.role, "content": m.content, "sent_on": str(m.sent_on)} for m in visible[-HISTORY_SHOWN:]]
	return {
		"enabled": True,
		"name": (s.get("assistant_name") or "Nora").strip(),
		"position": s.get("assistant_position") or "Bottom right",
		"color": s.get("assistant_color") or "",
		"greeting": greeting(ctx),
		"signed_in": bool(ctx.user and ctx.user != "Guest"),
		"history": history,
		"labels": labels(),
		# //// Neoffice — the answering machine (814347b504 "feat(assistant): un répondeur quand le modèle tombe ou la limite est atteinte")
		# the answering machine speaks from the first screen when it has to
		"notice": unavailable(ctx, reason) if (reason := unavailable_reason(ctx, conversation)) else None,
	}


def _daily_limit_reached(conversation, ctx):
	s = ctx.settings
	if ctx.user and ctx.user != "Guest":
		limit = cint(s.get("assistant_user_daily_limit")) or DEFAULT_USER_DAILY
	else:
		limit = cint(s.get("assistant_guest_daily_limit")) or DEFAULT_GUEST_DAILY
	today = now_datetime().date()
	sent_today = len([m for m in conversation.messages if m.role == "user" and m.sent_on and m.sent_on.date() == today])
	return sent_today >= limit


def _monthly_cap_reached(ctx):
	cap = cint(ctx.settings.get("assistant_monthly_token_cap"))
	return bool(cap) and engine.monthly_tokens() >= cap


# //// Neoffice — the answering machine: what a "no answer" actually means (outage, daily limit, monthly cap), and what to write on the conversation for the outage case (814347b504 "feat(assistant): un répondeur quand le modèle tombe ou la limite est atteinte")
def unavailable_reason(ctx, conversation=None):
	if in_outage():
		return "outage"
	if conversation and _daily_limit_reached(conversation, ctx):
		return "limit"
	if _monthly_cap_reached(ctx):
		return "cap"
	return None


def _answering_machine(conversation, ctx, reason, user_text=None):
	"""The notice, written on the conversation when the visitor's words were (outage only)."""
	out = unavailable(ctx, reason)
	if reason == "outage":
		if user_text:
			conversation.add_message("user", user_text)
		conversation.add_message("assistant", out["reply"])
		conversation.flags.ignore_permissions = True
		conversation.save()
	out["conversation"] = conversation.name
	out["limited"] = reason in ("limit", "cap")
	return out


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=20, seconds=600)
def send(message, page_route=None):
	s = settings()
	if not enabled(s):
		frappe.throw(_("The assistant is not enabled."), frappe.PermissionError)
	text = (message or "").strip()
	if not text:
		frappe.throw(_("Le message est vide."))
	text = text[:MAX_MESSAGE_CHARS]
	ctx = context(page_route)
	conversation = find_conversation(ctx, create=True)
	if not conversation:
		frappe.throw(_("Impossible d'ouvrir une conversation pour cette session."))
	ctx.conversation = conversation
	if ctx.page_route:
		conversation.page_route = ctx.page_route
	# //// Neoffice — was: the limit label alone, the cap sentence alone, and on a model
	# //// failure the canned FALLBACK; each left the visitor with nothing to do. Now every
	# //// one of them is the answering machine, and a failure arms the outage flag so the
	# //// next visitors get the notice at once instead of a 25 s wait.
	reason = unavailable_reason(ctx, conversation)
	if reason:
		return _answering_machine(conversation, ctx, reason, user_text=text)
	try:
		out = engine.respond(conversation, text, ctx)
	except Exception:
		frappe.log_error("Shop assistant: reply failed", frappe.get_traceback())
		# //// Neoffice — the answering machine: arm the outage flag so the next visitors get the notice at once, and answer this one the same way instead of a bare error (814347b504 "feat(assistant): un répondeur quand le modèle tombe ou la limite est atteinte")
		mark_outage()
		# respond() already wrote the visitor's words on the conversation
		result = _answering_machine(conversation, ctx, "outage")
		result["failed"] = True
		return result
	return {"reply": out.reply, "conversation": out.conversation, "escalated": conversation.status == "Escalated"}


# //// Neoffice ▼▼▼ — the answering machine's tape: the "leave a message" endpoint and the escalation it triggers, reached with no model involved when the model is down or a limit is hit (814347b504 "feat(assistant): un répondeur quand le modèle tombe ou la limite est atteinte")
@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=5, seconds=600)
def leave_message(message, email=None, page_route=None):
	"""The answering machine's tape: the visitor's words go to the team as they are."""
	s = settings()
	if not enabled(s):
		frappe.throw(_("The assistant is not enabled."), frappe.PermissionError)
	text = (message or "").strip()[:MAX_MESSAGE_CHARS]
	if not text:
		frappe.throw(_("Le message est vide."))
	return leave(context(page_route), text, email)


def leave(ctx, text, email=None):
	"""Hand `text` to the team through the escalation path, without the model.

	A signed-in visitor is written to at the session's address, whatever the form
	said; a guest has to give a valid one. The conversation turns Escalated, the
	team is told (Raven, support email), the visitor gets a confirmation.
	"""
	from webshop.webshop.assistant import escalation

	if signed_in(ctx):
		email = frappe.db.get_value("User", ctx.user, "email") or ctx.user
	else:
		email = validate_email_address((email or "").strip()) if email else None
		if not email:
			frappe.throw(_("Indiquez une adresse email valide pour que l'équipe puisse vous répondre."))
	conversation = ctx.conversation or find_conversation(ctx, create=True)
	if not conversation:
		frappe.throw(_("Impossible d'ouvrir une conversation pour cette session."))
	ctx.conversation = conversation
	# the form is prefilled with the words the model could not answer: no second copy
	last_user = next((m for m in reversed(conversation.messages) if m.role == "user"), None)
	if not last_user or (last_user.content or "").strip() != text:
		conversation.add_message("user", text)
	out = escalation.contact_team(ctx, summary=text, email=email)
	reply = _("C'est transmis. L'équipe vous répond à {0}.").format(email)
	status = store_status_line(ctx.settings)
	if status:
		reply = f"{reply} {status}"
	conversation.add_message("assistant", reply)
	conversation.flags.ignore_permissions = True
	conversation.save()
	return {"reply": reply, "conversation": conversation.name, "escalated": True, "via": out.get("via")}
# //// Neoffice ▲▲▲


@frappe.whitelist(allow_guest=True, methods=["POST"])
def reset():
	ctx = context()
	conversation = find_conversation(ctx)
	if conversation:
		frappe.db.set_value("Shop Assistant Conversation", conversation.name, "status", "Closed")
	return {"closed": bool(conversation)}


def get_usage_stats():
	"""The figures of the Assistant tab: this month, this shop."""
	month_start = now_datetime().date().replace(day=1)
	row = frappe.db.sql(
		"""select count(*) as conversations,
			coalesce(sum(message_count), 0) as messages,
			coalesce(sum(prompt_tokens), 0) as prompt_tokens,
			coalesce(sum(completion_tokens), 0) as completion_tokens,
			sum(case when status = 'Escalated' then 1 else 0 end) as escalated
		from `tabShop Assistant Conversation`
		where last_message_on >= %s""",
		(month_start,),
		as_dict=True,
	)[0]
	price = frappe.utils.flt(settings().get("assistant_token_price"))
	tokens = cint(row.prompt_tokens) + cint(row.completion_tokens)
	return {
		"conversations": cint(row.conversations),
		"messages": cint(row.messages),
		"prompt_tokens": cint(row.prompt_tokens),
		"completion_tokens": cint(row.completion_tokens),
		"tokens": tokens,
		"escalated": cint(row.escalated),
		"estimated_cost": round(tokens / 1000.0 * price, 2) if price else None,
		"monthly_cap": cint(settings().get("assistant_monthly_token_cap")) or None,
	}


@frappe.whitelist()
def usage_stats():
	frappe.only_for(("System Manager", "Website Manager"))
	return get_usage_stats()


# //// Neoffice — nightly purge job feeding the usage report and retention policy (84412d0bec "feat(assistant): rapport d'usage, purge de nuit, conversations sur la fiche client")
def purge_old_conversations():
	"""Nightly: forget conversations older than the retention, except the ones
	that were handed to the team — those are the trace the team may need."""
	days = cint(settings().get("assistant_retention_days")) or 90
	cutoff = add_days(now_datetime(), -days)
	names = frappe.get_all(
		"Shop Assistant Conversation",
		filters={"last_message_on": ["<", cutoff], "status": ["!=", "Escalated"]},
		pluck="name",
		limit=500,
	)
	for name in names:
		frappe.delete_doc("Shop Assistant Conversation", name, force=True, ignore_permissions=True)
	if names:
		frappe.db.commit()
	return len(names)
