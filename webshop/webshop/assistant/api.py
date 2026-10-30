# //// Neoffice — added file (shop assistant, no upstream equivalent).
"""What the bubble calls. Three public endpoints, all reading the identity from
the session and nothing else:

- `get_config`: is the assistant on, how it is called, the greeting, the last
  turns of this visitor's conversation, the labels of the widget;
- `send`: one message in, one reply out, within the visitor's limits;
- `reset`: close the conversation, start afresh next time.
"""

import re
import time
from contextlib import contextmanager

import frappe
from frappe import _
from frappe.utils import add_days, cint, now_datetime, nowdate

from webshop.webshop.assistant import engine, llm, usage
from webshop.webshop.doctype.shop_assistant_conversation.shop_assistant_conversation import (
	ShopAssistantConversation,
)
# //// Neoffice — Frappe's rate_limit counts the first X-Forwarded-For entry, which a caller writes on the shop vhosts that append to the header; this one counts the last (lot A of the 2026-10-30 audit)
from webshop.webshop.utils import throttle

MAX_MESSAGE_CHARS = 1000
RESUME_WITHIN_DAYS = 30
# //// Neoffice — every message loads the whole thread: a visitor who comes back for weeks starts a new one past this (lot C of the 2026-10-30 audit)
MAX_CONVERSATION_MESSAGES = 200
HISTORY_SHOWN = 12
# //// Neoffice — budgets that exist when the merchant sets none (lot A of the 2026-10-30 audit).
# //// An empty monthly cap used to mean "no cap": a flood of fresh visitors could burn the model's
# //// capacity, shared with the rest of the fleet, with nothing to stop it. Was 30 and 200 a day.
DEFAULT_GUEST_DAILY = 20
DEFAULT_USER_DAILY = 100
DEFAULT_MONTHLY_TOKEN_CAP = 3_000_000
# messages the whole site may send to the model in one clock hour, whoever sends them
SITE_HOURLY_MESSAGES = 300
# a visitor's lock outlives the slowest answer (a few model calls of 25 s) and ends by itself if the worker dies
LOCK_SECONDS = 120
# //// Neoffice — the reason `unavailable_reason` gives, as the day's counters name it (lot D of the 2026-10-30 audit)
REFUSAL_OF_REASON = {"outage": "outage", "limit": "day_limit", "cap": "month_cap", "busy": "busy"}
# //// Neoffice — answers the whole site gives at the same moment when the merchant sets none (lot C of the 2026-10-30 audit)
# each one holds one of the shop's web workers for as long as the model takes
BENCH_DEFAULT_WORKERS = 2
ANSWER_SLOTS_KEY = "webshop_assistant_inflight"
# what uuid.uuid4() writes: the only shape the shop's guest cookie takes
GUEST_SESSION_SHAPE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# letters of any language (a French shop's routes keep their accents), digits and . _ - / : no space, no line break
ROUTE_SHAPE = re.compile(r"^\w[\w\-./]{0,138}$")
# pages of the shop that are not documents
SHOP_PAGES = ("all-products", "cart", "checkout", "orders", "store-hours", "occasions", "shop-by-category", "wishlist")
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


# //// Neoffice ▼▼▼ — lot A of the 2026-10-30 audit: the site's hourly budget, and one message at a time per visitor
def _site_hour_key():
	return frappe.cache().make_key("webshop_assistant_hour:" + now_datetime().strftime("%Y%m%d%H"))


def site_hour_count():
	"""Messages the whole site has sent to the model during this clock hour."""
	# nosemgrep: frappe-semgrep-rules.rules.frappe-cache-breaks-multitenancy -- the key goes through make_key (site-prefixed), and get_value would keep a miss for the whole request
	return cint(frappe.cache().get(_site_hour_key()))


def bump_site_hour():
	cache = frappe.cache()
	key = _site_hour_key()
	# the key outlives its hour a little; written before the count so a dead process cannot leave a counter without end
	cache.set(key, 0, ex=3700, nx=True)
	cache.incr(key)


def clear_site_hour():
	frappe.cache().delete(_site_hour_key())


