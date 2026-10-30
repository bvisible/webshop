# //// Neoffice — added file (shop assistant, no upstream equivalent).
"""Counting what the assistant is asked, answers and refuses (lot D of the 2026-10-30 audit).

The counters live in Redis, incremented atomically, so that a flood costs the database nothing: every request that
reaches Frappe is counted, the ones the throttle refuses before the endpoint runs included. Each night they are written
to `Shop Assistant Usage Day`, one row a day, which holds no word a visitor wrote and no address: it can be kept for as
long as the shop is billed from it.

The counters are the real Redis ones, under a day no real day will ever be (the test works on 2001-02-03).
"""

import types

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, nowdate

from webshop.webshop.assistant import usage
from webshop.webshop.report.shop_assistant_usage import shop_assistant_usage
from webshop.webshop.utils import throttle

DAY = "2001-02-03"
NEXT_DAY = "2001-02-04"


class TestUsageCounters(FrappeTestCase):
	def setUp(self):
		for day in (DAY, NEXT_DAY):
			usage.forget(day)
		frappe.db.delete("Shop Assistant Usage Day", {"day": ["in", (DAY, NEXT_DAY)]})

	def tearDown(self):
		for day in (DAY, NEXT_DAY):
			usage.forget(day)
		frappe.db.delete("Shop Assistant Usage Day", {"day": ["in", (DAY, NEXT_DAY)]})
		frappe.db.rollback()

	# --- counting ----------------------------------------------------------------------------------

	def test_a_counter_adds_up_per_day(self):
		usage.count("received", day=DAY)
		usage.count("received", day=DAY)
		usage.count("tool_calls", 3, day=DAY)
		usage.count("received", day="2001-02-04")
		try:
			self.assertEqual(usage.counters(DAY), {"received": 2, "tool_calls": 3})
			self.assertEqual(usage.counters("2001-02-04"), {"received": 1})
		finally:
			usage.forget("2001-02-04")

	def test_a_counter_that_cannot_be_written_never_costs_a_visitor_their_answer(self):
		"""Counting is for the shop's eyes: Redis hiccuping while a visitor is being answered must not turn into an error."""
		import redis

		real = redis.Redis.hincrby

		def down(*args, **kwargs):
			raise redis.ConnectionError("redis is gone")

		redis.Redis.hincrby = down
		try:
			self.assertIsNone(usage.count("received", day=DAY))
			self.assertIsNone(usage.refused("rate", day=DAY))
			self.assertIsNone(usage.record_turn(1, 0, 10, 2, 300, day=DAY))
		finally:
			redis.Redis.hincrby = real

	def test_a_day_nobody_wrote_to_has_no_counters(self):
		self.assertEqual(usage.counters(DAY), {})

	def test_a_refusal_is_counted_under_its_reason_and_as_a_request(self):
		usage.refused("day_limit", day=DAY)
		self.assertEqual(usage.counters(DAY), {"received": 1, "refused_day_limit": 1})

	def test_only_the_reasons_the_report_knows_are_counted(self):
		with self.assertRaises(ValueError):
			usage.refused("because i said so", day=DAY)

	def test_the_turn_of_an_answer_adds_its_calls_tokens_and_duration(self):
		usage.record_turn(model_calls=2, tool_calls=1, prompt_tokens=900, completion_tokens=40, duration_ms=3400, day=DAY)
		usage.record_turn(model_calls=1, tool_calls=0, prompt_tokens=500, completion_tokens=20, duration_ms=800, day=DAY)
		seen = usage.counters(DAY)
		self.assertEqual(
			(seen["model_calls"], seen["tool_calls"], seen["prompt_tokens"], seen["completion_tokens"]), (3, 1, 1400, 60)
		)
		self.assertEqual(seen["answered"], 2)

	# --- how long answers take ---------------------------------------------------------------------

	def test_the_median_and_the_95th_percentile_come_from_the_buckets(self):
		for milliseconds in [400] * 10 + [900] * 5 + [2500] * 4 + [25000]:
			usage.record_turn(model_calls=1, tool_calls=0, prompt_tokens=1, completion_tokens=1, duration_ms=milliseconds, day=DAY)
		median, p95 = usage.percentiles(usage.counters(DAY))
		self.assertEqual(median, 500)  # the bucket that holds the 10th of 20 answers
		self.assertEqual(p95, 3000)  # the bucket that holds the 19th of 20: one slow answer in twenty is not the 95th percentile
		self.assertEqual(usage.percentiles({}), (0, 0))

	def test_a_slow_tail_shows_in_the_95th_percentile(self):
		for milliseconds in [400] * 10 + [25000] * 10:
			usage.record_turn(model_calls=1, tool_calls=0, prompt_tokens=1, completion_tokens=1, duration_ms=milliseconds, day=DAY)
		self.assertEqual(usage.percentiles(usage.counters(DAY)), (500, 30000))

	def test_an_answer_slower_than_the_last_bucket_is_counted_in_it(self):
		usage.record_turn(model_calls=1, tool_calls=0, prompt_tokens=1, completion_tokens=1, duration_ms=900000, day=DAY)
		self.assertEqual(usage.percentiles(usage.counters(DAY))[1], usage.DURATION_BUCKETS[-1])

	# --- the night's write -------------------------------------------------------------------------

	def test_the_night_writes_one_row_and_empties_the_counters(self):
		usage.count("received", 5, day=DAY)
		usage.refused("rate", day=DAY)
		usage.record_turn(model_calls=1, tool_calls=2, prompt_tokens=700, completion_tokens=30, duration_ms=1200, day=DAY)
		name = usage.flush(DAY)
		row = frappe.get_doc("Shop Assistant Usage Day", name)
		self.assertEqual(str(row.day), DAY)
		self.assertEqual((row.received, row.answered, row.refused_rate), (6, 1, 1))  # 5 counted, plus the refusal
		self.assertEqual((row.model_calls, row.tool_calls, row.prompt_tokens, row.completion_tokens), (1, 2, 700, 30))
		self.assertEqual(row.median_ms, 2000)
		self.assertEqual(usage.counters(DAY), {})

	def test_a_late_request_of_a_day_already_written_is_added_to_its_row(self):
		usage.count("received", 2, day=DAY)
		first = usage.flush(DAY)
		usage.count("received", 3, day=DAY)
		second = usage.flush(DAY)
		self.assertEqual(first, second)
		self.assertEqual(frappe.db.get_value("Shop Assistant Usage Day", first, "received"), 5)

	def test_a_write_that_fails_loses_nothing(self):
		"""The night's write is billing: counters taken out of Redis must survive a row that could not be saved."""
		usage.count("received", 5, day=DAY)
		real = frappe.new_doc
		frappe.new_doc = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("the database said no"))
		try:
			with self.assertRaises(RuntimeError):
				usage.flush(DAY)
		finally:
			frappe.new_doc = real
		usage.count("received", 2, day=DAY)  # counted after the failed attempt
		name = usage.flush(DAY)
		self.assertEqual(frappe.db.get_value("Shop Assistant Usage Day", name, "received"), 7)
		self.assertEqual(usage.counters(DAY), {})

	def test_a_day_written_twice_has_the_percentiles_of_everything_counted(self):
		for _ in range(10):
			usage.record_turn(model_calls=1, tool_calls=0, prompt_tokens=1, completion_tokens=1, duration_ms=400, day=DAY)
		usage.flush(DAY)
		for _ in range(10):
			usage.record_turn(model_calls=1, tool_calls=0, prompt_tokens=1, completion_tokens=1, duration_ms=25000, day=DAY)
		row = frappe.get_doc("Shop Assistant Usage Day", usage.flush(DAY))
		self.assertEqual((row.answered, row.median_ms, row.p95_ms), (20, 500, 30000))

	def test_the_hourly_job_writes_today_so_far_so_that_a_clear_cache_costs_at_most_an_hour(self):
		"""`bench clear-cache` empties the Redis counters (measured on osiris: a day's figures, the outage flag, the rate windows).
		Each deployment runs it, so the day's figures cannot wait for the night to be written."""
		today = nowdate()
		before = usage.counters(today)
		usage.forget(today)
		try:
			usage.count("received", 3, day=today)
			usage.count("received", 2, day=today)
			name = usage.hourly()
			self.assertEqual(frappe.db.get_value("Shop Assistant Usage Day", name, "received"), 5)
			self.assertEqual(usage.counters(today), {}, "today's counters are in the row now")
			usage.count("received", 4, day=today)
			self.assertEqual(usage.totals(today, today)["received"], 9, "the written part and the part still counting")
		finally:
			usage.forget(today)
			for field, number in before.items():
				usage.count(field, number, day=today)

	def test_nothing_is_written_for_a_day_without_requests(self):
		self.assertIsNone(usage.flush(DAY))
		self.assertFalse(frappe.db.exists("Shop Assistant Usage Day", {"day": DAY}))

	def test_the_nightly_job_writes_the_finished_days_and_leaves_today_counting(self):
		yesterday = str(add_days(getdate(nowdate()), -1))
		before = frappe.db.get_value("Shop Assistant Usage Day", {"day": yesterday}, "name")
		try:
			usage.count("received", 4, day=yesterday)
			usage.count("received", 6, day=nowdate())
			written = usage.flush_finished_days()
			self.assertIn(yesterday, [str(day) for day in written])
			self.assertEqual(usage.counters(nowdate())["received"], 6, "today is still being counted")
			self.assertEqual(usage.counters(yesterday), {})
		finally:
			usage.forget(nowdate())
			if not before:
				frappe.db.delete("Shop Assistant Usage Day", {"day": yesterday})

	# --- what the settings tab and the report show --------------------------------------------------

	def test_totals_add_the_days_already_written_and_the_days_still_counting(self):
		usage.count("received", 4, day=DAY)
		usage.refused("rate", day=DAY)
		usage.flush(DAY)
		usage.count("received", 2, day=NEXT_DAY)
		usage.declined("busy", day=NEXT_DAY)
		total = usage.totals(DAY, NEXT_DAY)
		self.assertEqual(total["received"], 4 + 1 + 2)
		self.assertEqual((total["refused_rate"], total["refused_busy"]), (1, 1))
		self.assertEqual(total["refused"], 2)
		self.assertEqual(total["answered"], 0)

	def test_totals_of_a_period_nobody_wrote_in_are_zeros(self):
		total = usage.totals(DAY, NEXT_DAY)
		self.assertEqual((total["received"], total["refused"], total["answered"]), (0, 0, 0))

	def test_the_report_shows_a_day_nobody_was_answered_and_the_requests_of_every_day(self):
		usage.count("received", 9, day=DAY)
		usage.refused("rate", day=DAY)
		usage.flush(DAY)
		columns, rows = shop_assistant_usage.execute({"from_date": DAY, "to_date": DAY})
		self.assertIn("requests", [c["fieldname"] for c in columns])
		self.assertIn("refused", [c["fieldname"] for c in columns])
		(row,) = [r for r in rows if str(r["grouping"]) == DAY]
		self.assertEqual((row["requests"], row["refused"], row["conversations"]), (10, 1, 0))

	def test_the_row_holds_no_word_and_no_address(self):
		"""Nothing a visitor wrote, nothing that names a visitor: the row can be kept as long as the shop is billed from it."""
		fields = [f.fieldname for f in frappe.get_meta("Shop Assistant Usage Day").fields if f.fieldtype not in ("Int", "Date", "Section Break", "Column Break")]
		self.assertEqual(fields, [])


