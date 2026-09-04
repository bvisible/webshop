# //// Neoffice — added file (store hours, no upstream equivalent).
"""The store's opening hours: one source of truth for the public component,
the /store-hours page and the shop assistant.

The rows live on Webshop Settings: `store_hours` (Store Opening Hours, several
rows per weekday when there is a lunch break) and `store_closures` (Store
Closure: holidays, inventory, a move). Every computation takes the clock as an
argument, so tests fix it and the endpoint passes the site's own now.

The one rule worth writing down, because the widget this replaces got it
wrong: the next opening is looked for on the CURRENT day first. Closed between
12:00 and 13:30, a shop reopens "today at 13:30", not "tomorrow at 10:00".
"""

import datetime

import frappe
from frappe import _
from frappe.utils import add_days, formatdate, get_time, getdate, now_datetime

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
LOOKAHEAD_DAYS = 21
CLOSURES_HORIZON_DAYS = 60


def get_settings():
	return frappe.get_cached_doc("Webshop Settings")


def schedule(settings=None):
	"""The weekly periods and the closures, parsed once.

	Returns a dict with `periods` ({weekday index: [(opens, closes), ...]},
	Monday = 0, sorted, invalid rows dropped), `closures` ([{from_date, to_date,
	label}]), `note`, and `configured` (at least one period exists).
	"""
	settings = settings or get_settings()
	periods = {}
	for row in settings.get("store_hours") or []:
		if row.get("weekday") not in WEEKDAYS:
			continue
		opens, closes = get_time(row.get("opens")), get_time(row.get("closes"))
		if not opens or not closes or closes <= opens:
			continue
		periods.setdefault(WEEKDAYS.index(row.get("weekday")), []).append((opens, closes))
	for day in periods:
		periods[day].sort()
	closures = []
	for row in settings.get("store_closures") or []:
		if not row.get("from_date") or not row.get("to_date"):
			continue
		closures.append(
			frappe._dict(
				from_date=getdate(row.get("from_date")),
				to_date=getdate(row.get("to_date")),
				label=(row.get("label") or "").strip(),
			)
		)
	return frappe._dict(
		periods=periods,
		closures=closures,
		note=(settings.get("store_hours_note") or "").strip(),
		configured=bool(periods),
	)


def closure_for(day, sched):
	"""The label of the closure covering `day` (the empty string when it has no
	label), or None when the day is not a closure."""
	for closure in sched.closures:
		if closure.from_date <= day <= closure.to_date:
			return closure.label or ""
	return None


def periods_on(day, sched):
	"""Opening periods of a calendar day: none during a closure."""
	if closure_for(day, sched) is not None:
		return []
	return sched.periods.get(day.weekday(), [])


def status_at(now, settings=None, sched=None):
	"""Open or closed at `now`, and what comes next.

	Returns `is_open`, `closes_at` (datetime, when open), `next_opening`
	(datetime, when closed and something opens within LOOKAHEAD_DAYS),
	`closure` (the label of today's closure, None otherwise).
	"""
	sched = sched or schedule(settings)
	today = now.date()
	clock = now.time()
	closure = closure_for(today, sched)
	if closure is None:
		for opens, closes in sched.periods.get(today.weekday(), []):
			if opens <= clock < closes:
				return frappe._dict(
					is_open=1, closes_at=datetime.datetime.combine(today, closes), next_opening=None, closure=None
				)
			if clock < opens:
				return frappe._dict(
					is_open=0, closes_at=None, next_opening=datetime.datetime.combine(today, opens), closure=None
				)
	for offset in range(1, LOOKAHEAD_DAYS + 1):
		day = today + datetime.timedelta(days=offset)
		periods = periods_on(day, sched)
		if periods:
			return frappe._dict(
				is_open=0,
				closes_at=None,
				next_opening=datetime.datetime.combine(day, periods[0][0]),
				closure=closure,
			)
	return frappe._dict(is_open=0, closes_at=None, next_opening=None, closure=closure)


def format_clock(value):
	"""13:30 as a French shop writes it (13h30) when the site speaks French."""
	value = get_time(value)
	if (frappe.local.lang or "").startswith("fr"):
		return f"{value.hour}h{value.minute:02d}"
	return f"{value.hour:02d}:{value.minute:02d}"


