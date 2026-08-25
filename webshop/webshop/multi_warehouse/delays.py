# //// Neoffice — added file (no upstream equivalent). Delivery estimation for
# //// the multi-warehouse feature. Two modes per source: Fixed (constant number
# //// of business days) and Periodic (supplier orders leave on a schedule —
# //// end of month, weekly, fixed day — then goods travel, then handling).
# //// Business days are Monday-Friday; holiday calendars are a later phase.

import calendar
from datetime import timedelta

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


def add_business_days(start_date, days):
	"""Return start_date advanced by `days` business days (Mon-Fri).

	A start on a weekend first rolls forward to Monday, so that
	add_business_days(saturday, 0) == monday.
	"""
	date = getdate(start_date)
	days = cint(days)

	while date.weekday() >= 5:
		date += timedelta(days=1)

	while days > 0:
		date += timedelta(days=1)
		if date.weekday() < 5:
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