class TestTheThrottleCountsItsRefusals(FrappeTestCase):
	"""The throttle runs before the endpoint: a refusal it makes is invisible unless it counts itself."""

	def setUp(self):
		self.real_header = frappe.get_request_header
		self.real_request = getattr(frappe.local, "request", None)
		self.name = "_wstest-usage-" + frappe.generate_hash(length=8)
		self.day = nowdate()
		self.before = usage.counters(self.day)

	def tearDown(self):
		frappe.get_request_header = self.real_header
		frappe.local.request = self.real_request
		throttle.reset(self.name, "10.0.0.9")
		# put today's counters back to what they were
		usage.forget(self.day)
		for field, number in self.before.items():
			usage.count(field, number, day=self.day)

	def test_a_call_refused_by_the_limit_is_counted_as_a_request_and_a_refusal(self):
		frappe.local.request = types.SimpleNamespace(method="POST")
		frappe.get_request_header = lambda key, default=None: "10.0.0.9" if key == "X-Forwarded-For" else default

		@throttle.throttle(self.name, 2, 30, on_refuse=lambda: usage.refused("rate"))
		def endpoint():
			return "ok"

		answers = []
		for _ in range(5):
			try:
				answers.append(endpoint())
			except frappe.RateLimitExceededError:
				answers.append("429")
		self.assertEqual(answers, ["ok", "ok", "429", "429", "429"])
		seen = usage.counters(self.day)
		self.assertEqual(seen.get("refused_rate", 0) - self.before.get("refused_rate", 0), 3)
		self.assertEqual(seen.get("received", 0) - self.before.get("received", 0), 3)
