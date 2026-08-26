# //// Neoffice — added file (no upstream equivalent). Delivery estimation for
# //// the multi-warehouse feature. Two modes per source: Fixed (constant number
# //// of business days) and Periodic (supplier orders leave on a schedule —
# //// end of month, weekly, fixed day — then goods travel, then handling).
# //// Business days are Monday-Friday; holiday calendars are a later phase.

import calendar
from datetime import timedelta

import frappe
from frappe.utils import cint, getdate, nowdate

WEEKDAYS = [
	"Monday",
	"Tuesday",
	"Wednesday",
	"Thursday",
	"Friday",
	"Saturday",
	"Sunday",
]


def get_holidays():
	"""Dates of the Holiday List configured in Webshop Settings, as a set.

	Cached per request: a single estimate walks several days, and a product
	page renders one estimate per source.
	"""
	if getattr(frappe.local, "webshop_delivery_holidays", None) is not None:
		return frappe.local.webshop_delivery_holidays

	holidays = set()
	try:
		holiday_list = frappe.db.get_single_value(
			"Webshop Settings", "delivery_holiday_list"
		)
		if holiday_list:
			holidays = {
				getdate(d)
				for d in frappe.get_all(
					"Holiday",
					filters={"parent": holiday_list},
					pluck="holiday_date",
				)
			}
	except Exception:
		# A missing field (pre-migration) or list must never break an estimate.
		holidays = set()

	frappe.local.webshop_delivery_holidays = holidays
	return holidays


def is_business_day(date, holidays=None):
	if date.weekday() >= 5:
		return False
	holidays = get_holidays() if holidays is None else holidays
	return date not in holidays


def add_business_days(start_date, days):
	"""Return start_date advanced by `days` business days.

	Business day = Mon-Fri minus the Webshop Settings holiday list. A start on
	a non-business day first rolls forward, so add_business_days(saturday, 0)
	is the next working day.
	"""
	date = getdate(start_date)
	days = cint(days)
	holidays = get_holidays()

	# Guard against a holiday list covering every day (misconfiguration).
	guard = 0
	while not is_business_day(date, holidays) and guard < 366:
		date += timedelta(days=1)
		guard += 1

	guard = 0
	while days > 0 and guard < 3660:
		date += timedelta(days=1)
		guard += 1
		if is_business_day(date, holidays):
			days -= 1

	return date


def next_order_departure(source_row, from_date=None):
	"""Next date a periodic supplier order leaves, on or after from_date."""
	date = getdate(from_date or nowdate())
	order_day = source_row.get("order_day") or "End of Month"

	if order_day == "End of Month":
		return date.replace(day=calendar.monthrange(date.year, date.month)[1])

	if order_day == "Weekly":
		weekday = source_row.get("order_weekday") or "Monday"
		try:
			target = WEEKDAYS.index(weekday)
		except ValueError:
			target = 0
		delta = (target - date.weekday()) % 7
		return date + timedelta(days=delta)

	# Day of Month (clamped to 1-28 so it exists in every month)
	day = min(max(cint(source_row.get("order_day_of_month")) or 1, 1), 28)
	if date.day <= day:
		return date.replace(day=day)
	if date.month == 12:
		return date.replace(year=date.year + 1, month=1, day=day)
	return date.replace(month=date.month + 1, day=day)


def expected_receipt_date(source_row, from_date=None):
	"""Estimated date the goods arrive at the shop (no handling included).

	Used as schedule_date on generated Purchase Order / Material Request lines.
	"""
	from_date = getdate(from_date or nowdate())

	if source_row.get("lead_time_mode") == "Periodic":
		departure = next_order_departure(source_row, from_date)
		return add_business_days(departure, cint(source_row.get("receipt_lead_days")))

	return add_business_days(from_date, cint(source_row.get("lead_time_days")))


def estimate_delivery_date(source_row, from_date=None):
	"""Estimated delivery date promised to the shopper for this source."""
	from_date = getdate(from_date or nowdate())

	if source_row.get("lead_time_mode") == "Periodic":
		receipt = expected_receipt_date(source_row, from_date)
		return add_business_days(receipt, cint(source_row.get("handling_days")))

	return add_business_days(from_date, cint(source_row.get("lead_time_days")))


def estimate_lead_days(source_row, from_date=None):
	"""Calendar days between now and the estimated delivery (for display)."""
	from_date = getdate(from_date or nowdate())
	return (estimate_delivery_date(source_row, from_date) - from_date).days
