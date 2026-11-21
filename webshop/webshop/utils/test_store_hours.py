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
		"""The footer-widget bug: 12:30 on a Friday said 'tomorrow at 10:00'."""
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


class TestABlockServedFromThePageCache(FrappeTestCase):
	"""A shop that opens at 10:00 said « Currently closed — Opens today at 10:00 » on its home page at 10:14.

	Frappe keeps a rendered page in its cache with no expiry, and the include writes the state on the
	server: the home page was served as it had been drawn before the opening. A page Builder renders loads
	no frappe script, so nothing redrew it. The block now says when it was drawn and carries its own
	script, which asks the server for the live state wherever the block is.
	"""

	def setUp(self):
		frappe.local.webshop_opening_hours_js_done = False
		self.addCleanup(setattr, frappe.local, "webshop_opening_hours_js_done", False)

	def test_the_block_says_when_it_was_drawn_and_in_which_language(self):
		import datetime as dt
		from zoneinfo import ZoneInfo

		from frappe.utils import get_system_timezone

		now = at(FRIDAY, 9, 59)
		data = store_hours.opening_hours(now, settings_like(WEEK))
		expected = int(now.replace(tzinfo=ZoneInfo(get_system_timezone())).timestamp())
		self.assertEqual(data.drawn_at, expected)
		self.assertEqual(dt.datetime.fromtimestamp(data.drawn_at, ZoneInfo(get_system_timezone())).hour, 9)
		self.assertEqual(data.lang, frappe.local.lang)

	def test_the_script_comes_once_per_request(self):
		first = store_hours.opening_hours_js()
		self.assertIn("get_opening_hours", first)
		self.assertEqual(store_hours.opening_hours_js(), "", "two blocks on a page carry it once")

	def test_the_script_needs_no_frappe(self):
		# a page Builder renders has no frappe object: frappe.call, frappe.ready and frappe.provide would throw
		script = store_hours.opening_hours_js()
		for needs_frappe in ("frappe.call", "frappe.ready", "frappe.provide"):
			self.assertNotIn(needs_frappe, script)
		self.assertNotIn("</script", script.lower(), "it is printed inside a <script> element")
		self.assertIn("_lang", script, "the live state comes back in the language of the page")
		self.assertIn("drawnAt", script, "a block drawn long ago hides its state until the live one comes")

	def test_the_include_prints_the_stamp_and_the_script_once(self):
		hours = store_hours.opening_hours(at(FRIDAY, 9, 59), settings_like(WEEK))
		html = frappe.render_template(
			"{% set hours = h %}{% include 'webshop/templates/includes/opening_hours.html' %}"
			"{% include 'webshop/templates/includes/opening_hours.html' %}",
			{"h": hours},
		)
		self.assertIn(f'data-drawn-at="{hours.drawn_at}"', html)
		self.assertIn(f'data-lang="{hours.lang}"', html)
		self.assertEqual(html.count("<script>"), 1, html[-400:])
		self.assertLess(html.index("webshop-opening-hours"), html.index("<script>"), "the block exists when its script runs")
