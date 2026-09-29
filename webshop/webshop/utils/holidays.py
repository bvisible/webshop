# //// Neoffice — added file (public holidays for the store hours, no upstream equivalent).
"""Public holidays, fetched once a year and kept in a Frappe Holiday List.

The store's opening hours need to know when the shop is closed for a public
holiday. Typing them by hand means retyping them every year, and getting the
movable ones wrong: Easter Monday, Ascension, Whit Monday and Corpus Christi
move with Easter, and half of them are cantonal anyway — Valais closes on
Saint Joseph's day and the Immaculate Conception, Geneva does not.

So they are read from **openholidaysapi.org**: free, no key, and the only source
checked that gives Swiss holidays **per canton and in French**. A holiday is kept
when it is nationwide, or when one of its subdivisions is the configured one or
contains it (`CH-VS` for a shop set on Valais). A day the API gives only for a
district or a municipality below the canton is not the canton's: Sechseläuten
belongs to the city of Zurich, and closing every shop of the canton for it is
wrong (#690).

They land in a **Holiday List**, Frappe's own doctype: visible and editable on
the desk, reusable by the delivery delays that already read one, and out of the
Single. `store_hours.schedule()` merges its dates into the closures.

Nothing here ever runs on a page request. The button on Webshop Settings and the
monthly job are the only callers, and a provider that is down leaves the list
exactly as it was.
"""

import datetime
import json

import frappe
from frappe import _
from frappe.utils import add_days, getdate, today

PROVIDER = "https://openholidaysapi.org"
HOLIDAYS_ENDPOINT = PROVIDER + "/PublicHolidays"
SUBDIVISIONS_ENDPOINT = PROVIDER + "/Subdivisions"
TIMEOUT = 20
# how far ahead the yearly top-up keeps the list stocked
YEARS_AHEAD = 1


def _get(url, params):
	"""One GET at the provider, decoded leniently. None when it cannot be read.

	The provider has been seen answering with a raw control character inside a
	string, which `json.loads` rejects by default — `strict=False` accepts it
	rather than losing a whole year of holidays over one byte.
	"""
	import requests

	try:
		response = requests.get(url, params=params, timeout=TIMEOUT)
		response.raise_for_status()
		return json.loads(response.text, strict=False)
	except Exception as exc:
		frappe.log_error(
			"Public holidays: provider unreachable",
			f"{url} {params}\n{type(exc).__name__}: {exc}",
		)
		return None


def _named(entry, language):
	"""The holiday's name in the wanted language, else whatever the provider gave."""
	names = entry.get("name") or []
	wanted = (language or "").upper()
	for name in names:
		if (name.get("language") or "").upper() == wanted:
			return (name.get("text") or "").strip()
	return (names[0].get("text") if names else "").strip()


def _covers(entry, subdivision):
	"""Does this holiday apply where the shop is?

	Nationwide holidays always do. A regional one does when one of its subdivisions
	is the shop's own (`CH-VS`) or contains it (`CH`): codes nest by dashes, so
	`CH-VS` contains `CH-VS-…`. A code BELOW the shop's (a district, a municipality)
	does not count: it names a place inside the canton, not the canton. The rule
	used to keep those too, so one district's day closed the whole canton (#690).
	"""
	if entry.get("nationwide"):
		return True
	if not subdivision:
		return False
	for row in entry.get("subdivisions") or []:
		code = row.get("code") or ""
		if code and (subdivision == code or subdivision.startswith(code + "-")):
			return True
	return False


def _only_below(entry, subdivision):
	"""True for a holiday the provider gives only for places BELOW the shop's subdivision.

	These are the days the old rule wrote into the Holiday List for the whole canton.
	They are no longer kept, and `sync_holiday_list` retracts the ones already there.
	"""
	if entry.get("nationwide") or not subdivision or _covers(entry, subdivision):
		return False
	codes = [row.get("code") or "" for row in entry.get("subdivisions") or []]
	return any(code.startswith(subdivision + "-") for code in codes)


