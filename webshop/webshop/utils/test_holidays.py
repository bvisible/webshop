# //// Neoffice — added file (public holidays for the store hours, no upstream equivalent).
"""The public holidays, with the provider replaced by a fixture.

Nothing here goes to the network: `_get` is stubbed, so the tests state what the
module must do with an answer rather than what openholidaysapi.org happens to
return today. The one shape worth pinning is the Swiss one, because it is why the
feature exists: Valais closes on Saint Joseph's day and Geneva does not, so a
holiday has to be filtered by canton and not merely by country.

The other rule under test is what happens when the provider is down: the list is
left exactly as it was. An outage that silently emptied a Holiday List would open
the shop on Christmas Day.
"""

import datetime

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.utils import holidays, store_hours

LIST_NAME = "_WSTEST Public holidays"

# Two nationwide days, one Valais-only, one named through a district of Valais,
# one that belongs to another canton, and one spanning two days.
ANSWER = [
	{
		"startDate": "2026-01-01",
		"nationwide": True,
		"name": [{"language": "FR", "text": "Nouvel an"}, {"language": "DE", "text": "Neujahr"}],
	},
	{
		"startDate": "2026-08-01",
		"nationwide": True,
		"name": [{"language": "FR", "text": "Fête nationale suisse"}],
	},
	{
		"startDate": "2026-03-19",
		"nationwide": False,
		"subdivisions": [{"code": "CH-VS"}, {"code": "CH-SZ"}],
		"name": [{"language": "FR", "text": "Saint-Joseph"}],
	},
	{
		"startDate": "2026-11-01",
		"nationwide": False,
		"subdivisions": [{"code": "CH-VS-SIERRE"}],
		"name": [{"language": "FR", "text": "Toussaint"}],
	},
	{
		"startDate": "2026-09-11",
		"nationwide": False,
		"subdivisions": [{"code": "CH-GE"}],
		"name": [{"language": "FR", "text": "Jeûne genevois"}],
	},
	{
		"startDate": "2026-12-24",
		"endDate": "2026-12-25",
		"nationwide": True,
		"name": [{"language": "FR", "text": "Noël"}],
	},
]