def format_span(delta):
	"""A remaining time as customers read it: '2h 15min', '15 min'."""
	minutes = max(0, int(delta.total_seconds() // 60))
	hours, minutes = divmod(minutes, 60)
	if hours:
		return _("{0}h {1}min").format(hours, minutes)
	return _("{0} min").format(minutes)


def day_text(periods):
	"""'10h00 - 12h00 / 13h30 - 18h00', 'non-stop' for one period across lunch, 'Closed' otherwise."""
	if not periods:
		return _("Closed")
	parts = [f"{format_clock(opens)} - {format_clock(closes)}" for opens, closes in periods]
	text = " / ".join(parts)
	if len(periods) == 1:
		opens, closes = periods[0]
		if opens <= datetime.time(12, 30) and closes >= datetime.time(13, 30):
			text += " " + _("non-stop")
	return text


def describe(status, now):
	"""The two lines of the banner: the state, and what happens next."""
	if status.is_open:
		return _("Currently open"), _("Closes in {0}").format(format_span(status.closes_at - now))
	headline = _("Closed: {0}").format(status.closure) if status.closure else _("Currently closed")
	if not status.next_opening:
		return headline, ""
	day = status.next_opening.date()
	clock = format_clock(status.next_opening.time())
	today = now.date()
	if day == today:
		detail = _("Opens today at {0}").format(clock)
	elif day == add_days(today, 1):
		detail = _("Opens tomorrow at {0}").format(clock)
	elif (day - today).days < 7:
		detail = _("Opens {0} at {1}").format(_(WEEKDAYS[day.weekday()]), clock)
	else:
		detail = _("Opens on {0} at {1}").format(formatdate(day, "d MMMM"), clock)
	return headline, detail


def week(now, sched):
	"""The seven days from Monday, each with its text and whether it is today."""
	today = now.date()
	out = []
	for index, name in enumerate(WEEKDAYS):
		periods = sched.periods.get(index, [])
		label = _(name)
		out.append(
			frappe._dict(
				weekday=name,
				# French translations write weekdays in lower case; a sign in the
				# window starts them with a capital.
				label=label[:1].upper() + label[1:],
				periods=[{"opens": format_clock(o), "closes": format_clock(c)} for o, c in periods],
				text=day_text(periods),
				closed=not periods,
				is_today=index == today.weekday(),
			)
		)
	return out


def upcoming_closures(now, sched, horizon_days=CLOSURES_HORIZON_DAYS):
	"""Closures that end today or later and start within the horizon, oldest first."""
	today = now.date()
	limit = add_days(today, horizon_days)
	out = []
	for closure in sorted(sched.closures, key=lambda c: c.from_date):
		if closure.to_date < today or closure.from_date > limit:
			continue
		if closure.from_date == closure.to_date:
			when = formatdate(closure.from_date, "EEEE d MMMM")
		else:
			when = _("from {0} to {1}").format(
				formatdate(closure.from_date, "d MMMM"), formatdate(closure.to_date, "d MMMM")
			)
		out.append(
			frappe._dict(
				from_date=str(closure.from_date),
				to_date=str(closure.to_date),
				label=closure.label,
				text=f"{when} · {closure.label}" if closure.label else when,
			)
		)
	return out


def opening_hours(now=None, settings=None):
	"""Everything the component, the page and the assistant show."""
	settings = settings or get_settings()
	now = now or now_datetime()
	sched = schedule(settings)
	status = status_at(now, sched=sched)
	headline, detail = describe(status, now) if sched.configured else ("", "")
	return frappe._dict(
		configured=sched.configured,
		title=_("Opening hours"),
		today_text=formatdate(now.date(), "EEEE d MMMM yyyy"),
		is_open=status.is_open,
		headline=headline,
		detail=detail,
		next_opening=status.next_opening.isoformat() if status.next_opening else None,
		closes_at=status.closes_at.isoformat() if status.closes_at else None,
		week=week(now, sched),
		closures=upcoming_closures(now, sched),
		note=sched.note,
		address=(settings.get("store_address") or "").strip(),
		phone=(settings.get("store_phone") or "").strip(),
		email=(settings.get("store_email") or "").strip(),
	)


@frappe.whitelist(allow_guest=True)
def get_opening_hours():
	"""Public: what the component draws. Nothing here depends on who asks."""
	return opening_hours()


def hours_summary(now=None, settings=None):
	"""One paragraph for the assistant's answer and for the summary emails."""
	data = opening_hours(now, settings)
	if not data.configured:
		return _("Opening hours are not published.")
	lines = [f"{data.headline} — {data.detail}".strip(" —")]
	lines += [f"{day.label}: {day.text}" for day in data.week]
	lines += [_("Closed {0}").format(c.text) for c in data.closures]
	if data.note:
		lines.append(data.note)
	return "\n".join(lines)