def _fetch(country, subdivision, year, language="FR"):
	"""([(date, name)] kept, {(date, name)} rejected) for one year, or None when unread.

	`rejected` holds the days of the holidays given only for places below the shop's
	subdivision (see `_only_below`): the sync uses it to retract what an older rule wrote.
	"""
	entries = _get(
		HOLIDAYS_ENDPOINT,
		{
			"countryIsoCode": country,
			"languageIsoCode": language,
			"validFrom": f"{year}-01-01",
			"validTo": f"{year}-12-31",
		},
	)
	if entries is None:
		return None
	found = {}
	rejected = set()
	for entry in entries:
		if _covers(entry, subdivision):
			keep = True
		elif _only_below(entry, subdivision):
			keep = False
		else:
			continue
		start = entry.get("startDate")
		end = entry.get("endDate") or start
		if not start:
			continue
		name = _named(entry, language) or _("Public holiday")
		day = getdate(start)
		last = getdate(end)
		# a multi-day holiday is written out day by day, the way a Holiday List holds it
		while day <= last:
			if keep:
				found.setdefault(day, name)
			else:
				rejected.add((day, name))
			day = getdate(add_days(day, 1))
	return sorted(found.items()), rejected


def fetch_holidays(country, subdivision, year, language="FR"):
	"""[(date, name)] of the public holidays of one year where the shop is.

	Returns None — not an empty list — when the provider could not be read, so a
	caller never mistakes an outage for "no holidays this year" and wipes a list.
	"""
	result = _fetch(country, subdivision, year, language)
	return None if result is None else result[0]


def subdivisions(country="CH", language="FR"):
	"""[(code, name)] of the country's regions, for the picker. Empty when unread."""
	entries = _get(SUBDIVISIONS_ENDPOINT, {"countryIsoCode": country, "languageIsoCode": language})
	if not entries:
		return []
	out = []
	for entry in entries:
		code = entry.get("code")
		if not code:
			continue
		out.append((code, _named(entry, language) or code))
	return sorted(out, key=lambda row: row[1])


# //// Neoffice — whitelisted for the Webshop Settings client script's canton picker.
@frappe.whitelist()
def get_subdivisions(country="CH", language="FR"):
	"""The country's regions, as the picker's option list."""
	frappe.only_for(("System Manager", "Website Manager"))
	return [{"value": code, "label": label} for code, label in subdivisions(country, language)]


def sync_holiday_list(list_name, country, subdivision, years, language="FR", weekly_off=None):
	"""Write the fetched holidays of `years` into the named Holiday List.

	The list is created when missing. A date typed by hand inside the covered years
	is kept, so a shop can add "closed the Monday after the fair" without it being
	wiped every month. One kind of row is retracted: a holiday the provider gives
	only for a place below the shop's subdivision, which an older rule wrote for the
	whole canton (#690). Such a row is recognised by its date AND its wording, and
	only when no day of the current rule sits on that date; a row typed by hand with
	other words survives. The report lists what was retracted.
	Returns a report dict; raises nothing a caller has to catch.
	"""
	years = sorted({int(y) for y in years})
	if not years:
		return {"ok": False, "reason": _("No year to fetch.")}

	fetched = {}
	below = set()
	unreachable = []
	for year in years:
		result = _fetch(country, subdivision, year, language)
		if result is None:
			unreachable.append(year)
			continue
		rows, rejected = result
		fetched.update(dict(rows))
		below.update(rejected)

	if not fetched:
		# nothing readable: leave the list exactly as it was
		return {
			"ok": False,
			"reason": _("The public holidays could not be read from the provider."),
			"unreachable": unreachable,
		}

	first, last = datetime.date(years[0], 1, 1), datetime.date(years[-1], 12, 31)

	if frappe.db.exists("Holiday List", list_name):
		doc = frappe.get_doc("Holiday List", list_name)
	else:
		doc = frappe.new_doc("Holiday List")
		doc.holiday_list_name = list_name
	doc.from_date = min(getdate(doc.from_date), first) if doc.get("from_date") else first
	doc.to_date = max(getdate(doc.to_date), last) if doc.get("to_date") else last
	if weekly_off:
		doc.weekly_off = weekly_off

	kept = []
	retracted = []
	for row in doc.get("holidays") or []:
		day = getdate(row.holiday_date)
		if day.year not in years:
			# outside what this run fetched: never touched
			kept.append((day, row.description))
		elif day in fetched:
			# a day of the current rule: written again below, with the provider's wording
			continue
		elif (day, (row.description or "").strip()) in below:
			# what an older rule wrote for a place below the shop's subdivision
			retracted.append({"date": day.isoformat(), "description": row.description})
		else:
			# typed by hand
			kept.append((day, row.description))
	merged = dict(kept)
	merged.update(fetched)

	doc.set("holidays", [])
	for day, description in sorted(merged.items()):
		doc.append("holidays", {"holiday_date": day, "description": description})
	doc.flags.ignore_permissions = True
	doc.save()

	return {
		"ok": True,
		"name": doc.name,
		"years": years,
		"fetched": len(fetched),
		"total": len(merged),
		"unreachable": unreachable,
		"retracted": retracted,
	}