class TestHolidays(FrappeTestCase):
	def setUp(self):
		self.real_get = holidays._get
		self.purge()

	def tearDown(self):
		holidays._get = self.real_get
		self.purge()

	def purge(self):
		frappe.set_user("Administrator")
		if frappe.db.exists("Holiday List", LIST_NAME):
			frappe.delete_doc("Holiday List", LIST_NAME, force=True, ignore_permissions=True)
		frappe.db.commit()

	def answer_with(self, payload):
		holidays._get = lambda url, params: payload

	# --- which days belong to this shop -------------------------------------------

	def test_a_canton_gets_the_national_days_and_its_own(self):
		self.answer_with(ANSWER)
		found = dict(holidays.fetch_holidays("CH", "CH-VS", 2026, "FR"))
		self.assertIn(datetime.date(2026, 1, 1), found)  # nationwide
		self.assertIn(datetime.date(2026, 3, 19), found)  # Valais
		self.assertEqual(found[datetime.date(2026, 3, 19)], "Saint-Joseph")
		# a district of the canton counts as the canton
		self.assertIn(datetime.date(2026, 11, 1), found)
		# another canton's day does not
		self.assertNotIn(datetime.date(2026, 9, 11), found)

	def test_another_canton_gets_a_different_week(self):
		self.answer_with(ANSWER)
		valais = dict(holidays.fetch_holidays("CH", "CH-VS", 2026, "FR"))
		geneva = dict(holidays.fetch_holidays("CH", "CH-GE", 2026, "FR"))
		self.assertIn(datetime.date(2026, 9, 11), geneva)
		self.assertNotIn(datetime.date(2026, 3, 19), geneva)
		self.assertNotEqual(sorted(valais), sorted(geneva))

	def test_without_a_canton_only_the_national_days_are_kept(self):
		self.answer_with(ANSWER)
		found = dict(holidays.fetch_holidays("CH", "", 2026, "FR"))
		self.assertEqual(
			sorted(found),
			[datetime.date(2026, 1, 1), datetime.date(2026, 8, 1), datetime.date(2026, 12, 24), datetime.date(2026, 12, 25)],
		)

	def test_a_holiday_over_two_days_is_written_day_by_day(self):
		self.answer_with(ANSWER)
		found = dict(holidays.fetch_holidays("CH", "CH-VS", 2026, "FR"))
		self.assertEqual(found[datetime.date(2026, 12, 24)], "Noël")
		self.assertEqual(found[datetime.date(2026, 12, 25)], "Noël")

	def test_the_name_comes_in_the_language_asked_for(self):
		self.answer_with(ANSWER)
		fr = dict(holidays.fetch_holidays("CH", "", 2026, "FR"))
		de = dict(holidays.fetch_holidays("CH", "", 2026, "DE"))
		self.assertEqual(fr[datetime.date(2026, 1, 1)], "Nouvel an")
		self.assertEqual(de[datetime.date(2026, 1, 1)], "Neujahr")
		# a day the provider does not translate falls back rather than coming back empty
		self.assertTrue(de[datetime.date(2026, 8, 1)])

	# --- what an outage must never do ----------------------------------------------

	def test_an_unreachable_provider_returns_none_not_an_empty_year(self):
		holidays._get = lambda url, params: None
		self.assertIsNone(holidays.fetch_holidays("CH", "CH-VS", 2026, "FR"))

	def test_an_outage_leaves_the_list_exactly_as_it_was(self):
		self.answer_with(ANSWER)
		holidays.sync_holiday_list(LIST_NAME, "CH", "CH-VS", [2026])
		before = self._dates()
		self.assertTrue(before)

		holidays._get = lambda url, params: None
		report = holidays.sync_holiday_list(LIST_NAME, "CH", "CH-VS", [2026])
		self.assertFalse(report["ok"])
		self.assertEqual(self._dates(), before)

	# --- the Holiday List ------------------------------------------------------------

	def test_the_list_is_created_and_holds_the_fetched_days(self):
		self.answer_with(ANSWER)
		report = holidays.sync_holiday_list(LIST_NAME, "CH", "CH-VS", [2026])
		self.assertTrue(report["ok"])
		self.assertTrue(frappe.db.exists("Holiday List", LIST_NAME))
		self.assertIn(datetime.date(2026, 3, 19), self._dates())

	def test_a_day_typed_by_hand_survives_the_next_fetch(self):
		self.answer_with(ANSWER)
		holidays.sync_holiday_list(LIST_NAME, "CH", "CH-VS", [2026])
		doc = frappe.get_doc("Holiday List", LIST_NAME)
		doc.append("holidays", {"holiday_date": datetime.date(2026, 6, 15), "description": "Fermeture annuelle"})
		doc.flags.ignore_permissions = True
		doc.save()
		frappe.db.commit()

		holidays.sync_holiday_list(LIST_NAME, "CH", "CH-VS", [2026])
		dates = self._dates()
		self.assertIn(datetime.date(2026, 6, 15), dates, "a hand-typed closure was wiped by the fetch")
		self.assertIn(datetime.date(2026, 3, 19), dates)

	def _dates(self):
		if not frappe.db.exists("Holiday List", LIST_NAME):
			return set()
		return {
			frappe.utils.getdate(row.holiday_date)
			for row in frappe.get_doc("Holiday List", LIST_NAME).get("holidays") or []
		}

	# --- and what the opening hours make of it ---------------------------------------

	def test_the_shop_closes_on_a_public_holiday(self):
		self.answer_with(ANSWER)
		holidays.sync_holiday_list(LIST_NAME, "CH", "CH-VS", [2026])
		settings = frappe._dict(
			store_hours=[frappe._dict(weekday="Thursday", opens="10:00", closes="18:00")],
			store_closures=[],
			store_hours_note="",
			store_holiday_list=LIST_NAME,
		)
		sched = store_hours.schedule(settings)
		# 19 March 2026 is a Thursday: open by the weekly rows, closed by the holiday
		self.assertEqual(store_hours.periods_on(datetime.date(2026, 3, 19), sched), [])
		self.assertEqual(store_hours.closure_for(datetime.date(2026, 3, 19), sched), "Saint-Joseph")
		# and an ordinary Thursday still opens
		self.assertTrue(store_hours.periods_on(datetime.date(2026, 3, 26), sched))

	def test_a_closure_typed_by_hand_keeps_its_own_wording(self):
		"""Both cover the day; the one the shop wrote is the one the page shows."""
		self.answer_with(ANSWER)
		holidays.sync_holiday_list(LIST_NAME, "CH", "CH-VS", [2026])
		settings = frappe._dict(
			store_hours=[frappe._dict(weekday="Thursday", opens="10:00", closes="18:00")],
			store_closures=[
				frappe._dict(from_date="2026-03-19", to_date="2026-03-19", label="Vacances de printemps")
			],
			store_hours_note="",
			store_holiday_list=LIST_NAME,
		)
		sched = store_hours.schedule(settings)
		self.assertEqual(
			store_hours.closure_for(datetime.date(2026, 3, 19), sched), "Vacances de printemps"
		)

	def test_no_list_configured_changes_nothing(self):
		settings = frappe._dict(
			store_hours=[frappe._dict(weekday="Thursday", opens="10:00", closes="18:00")],
			store_closures=[],
			store_hours_note="",
		)
		sched = store_hours.schedule(settings)
		self.assertEqual(sched.closures, [])
		self.assertTrue(store_hours.periods_on(datetime.date(2026, 3, 19), sched))