@contextmanager
def conversation_lock(ctx):
	"""One message at a time per visitor: yields True when the visitor may go on, False when one is already answered.

	Two parallel sends of one visitor load the same conversation and the second to save raised
	TimestampMismatchError. `send` took every exception for a dead model and armed the outage flag for the whole
	site: two requests were enough to switch the assistant off for everybody. The second request now waits its
	turn by being told so, and nothing else happens.
	"""
	who = ctx.user if signed_in(ctx) else ctx.guest_session
	if not who:
		yield True
		return
	cache = frappe.cache()
	key = cache.make_key(f"webshop_assistant_busy:{who}")
	token = frappe.generate_hash(length=16)
	if not cache.set(key, token, ex=LOCK_SECONDS, nx=True):
		yield False
		return
	try:
		yield True
	finally:
		# only the holder lets go: a lock that expired and was taken again belongs to somebody else
		if cache.get(key) in (token, token.encode()):
			cache.delete(key)


def max_simultaneous(s=None):
	"""Answers the site gives at the same moment: the merchant's figure, else what the web workers can spare.

	The shop and the ERP run on a handful of web workers (three on the development server), and an answer holds one for
	as long as the model takes. Left to itself the assistant leaves the shop more than half of them: 1 for up to 4
	workers, 2 for 5, then one more for every two.
	"""
	chosen = cint((s or settings()).get("assistant_max_simultaneous_answers"))
	if chosen:
		return chosen
	workers = cint(frappe.conf.get("gunicorn_workers")) or BENCH_DEFAULT_WORKERS
	return max(1, (workers - 1) // 2)


@contextmanager
def answer_slot(limit):
	"""A place among the few answers the site gives at once: yields True when there is one, False when they are all taken.

	An answer holds a web worker for as long as the model takes. The shop has a handful of them, and ten visitors
	asking together would hold them all: the shop itself would stop answering. A sorted set in Redis holds who is being
	answered, scored by the moment they started; a holder that dies is forgotten after LOCK_SECONDS.

	The place is taken first and checked after: of two visitors racing for the last place, the one that started first
	keeps it, and neither is refused by the other's trial.
	"""
	cache = frappe.cache()
	key = cache.make_key(ANSWER_SLOTS_KEY)
	token = frappe.generate_hash(length=16)
	now = time.time()
	cache.zremrangebyscore(key, 0, now - LOCK_SECONDS)
	cache.zadd(key, {token: now})
	cache.expire(key, LOCK_SECONDS * 2)
	rank = cache.zrank(key, token)
	if rank is None or rank >= limit:
		cache.zrem(key, token)
		yield False
		return
	try:
		yield True
	finally:
		cache.zrem(key, token)


def clear_answer_slots():
	frappe.cache().delete(frappe.cache().make_key(ANSWER_SLOTS_KEY))
# //// Neoffice ▲▲▲


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
		# //// Neoffice — msgids were French, now English (house rule); the French screen is unchanged, served by the translation catalogue.
		line += " " + _("You can also call us at {0}.").format(data.phone)
	return line


def unavailable(ctx, reason):
	"""The notice the visitor reads instead of an answer, and what the widget does with it.

	`reason` is "outage" (the model failed), "limit" (the visitor's messages for today),
	"cap" (the shop's tokens for the month) or "busy" (the site's hour, or every place taken).
	The words are the merchant's when set.
	"""
	s = ctx.settings
	if reason == "limit":
		lead = labels()["limit"]
	elif reason == "busy":
		# //// Neoffice — a busy site is not a paused assistant: the merchant's "pause" sentence would lie (lot C of the 2026-10-30 audit)
		lead = _("The assistant is very busy at the moment: please try again in a little while.")
	else:
		lead = (s.get("assistant_offline_message") or "").strip() or _("The assistant is not available at the moment.")
	invite = _("Leave us your message below: the team will reply by email.")
	return {
		"reply": " ".join(p for p in (lead, store_status_line(s), invite) if p),
		"unavailable": reason,
		"leave_message": True,
		"email_required": not signed_in(ctx),
	}


# //// Neoffice ▼▼▼ — lot A of the 2026-10-30 audit: what the browser sends is not trusted into the prompt or the database
def _guest_session():
	"""The guest cookie, when it has the shape the shop gives it; None for anything else.

	The cookie is a string the visitor writes. A long one overflowed the 140 characters of the field and made the
	insert raise; any one of them was a Redis key and a SQL parameter.
	"""
	from webshop.webshop.shopping_cart.guest_cart import get_guest_session_id

	try:
		guest = str(get_guest_session_id() or "")
	except Exception:
		return None
	return guest if GUEST_SESSION_SHAPE.match(guest) else None


def clean_route(route):
	"""The page route the browser names, kept only when it is the route of a page the shop serves.

	It is written into the SYSTEM prompt ("the visitor writes from the page /..."): a sentence there speaks with the
	system's voice. A shape check removes spaces and line breaks, and the lookup removes everything that is not a page.
	"""
	route = (route or "").strip().strip("/")
	if not route or ".." in route or not ROUTE_SHAPE.match(route):
		return ""
	if (
		route in SHOP_PAGES
		or frappe.db.exists("Website Item", {"route": route, "published": 1})
		or frappe.db.exists("Item Group", {"route": route})
		or frappe.db.exists("Web Page", {"route": route, "published": 1})
	):
		return route
	return ""
# //// Neoffice ▲▲▲


def context(page_route=None, conversation=None):
	"""Who is asking, resolved on the server. The browser only says which page."""
	from webshop.webshop.shopping_cart.cart import get_party

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
		guest_session = _guest_session()
	return frappe._dict(
		user=user,
		customer=customer,
		guest_session=guest_session,
		settings=settings(),
		# //// Neoffice — was (page_route or "").strip()[:140], written as it came into the system prompt
		page_route=clean_route(page_route),
		conversation=conversation,
		summary=None,
	)


def find_conversation(ctx, create=False):
	"""The visitor's open conversation, resumed for RESUME_WITHIN_DAYS."""
	since = add_days(now_datetime(), -RESUME_WITHIN_DAYS)
	filters = {
		"status": ["in", ("Open", "Escalated")],
		"last_message_on": [">=", since],
		# //// Neoffice — a thread at its size is not resumed, whatever its status (lot C of the 2026-10-30 audit)
		"message_count": ["<", MAX_CONVERSATION_MESSAGES],
	}
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
	guest = _guest_session()
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


# //// Neoffice — msgids were French, now English (house rule); the French screen is unchanged, served by the translation catalogue.
def greeting(ctx):
	s = ctx.settings
	name = (s.get("assistant_name") or "Nora").strip()
	welcome = (s.get("assistant_welcome") or "").strip()
	if ctx.user and ctx.user != "Guest":
		first_name = frappe.db.get_value("User", ctx.user, "first_name") or ""
		hello = _("Hello {0}!").format(first_name) if first_name else _("Hello!")
		return f"{hello} " + (welcome or _("I am {0}, the shop assistant. An order to track, a product to find?").format(name))
	return welcome or _("Hello! I am {0}, the shop assistant. A product, our opening hours, an order? I am here to help.").format(name)


def labels():
	return {
		"title": _("Assistant"),
		"placeholder": _("Write your message…"),
		"send": _("Send"),
		"typing": _("typing…"),
		"talk_to_team": _("Talk to the team"),
		"new_conversation": _("New conversation"),
		"resume": _("Shall we pick up where we left off?"),
		"close": _("Close"),
		"open": _("Open the assistant"),
		"error": _("The message was not sent. Please try again in a moment."),
		"limit": _("You have reached the message limit for today."),
		# //// Neoffice — labels for the answering machine's "leave a message" form (814347b504 "feat(assistant): an answering machine when the model is down or the limit is reached")
		"leave_title": _("Leave a message for the team"),
		"leave_placeholder": _("Your message for the team…"),
		"leave_email": _("Your email address"),
		"leave_send": _("Send to the team"),
		"leave_cancel": _("Cancel"),
		"leave_error": _("The message could not be sent. Please try again, or write to us directly."),
		# //// Neoffice — the visitor's opinion of an answer (lot D of the 2026-10-30 audit)
		"useful": _("Useful"),
		"not_useful": _("Not useful"),
		# //// Neoffice — not "Report": the catalogue already says "Rapport" for a report (a document), which on a French shop read as a link to a report
		"report": _("Report a problem"),
		"thanks": _("Thank you for your opinion."),
		"suggestions": [
			_("What are your opening hours?"),
			_("Where is my order?"),
			_("I am looking for a product"),
			_("Talk to someone"),
		],
	}


@frappe.whitelist(allow_guest=True)  # nosemgrep: frappe-semgrep-rules.rules.security.guest-whitelisted-method -- reviewed in the 2026-10-30 audit of the assistant (neoffice-maintenance#2015, #2019): open to visitors on purpose, throttled per connection, the identity read from the session only
# //// Neoffice — every page of the shop asks for this, and it was open to any number of calls: it reads the month's token sum and looks the visitor's conversation up (lot A of the 2026-10-30 audit)
@throttle.throttle("config", 120, 60)
def get_config(page_route: str | None = None):
	s = settings()
	if not enabled(s):
		return {"enabled": False}
	usage.count("config_calls")
	# //// Neoffice — the page is not needed to draw the bubble (`page_route` stays in the signature for the widget's call); not looking it up spares this hot path three queries
	ctx = context()
	conversation = find_conversation(ctx)
	history = []
	if conversation:
		visible = [m for m in conversation.messages if m.role in ("user", "assistant") and m.content and not m.tool_calls]
		history = [_shown(m) for m in visible[-HISTORY_SHOWN:]]
	return {
		"enabled": True,
		"name": (s.get("assistant_name") or "Nora").strip(),
		"position": s.get("assistant_position") or "Bottom right",
		"color": s.get("assistant_color") or "",
		"greeting": greeting(ctx),
		"signed_in": bool(ctx.user and ctx.user != "Guest"),
		"history": history,
		"labels": labels(),
		"consent": consent_line(s, bool(ctx.user and ctx.user != "Guest")),
		# //// Neoffice — the answering machine (814347b504 "feat(assistant): an answering machine when the model is down or the limit is reached")
		# the answering machine speaks from the first screen when it has to
		"notice": unavailable(ctx, reason) if (reason := unavailable_reason(ctx, conversation)) else None,
	}


# //// Neoffice — lot E of the 2026-10-30 audit: the sentence a visitor reads while anonymised samples are kept
def consent_line(s, signed_in):
	"""What the visitor is told when samples are collected, None when they are not or when this visitor is not collected.

	Only visitors who are not signed in are sampled, so only they are told. The merchant's own sentence wins.
	"""
	if not cint(s.get("assistant_collect_samples")) or signed_in:
		return None
	return (s.get("assistant_consent_text") or "").strip() or _("Conversations may be used, anonymously, to improve the service.")


# //// Neoffice — lot D of the 2026-10-30 audit: an answer is drawn again with its name and the opinion already given
OPINIONS = {"Useful": "up", "Not useful": "down"}


def _shown(m):
	entry = {"role": m.role, "content": m.content, "sent_on": str(m.sent_on)}
	if m.role == "assistant":
		entry.update(id=m.name, feedback=OPINIONS.get(m.feedback, ""), reported=bool(m.reported))
	return entry


def _daily_limit_reached(conversation, ctx):
	s = ctx.settings
	if ctx.user and ctx.user != "Guest":
		limit = cint(s.get("assistant_user_daily_limit")) or DEFAULT_USER_DAILY
	else:
		limit = cint(s.get("assistant_guest_daily_limit")) or DEFAULT_GUEST_DAILY
	today = now_datetime().date()
	sent_today = len([m for m in conversation.messages if m.role == "user" and m.sent_on and m.sent_on.date() == today])
	return sent_today >= limit


# //// Neoffice — the cap the merchant set, else the default: an empty field used to mean no cap at all (lot A of the 2026-10-30 audit)
def monthly_cap(s=None):
	"""Tokens the shop may spend in a month: the merchant's figure, else DEFAULT_MONTHLY_TOKEN_CAP."""
	return cint((s or settings()).get("assistant_monthly_token_cap")) or DEFAULT_MONTHLY_TOKEN_CAP


def _monthly_cap_reached(ctx):
	return engine.monthly_tokens() >= monthly_cap(ctx.settings)


# //// Neoffice — the answering machine: what a "no answer" actually means (outage, daily limit, monthly cap), and what to write on the conversation for the outage case (814347b504 "feat(assistant): an answering machine when the model is down or the limit is reached")
def unavailable_reason(ctx, conversation=None):
	if in_outage():
		return "outage"
	if conversation and _daily_limit_reached(conversation, ctx):
		return "limit"
	if _monthly_cap_reached(ctx):
		return "cap"
	# //// Neoffice — the whole site's hour: a flood that keeps changing visitor still meets a ceiling (lot A of the 2026-10-30 audit)
	if site_hour_count() >= SITE_HOURLY_MESSAGES:
		return "busy"
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
	out["conversation"] = conversation.name if conversation else None
	out["limited"] = reason in ("limit", "cap", "busy")
	return out


@frappe.whitelist(allow_guest=True, methods=["POST"])  # nosemgrep: frappe-semgrep-rules.rules.security.guest-whitelisted-method -- reviewed in the 2026-10-30 audit of the assistant (neoffice-maintenance#2015, #2019): open to visitors on purpose, throttled per connection, the identity read from the session only
# //// Neoffice — was frappe's @rate_limit(limit=20, seconds=600), keyed on the first X-Forwarded-For entry; a day's ceiling per connection is new (lot A of the 2026-10-30 audit)
@throttle.throttle("send", 20, 600, on_refuse=lambda: usage.refused("rate"))
@throttle.throttle("send-day", 150, 86400, on_refuse=lambda: usage.refused("rate"))
def send(message: str, page_route: str | None = None):
	s = settings()
	if not enabled(s):
		# //// Neoffice — counted, then refused (lot D of the 2026-10-30 audit)
		usage.refused("off")
		frappe.throw(_("The assistant is not enabled."), frappe.PermissionError)
	usage.count("received")
	# //// Neoffice — msgids were French, now English (house rule); the French screen is unchanged, served by the translation catalogue.
	text = (message or "").strip()
	if not text:
		frappe.throw(_("The message is empty."))
	text = text[:MAX_MESSAGE_CHARS]
	ctx = context(page_route)
	usage.count("signed_in" if signed_in(ctx) else "guests")
	# //// Neoffice — one message at a time per visitor (lot A of the 2026-10-30 audit): the second of two parallel sends is told to wait instead of raising on a stale conversation
	with conversation_lock(ctx) as free:
		if not free:
			usage.declined("locked")
			return {"reply": _("Your previous message is still being answered. One moment, please."), "busy": True}
		return _answer(ctx, text)


def _answer(ctx, text):
	"""One message in, one reply out, for a visitor nobody else is answering."""
	conversation = find_conversation(ctx, create=True)
	if not conversation:
		frappe.throw(_("Unable to open a conversation for this session."))
	ctx.conversation = conversation
	if ctx.page_route:
		conversation.page_route = ctx.page_route
	# //// Neoffice — was: the limit label alone, the cap sentence alone, and on a model
	# //// failure the canned FALLBACK; each left the visitor with nothing to do. Now every
	# //// one of them is the answering machine, and a failure arms the outage flag so the
	# //// next visitors get the notice at once instead of a 25 s wait.
	reason = unavailable_reason(ctx, conversation)
	if reason:
		usage.declined(REFUSAL_OF_REASON[reason])
		return _answering_machine(conversation, ctx, reason, user_text=text)
	# //// Neoffice — only a few answers at once: each holds a web worker for as long as the model takes (lot C of the 2026-10-30 audit). Nothing is written for the visitor who is turned away, who asks again in a moment.
	with answer_slot(max_simultaneous(ctx.settings)) as granted:
		if not granted:
			usage.declined("busy")
			return _answering_machine(conversation, ctx, "busy")
		return _respond(conversation, ctx, text)


def _respond(conversation, ctx, text):
	"""The model's answer to one message, within a place taken by `answer_slot`."""
	bump_site_hour()
	try:
		out = engine.respond(conversation, text, ctx)
	except llm.ModelUnavailable:
		frappe.log_error("Shop assistant: the model did not answer", frappe.get_traceback())
		# //// Neoffice — the answering machine: arm the outage flag so the next visitors get the notice at once, and answer this one the same way instead of a bare error (814347b504 "feat(assistant): an answering machine when the model is down or the limit is reached")
		# //// Neoffice — only the model's failure arms it; this branch used to be `except Exception` (lot A of the 2026-10-30 audit)
		mark_outage()
		usage.declined("outage")
		# respond() already wrote the visitor's words on the conversation
		result = _answering_machine(conversation, ctx, "outage")
		result["failed"] = True
		return result
	except Exception:
		# //// Neoffice — a fault of ours is not the model's: this visitor is told, with the way to the team, and the
		# //// next ones are not (the flag switches the assistant off for everybody for OUTAGE_SECONDS). Nothing is
		# //// saved here: the conversation may be the very thing that failed.
		frappe.log_error("Shop assistant: reply failed", frappe.get_traceback())
		usage.count("errors")
		result = unavailable(ctx, "outage")
		result.update(failed=True, conversation=conversation.name, limited=False)
		return result
	usage.record_turn(out.model_calls, out.tool_calls, out.prompt_tokens, out.completion_tokens, out.duration_ms)
	# //// Neoffice — a thread that reached its size is closed (an escalated one stays the team's); the visitor's next message opens a new one (lot C of the 2026-10-30 audit)
	if conversation.status == "Open" and cint(conversation.message_count) >= MAX_CONVERSATION_MESSAGES:
		frappe.db.set_value("Shop Assistant Conversation", conversation.name, "status", "Closed", update_modified=False)
	return {
		"reply": out.reply,
		"message_id": out.message_id,
		"conversation": out.conversation,
		"escalated": conversation.status == "Escalated",
	}


# //// Neoffice ▼▼▼ — the answering machine's tape: the "leave a message" endpoint and the escalation it triggers, reached with no model involved when the model is down or a limit is hit (814347b504 "feat(assistant): an answering machine when the model is down or the limit is reached")
@frappe.whitelist(allow_guest=True, methods=["POST"])
# //// Neoffice — was frappe's @rate_limit(limit=5, seconds=600), keyed on the first X-Forwarded-For entry; the day's ceiling is new (lot A of the 2026-10-30 audit)
@throttle.throttle("leave", 5, 600)
@throttle.throttle("leave-day", 15, 86400)
def leave_message(message, email=None, page_route=None):
	"""The answering machine's tape: the visitor's words go to the team as they are."""
	s = settings()
	if not enabled(s):
		frappe.throw(_("The assistant is not enabled."), frappe.PermissionError)
	# //// Neoffice — msgids were French, now English (house rule); the French screen is unchanged, served by the translation catalogue.
	text = (message or "").strip()[:MAX_MESSAGE_CHARS]
	if not text:
		frappe.throw(_("The message is empty."))
	ctx = context(page_route)
	# //// Neoffice — saves the same conversation `send` is answering on: one at a time (lot A of the 2026-10-30 audit); an error, not a reply, so the form stays open and the words are not lost
	with conversation_lock(ctx) as free:
		if not free:
			frappe.throw(_("Your previous message is still being answered. One moment, please."))
		return leave(ctx, text, email)


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
		# //// Neoffice — validate_email_address accepts a whole list ("a@x.ch,b@y.ch"), which went on as ONE recipient: the team's door was a mail relay for strangers (lot A of the 2026-10-30 audit)
		email = escalation.single_email(email)
		if not email:
			frappe.throw(_("Enter a valid email address so the team can reply to you."))
	conversation = ctx.conversation or find_conversation(ctx, create=True)
	if not conversation:
		frappe.throw(_("Unable to open a conversation for this session."))
	ctx.conversation = conversation
	# the form is prefilled with the words the model could not answer: no second copy
	last_user = next((m for m in reversed(conversation.messages) if m.role == "user"), None)
	if not last_user or (last_user.content or "").strip() != text:
		conversation.add_message("user", text)
	out = escalation.contact_team(ctx, summary=text, email=email)
	reply = _("Your message has been passed on. The team will reply to {0}.").format(email)
	status = store_status_line(ctx.settings)
	if status:
		reply = f"{reply} {status}"
	conversation.add_message("assistant", reply)
	conversation.flags.ignore_permissions = True
	conversation.save()
	usage.count("leave_messages")
	return {"reply": reply, "conversation": conversation.name, "escalated": True, "via": out.get("via")}
# //// Neoffice ▲▲▲


# //// Neoffice ▼▼▼ — lot D of the 2026-10-30 audit: the visitor says whether an answer helped, or reports it
@frappe.whitelist(allow_guest=True, methods=["POST"])  # nosemgrep: frappe-semgrep-rules.rules.security.guest-whitelisted-method -- reviewed in the 2026-10-30 audit of the assistant (neoffice-maintenance#2015, #2019): open to visitors on purpose, throttled per connection, the identity read from the session only
@throttle.throttle("rate", 30, 600)
@throttle.throttle("rate-day", 200, 86400)
def rate_message(message: str, rating: str):
	"""Record the visitor's opinion of one answer: "up" (useful), "down" (not useful) or "report".

	The answer must belong to the visitor's own conversation, by the session and nothing the browser says: an answer of
	somebody else, the visitor's own words and the assistant's tool rounds are all "not found". An opinion is counted
	when it changes, so a double click is one opinion.
	"""
	s = settings()
	if not enabled(s):
		frappe.throw(_("The assistant is not enabled."), frappe.PermissionError)
	if rating not in ("up", "down", "report"):
		frappe.throw(_("Unknown opinion."))
	ctx = context()
	row = frappe.db.get_value(
		"Shop Assistant Message",
		{"name": message, "parenttype": "Shop Assistant Conversation", "role": "assistant"},
		["name", "parent", "tool_calls", "feedback", "reported"],
		as_dict=True,
	)
	owner = row and frappe.db.get_value("Shop Assistant Conversation", row.parent, ["user", "guest_session"], as_dict=True)
	mine = bool(owner) and (
		owner.user == ctx.user if signed_in(ctx) else (not owner.user and bool(ctx.guest_session) and owner.guest_session == ctx.guest_session)
	)
	if not row or row.tool_calls or not mine:
		frappe.throw(_("Message not found."), frappe.DoesNotExistError)
	changes = {}
	if rating == "report":
		if not row.reported:
			changes = {"reported": 1}
			usage.count("reported")
	elif row.feedback != ("Useful" if rating == "up" else "Not useful"):
		changes = {"feedback": "Useful" if rating == "up" else "Not useful"}
		usage.count("feedback_up" if rating == "up" else "feedback_down")
	if changes:
		changes["feedback_on"] = now_datetime()
		frappe.db.set_value("Shop Assistant Message", row.name, changes, update_modified=False)
	return {"ok": True}
# //// Neoffice ▲▲▲


@frappe.whitelist(allow_guest=True, methods=["POST"])
# //// Neoffice — was open to any number of calls (lot A of the 2026-10-30 audit)
@throttle.throttle("reset", 10, 600)
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
		# //// Neoffice — the cap in force (the default when the merchant set none), not "no cap"
		"monthly_cap": monthly_cap(),
		# //// Neoffice — what the counters of lot D say: every request, those turned away included (the 2026-10-30 audit)
		**_request_stats(month_start),
	}


def _request_stats(month_start):
	month = usage.totals(month_start, nowdate())
	today = usage.totals(nowdate(), nowdate())
	return {
		"requests": month["received"],
		"answered": month["answered"],
		"refused": {reason: month[f"refused_{reason}"] for reason in usage.REFUSAL_REASONS},
		"refused_total": month["refused"],
		"feedback": {"up": month["feedback_up"], "down": month["feedback_down"], "reported": month["reported"]},
		"today": {"received": today["received"], "answered": today["answered"], "refused": today["refused"]},
	}


@frappe.whitelist()
def usage_stats():
	frappe.only_for(("System Manager", "Website Manager"))
	return get_usage_stats()


# //// Neoffice — nightly purge job feeding the usage report and retention policy (84412d0bec "feat(assistant): usage report, nightly purge, conversations on the customer record")
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
