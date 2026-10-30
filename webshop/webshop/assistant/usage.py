# //// Neoffice — added file (shop assistant, no upstream equivalent).
"""What the assistant is asked, answers and refuses, counted without touching the database (lot D of the 2026-10-30 audit).

Counting goes to a Redis hash per day (`HINCRBY`, atomic): a flood of requests costs the database nothing, and the ones
the rate limit turns away before the endpoint runs are counted too, which is what a person watching an attack needs to
see. Each night `flush_finished_days` writes the finished days to `Shop Assistant Usage Day`, one row a day, figures
only: no word a visitor wrote, no address. That row is what the service is billed from.

The browser counts nothing: a counter in the front end is a counter anyone can write.
"""

import math

import frappe
import redis
from frappe.utils import add_days, cint, getdate, nowdate

PREFIX = "webshop_assistant_usage"
# a day's counters outlive the night's write by a few days, so a job that did not run is caught up by the next one
KEPT_DAYS = 4

# why a request got no answer; each is a column of the day's row (`refused_<reason>`)
REFUSAL_REASONS = ("rate", "day_limit", "month_cap", "outage", "busy", "locked", "off")
# the columns that are plain sums, in the order of the day's row
SUMS = (
	"received",
	"answered",
	"errors",
	"guests",
	"signed_in",
	"config_calls",
	"leave_messages",
	"model_calls",
	"tool_calls",
	"prompt_tokens",
	"completion_tokens",
	"feedback_up",
	"feedback_down",
	"reported",
) + tuple(f"refused_{reason}" for reason in REFUSAL_REASONS)
# answer times are counted in buckets (upper bounds, milliseconds), so a median and a 95th percentile need no list of
# every duration: eleven counters a day
DURATION_BUCKETS = (500, 1000, 2000, 3000, 5000, 8000, 12000, 20000, 30000, 60000, 120000)


def _day(day=None):
	return str(getdate(day)) if day else nowdate()


def _key(day):
	return frappe.cache().make_key(f"{PREFIX}:{day}")


def count(field, number=1, day=None):
	"""Add `number` to `field` of the day's counters.

	Counting is for the shop's eyes: a Redis that cannot be written must never turn into an error for the visitor being answered.
	"""
	try:
		cache = frappe.cache()
		key = _key(_day(day))
		cache.hincrby(key, field, number)
		cache.expire(key, KEPT_DAYS * 86400)
	except redis.RedisError:
		pass


def refused(reason, day=None):
	"""A request turned away before the endpoint counted it (the rate limit, the switch off), and why. It is a request too."""
	count("received", day=day)
	declined(reason, day=day)


def declined(reason, day=None):
	"""A request already counted as received that got no answer, and why."""
	if reason not in REFUSAL_REASONS:
		raise ValueError(f"unknown reason for a refusal: {reason!r}")
	count(f"refused_{reason}", day=day)


def record_turn(model_calls, tool_calls, prompt_tokens, completion_tokens, duration_ms, day=None):
	"""An answer was given: what it cost."""
	count("answered", day=day)
	count("model_calls", model_calls, day=day)
	count("tool_calls", tool_calls, day=day)
	count("prompt_tokens", prompt_tokens, day=day)
	count("completion_tokens", completion_tokens, day=day)
	bucket = next((bound for bound in DURATION_BUCKETS if cint(duration_ms) <= bound), DURATION_BUCKETS[-1])
	count(f"ms_{bucket}", day=day)


def _read(key):
	"""A counters hash as `{field: number}`.

	Frappe's own `hgetall` prefixes the name again and unpickles the values; these are plain integers written by `HINCRBY`
	under a key that is already prefixed, so the connection's own command is called.
	"""
	raw = redis.Redis.hgetall(frappe.cache(), key) or {}
	return {_text(field): cint(number) for field, number in raw.items()}


def _text(value):
	return value.decode() if isinstance(value, bytes) else value


def counters(day=None):
	"""The day's counters so far, `{field: number}`; empty for a day nobody wrote to."""
	return _read(_key(_day(day)))


def forget(day=None):
	frappe.cache().delete(_key(_day(day)))


