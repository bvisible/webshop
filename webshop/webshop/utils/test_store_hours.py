# //// Neoffice — added file (store hours, no upstream equivalent).
"""The opening-hours computation, with the clock fixed by hand.

The scenarios are the ones a customer meets in a week, plus the one the widget
this replaces got wrong: closed for lunch, it announced tomorrow's opening.
"""

import datetime

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.utils import store_hours


def settings_like(rows, closures=(), note=""):
	"""What `schedule()` reads, without touching Webshop Settings."""
	return frappe._dict(
		store_hours=[frappe._dict(weekday=d, opens=o, closes=c) for d, o, c in rows],
		store_closures=[frappe._dict(from_date=f, to_date=t, label=l) for f, t, l in closures],
		store_hours_note=note,
	)


# Tuesday to Friday with a lunch break, Saturday non-stop, closed Sunday and Monday.
WEEK = [
	("Tuesday", "10:00", "12:00"),
	("Tuesday", "13:30", "18:00"),
	("Wednesday", "10:00", "12:00"),
	("Wednesday", "13:30", "19:00"),
	("Thursday", "10:00", "12:00"),
	("Thursday", "13:30", "18:00"),
	("Friday", "10:00", "12:00"),
	("Friday", "13:30", "18:00"),
	("Saturday", "10:00", "17:00"),
]
FRIDAY = datetime.date(2026, 9, 4)


def at(day, hour, minute=0):
	return datetime.datetime.combine(day, datetime.time(hour, minute))


class TestStoreHours(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.lang = frappe.local.lang
		frappe.local.lang = "en"

	@classmethod
	def tearDownClass(cls):
		frappe.local.lang = cls.lang
		super().tearDownClass()

	def test_closed_for_lunch_reopens_today_not_tomorrow(self):
		"""The blowbackshop bug: 12:30 on a Friday said 'tomorrow at 10:00'."""
		status = store_hours.status_at(at(FRIDAY, 12, 30), settings_like(WEEK))
		self.assertFalse(status.is_open)
		self.assertEqual(status.next_opening, at(FRIDAY, 13, 30))
		headline, detail = store_hours.describe(status, at(FRIDAY, 12, 30))
		self.assertEqual(headline, "Currently closed")
		self.assertEqual(detail, "Opens today at 13:30")

	def test_before_the_first_period_it_opens_today(self):
		status = store_hours.status_at(at(FRIDAY, 8, 15), settings_like(WEEK))
		self.assertEqual(status.next_opening, at(FRIDAY, 10, 0))

	def test_open_now_says_when_it_closes(self):
		now = at(FRIDAY, 15, 45)
		status = store_hours.status_at(now, settings_like(WEEK))
		self.assertTrue(status.is_open)
		self.assertEqual(status.closes_at, at(FRIDAY, 18, 0))
		headline, detail = store_hours.describe(status, now)
		self.assertEqual(headline, "Currently open")
		self.assertEqual(detail, "Closes in 2h 15min")

	def test_after_closing_it_is_tomorrow(self):
		status = store_hours.status_at(at(FRIDAY, 18, 0), settings_like(WEEK))
		self.assertFalse(status.is_open)
		self.assertEqual(status.next_opening, at(FRIDAY + datetime.timedelta(days=1), 10, 0))
		self.assertEqual(store_hours.describe(status, at(FRIDAY, 18, 0))[1], "Opens tomorrow at 10:00")

	def test_closed_days_are_skipped_to_the_next_open_one(self):
		saturday_evening = at(FRIDAY + datetime.timedelta(days=1), 17, 30)
		status = store_hours.status_at(saturday_evening, settings_like(WEEK))
		self.assertEqual(status.next_opening.date(), FRIDAY + datetime.timedelta(days=4))  # Tuesday
		self.assertEqual(store_hours.describe(status, saturday_evening)[1], "Opens Tuesday at 10:00")

	def test_a_closure_hides_the_day_and_names_itself(self):
		closures = [(FRIDAY, FRIDAY + datetime.timedelta(days=8), "Holidays")]
		now = at(FRIDAY, 11, 0)
		status = store_hours.status_at(now, settings_like(WEEK, closures))
		self.assertFalse(status.is_open)
		self.assertEqual(status.closure, "Holidays")
		# the first open day after the closure: Sunday 13 is closed, Monday too, Tuesday 15 opens
		self.assertEqual(status.next_opening, at(datetime.date(2026, 9, 15), 10, 0))
		headline, detail = store_hours.describe(status, now)
		self.assertEqual(headline, "Closed: Holidays")
		self.assertTrue(detail.startswith("Opens on"), detail)

	def test_the_week_reads_like_a_sign_in_the_window(self):
		sched = store_hours.schedule(settings_like(WEEK))
		week = store_hours.week(at(FRIDAY, 9, 0), sched)
		by_day = {d.weekday: d for d in week}
		self.assertEqual(by_day["Friday"].text, "10:00 - 12:00 / 13:30 - 18:00")
		self.assertEqual(by_day["Saturday"].text, "10:00 - 17:00 non-stop")
		self.assertEqual(by_day["Sunday"].text, "Closed")
		self.assertTrue(by_day["Friday"].is_today)
		self.assertTrue(by_day["Monday"].closed)

	def test_french_writes_the_clock_the_french_way(self):
		frappe.local.lang = "fr"
		try:
			self.assertEqual(store_hours.format_clock("13:30:00"), "13h30")
		finally:
			frappe.local.lang = "en"

	def test_nothing_configured_says_so_without_failing(self):
		data = store_hours.opening_hours(at(FRIDAY, 12, 0), settings_like([]))
		self.assertFalse(data.configured)
		self.assertEqual(data.headline, "")
		self.assertEqual(len(data.week), 7)

	def test_the_public_endpoint_answers_a_guest(self):
		frappe.set_user("Guest")
		try:
			data = store_hours.get_opening_hours()
		finally:
			frappe.set_user("Administrator")
		for key in ("configured", "week", "closures", "headline", "today_text"):
			self.assertIn(key, data)
