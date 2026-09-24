# //// Neoffice — added file (no upstream equivalent): the visits from AI assistants
# //// (seo/ai_referrals.py, report Visits From AI Assistants). #691 lot 4.
"""Which visit came from which assistant, and what the report counts of them."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.report.visits_from_ai_assistants import visits_from_ai_assistants as report
from webshop.webshop.seo.ai_referrals import assistant_of


class TestWhichAssistant(FrappeTestCase):
	def test_by_the_referrer_s_host_or_the_utm_source(self):
		cases = {
			("https://chatgpt.com/", None): "ChatGPT",
			(None, "chatgpt.com"): "ChatGPT",
			("https://www.perplexity.ai/search/abc", None): "Perplexity",
			(None, "Perplexity"): "Perplexity",
			("https://gemini.google.com/app", None): "Gemini",
			("claude.ai", None): "Claude",
			("https://copilot.microsoft.com/chats/x", None): "Copilot",
		}
		for (referrer, source), assistant in cases.items():
			with self.subTest(referrer=referrer, source=source):
				self.assertEqual(assistant_of(referrer, source), assistant)

	def test_any_other_visit_is_nobody_s(self):
		for referrer, source in (
			("https://www.google.com/", None),
			("https://notchatgpt.com/", None),
			(None, "newsletter"),
			(None, None),
		):
			with self.subTest(referrer=referrer, source=source):
				self.assertIsNone(assistant_of(referrer, source))


class TestReport(FrappeTestCase):
	VIEWS = [
		frappe._dict(creation="2026-09-20 10:00:00", path="products/a", referrer="https://chatgpt.com/", source=None, visitor_id="v1"),
		frappe._dict(creation="2026-09-20 11:00:00", path="products/a", referrer=None, source="chatgpt.com", visitor_id="v1"),
		frappe._dict(creation="2026-09-21 09:00:00", path="brands/canon", referrer="https://www.perplexity.ai/", source=None, visitor_id="v2"),
		frappe._dict(creation="2026-09-21 09:30:00", path="/", referrer="https://www.google.com/", source="google", visitor_id="v3"),
	]

	def run_report(self, group_by, tracking=1):
		with (
			patch("frappe.get_all", return_value=self.VIEWS),
			patch("frappe.db.get_single_value", return_value=tracking),
		):
			return report.execute({"from_date": "2026-09-01", "to_date": "2026-09-30", "group_by": group_by})

	def test_visits_and_visitors_by_assistant(self):
		_columns, data, message = self.run_report("Assistant")
		self.assertIsNone(message)
		self.assertEqual(
			data,
			[
				{"assistant": "ChatGPT", "visits": 2, "visitors": 1},
				{"assistant": "Perplexity", "visits": 1, "visitors": 1},
			],
		)

	def test_by_page_and_by_day(self):
		_columns, by_page, _message = self.run_report("Page")
		self.assertEqual([(row["path"], row["assistant"], row["visits"]) for row in by_page], [("products/a", "ChatGPT", 2), ("brands/canon", "Perplexity", 1)])
		_columns, by_day, _message = self.run_report("Day")
		self.assertEqual([(str(row["date"]), row["assistant"]) for row in by_day], [("2026-09-20", "ChatGPT"), ("2026-09-21", "Perplexity")])

	def test_tracking_off_is_said_not_shown_as_an_empty_table(self):
		_columns, _data, message = self.run_report("Assistant", tracking=0)
		self.assertTrue(message)