def percentiles(seen):
	"""(median, 95th percentile) of the answer times, as the upper bound of the bucket that holds each."""
	buckets = [(bound, cint(seen.get(f"ms_{bound}"))) for bound in DURATION_BUCKETS]
	total = sum(number for _, number in buckets)
	if not total:
		return 0, 0

	def at(share):
		wanted = math.ceil(total * share)
		running = 0
		for bound, number in buckets:
			running += number
			if running >= wanted:
				return bound
		return DURATION_BUCKETS[-1]

	return at(0.5), at(0.95)


def flush(day):
	"""Write the day's counters to its row (adding to it when the day was already written) and empty them.

	The counters are renamed first, atomically, to a key of their own: a request that counts while the row is written lands in
	a fresh hash, which the next flush finds, instead of being lost between the read and the delete. The renamed counters are
	deleted only once the row is saved, so a write that fails loses nothing: the next flush finds them again. Returns the row's
	name, or None when nobody counted anything that day. A day written twice keeps the percentiles of the first writing.
	"""
	day = _day(day)
	cache = frappe.cache()
	key = _key(day)
	taken = cache.make_key(f"{PREFIX}:{day}:flushing:{frappe.generate_hash(length=8)}")
	try:
		cache.rename(key, taken)
	except Exception:  # no such key: nothing was counted since the last flush
		pass
	# this flush's own counters, and those of an earlier flush whose write failed
	pending = [raw.decode() if isinstance(raw, bytes) else raw for raw in cache.keys(cache.make_key(f"{PREFIX}:{day}:flushing:*"))]
	seen = {}
	for name in pending:
		for field, number in _read(name).items():
			seen[field] = seen.get(field, 0) + number
	if not seen:
		for name in pending:
			cache.delete(name)
		return None
	name = frappe.db.get_value("Shop Assistant Usage Day", {"day": day}, "name")
	row = frappe.get_doc("Shop Assistant Usage Day", name) if name else frappe.new_doc("Shop Assistant Usage Day")
	row.day = day
	for field in SUMS:
		row.set(field, cint(row.get(field)) + seen.get(field, 0))
	if not name:
		row.median_ms, row.p95_ms = percentiles(seen)
	row.flags.ignore_permissions = True
	row.save() if name else row.insert()
	for name in pending:
		cache.delete(name)
	return row.name


def flush_finished_days():
	"""Nightly: write every finished day still held in Redis. Today is left counting. Returns the days written.

	A scheduled job is committed by the scheduler when it ends: no commit here."""
	today = getdate(nowdate())
	written = []
	for age in range(KEPT_DAYS, 0, -1):
		day = str(add_days(today, -age))
		if flush(day):
			written.append(day)
	return written


def by_day(first, last):
	"""`{day: {field: number}}` for the days `first` to `last` that have any: the written rows and the days still counting.

	A day is in one place or the other (the night's write empties Redis), but a day written and then counted again is both,
	and its two halves are added.
	"""
	first, last = getdate(first), getdate(last)
	days = {}
	rows = frappe.get_all(
		"Shop Assistant Usage Day", filters={"day": ["between", (first, last)]}, fields=["day", *SUMS], limit_page_length=0
	)
	for row in rows:
		days[str(row.day)] = {field: cint(row.get(field)) for field in SUMS}
	for age in range(KEPT_DAYS + 1):
		day = add_days(last, -age)
		if day < first:
			break
		live = counters(day)
		if not live:
			continue
		mine = days.setdefault(str(day), {field: 0 for field in SUMS})
		for field in SUMS:
			mine[field] += live.get(field, 0)
	for mine in days.values():
		mine["refused"] = sum(mine[f"refused_{reason}"] for reason in REFUSAL_REASONS)
	return days


def totals(first, last):
	"""The sum of every counter over the days `first` to `last`, `refused` (every reason together) included."""
	total = {field: 0 for field in SUMS}
	for mine in by_day(first, last).values():
		for field in SUMS:
			total[field] += mine[field]
	total["refused"] = sum(total[f"refused_{reason}"] for reason in REFUSAL_REASONS)
	return total