def _settings():
	return frappe.get_cached_doc("Webshop Settings")


def wanted_years(from_year=None):
	"""The years the list should hold: this one, and the ones ahead."""
	start = int(from_year or getdate(today()).year)
	return list(range(start, start + YEARS_AHEAD + 1))


# //// Neoffice — whitelisted for the "Fetch public holidays" button on Webshop Settings.
@frappe.whitelist()
def refresh_store_holidays():
	"""Fetch this year's and next year's holidays into the shop's Holiday List."""
	frappe.only_for(("System Manager", "Website Manager"))
	settings = frappe.get_doc("Webshop Settings")
	country = (settings.get("store_holiday_country") or "").strip()
	subdivision = (settings.get("store_holiday_region") or "").strip()
	if not country:
		frappe.throw(_("Choose the country of the store first."))

	list_name = (settings.get("store_holiday_list") or "").strip()
	if not list_name:
		# //// Neoffice — the default name is NOT translated: it names a document, and a
		# //// name that followed the admin's session language would create a second list
		# //// the day someone opened the desk in another one.
		list_name = "Public holidays {0}".format(subdivision or country)

	report = sync_holiday_list(
		list_name, country, subdivision, wanted_years(), language=_holiday_language()
	)
	if not report.get("ok"):
		frappe.throw(report.get("reason") or _("The public holidays could not be read."))

	if settings.get("store_holiday_list") != report["name"]:
		frappe.db.set_single_value("Webshop Settings", "store_holiday_list", report["name"])
		frappe.clear_cache()
	return report


def _holiday_language():
	"""The language the holiday names are asked in: the site's, else French."""
	lang = (frappe.db.get_single_value("System Settings", "language") or "fr") or "fr"
	return lang.split("-")[0].upper()[:2] or "FR"


def top_up_holidays():
	"""Scheduled: keep the shop's Holiday List stocked for the years ahead.

	Silent by design. A provider that is down simply leaves the list alone until
	the next run; the shop keeps showing the holidays it already knows.
	"""
	settings = _settings()
	list_name = (settings.get("store_holiday_list") or "").strip()
	country = (settings.get("store_holiday_country") or "").strip()
	if not list_name or not country or not frappe.db.exists("Holiday List", list_name):
		return
	years = wanted_years()
	known = set(
		frappe.get_all(
			"Holiday",
			filters={"parent": list_name, "parenttype": "Holiday List"},
			pluck="holiday_date",
		)
	)
	missing = [y for y in years if not any(getdate(d).year == y for d in known)]
	if not missing:
		return
	sync_holiday_list(
		list_name,
		country,
		(settings.get("store_holiday_region") or "").strip(),
		missing,
		language=_holiday_language(),
	)


def holiday_closures(settings=None):
	"""[(date, label)] of the shop's public holidays, for the opening hours.

	Empty when no list is configured — the manual closures stand on their own.
	"""
	settings = settings or _settings()
	list_name = (settings.get("store_holiday_list") or "").strip()
	if not list_name:
		return []
	rows = frappe.get_all(
		"Holiday",
		filters={"parent": list_name, "parenttype": "Holiday List"},
		fields=["holiday_date", "description"],
		order_by="holiday_date asc",
	)
	return [(getdate(row.holiday_date), (row.description or "").strip()) for row in rows]
