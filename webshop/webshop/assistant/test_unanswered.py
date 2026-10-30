# //// Neoffice — added file (shop assistant, no upstream equivalent).
"""The questions the shop assistant left without an answer (lot D of the 2026-10-30 audit).

What a shop's own knowledge and catalogue lack shows in what visitors asked and went unanswered: the assistant said it did not
know, the visitor was handed to the team, said the answer did not help, or reported it. The report lists those questions, the
ones asked most first, and a weekly mail (off until the merchant switches it on) sends the same list to the team.

The conversations are real documents written for the test and removed with it.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, now_datetime, nowdate

from webshop.webshop.assistant import unanswered
from webshop.webshop.report.shop_assistant_unanswered_questions import shop_assistant_unanswered_questions as report

GUEST = "_wstest-unanswered-guest"


def talk(*turns, status="Open"):
	"""A conversation of `(question, answer, answer_fields)` turns; returns it."""
	doc = frappe.get_doc({"doctype": "Shop Assistant Conversation", "guest_session": GUEST, "status": status})
	for question, answer, fields in turns:
		doc.add_message("user", question)
		doc.add_message("assistant", answer, **fields)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc


class TestUnansweredQuestions(FrappeTestCase):
	def setUp(self):
		self.purge()

	def tearDown(self):
		self.purge()

	@staticmethod
	def purge():
		for name in frappe.get_all("Shop Assistant Conversation", filters={"guest_session": GUEST}, pluck="name"):
			frappe.delete_doc("Shop Assistant Conversation", name, force=True, ignore_permissions=True)

	def asked(self):
		return {row["question"]: row for row in unanswered.find(add_days(nowdate(), -1), add_days(nowdate(), 1))}

	def test_a_question_the_assistant_could_not_answer_is_listed_with_why(self):
		talk(("Livrez-vous en Islande ?", "Je ne sais pas.", {"signals": ",unanswered,"}))
		row = self.asked()["Livrez-vous en Islande ?"]
		self.assertEqual((row["count"], row["why"]), (1, "No answer"))

	def test_every_way_a_question_goes_unanswered_is_named(self):
		talk(
			("Une question sans réponse", "Je ne sais pas.", {"signals": ",unanswered,"}),
			("Une demande transmise", "J'ai prévenu l'équipe.", {"signals": ",escalated,"}),
			("Une réponse qui n'a pas aidé", "Voici.", {"feedback": "Not useful"}),
			("Une réponse signalée", "Voici.", {"reported": 1}),
		)
		why = {question: row["why"] for question, row in self.asked().items()}
		self.assertEqual(why["Une question sans réponse"], "No answer")
		self.assertEqual(why["Une demande transmise"], "Handed to the team")
		self.assertEqual(why["Une réponse qui n'a pas aidé"], "Marked not useful")
		self.assertEqual(why["Une réponse signalée"], "Reported")

	def test_an_answer_that_helped_and_a_refusal_of_another_subject_are_not_listed(self):
		talk(
			("Quels sont vos horaires ?", "De 9 h à 18 h.", {}),
			("Une recette de tarte ?", "Ce n'est pas mon domaine.", {"signals": ",off_topic_refused,"}),
			("Merci, c'est utile", "Avec plaisir.", {"feedback": "Useful"}),
		)
		self.assertEqual(self.asked(), {})

	def test_the_same_question_asked_again_is_one_line_with_its_count_and_the_most_asked_come_first(self):
		for text in ("Livrez-vous en Islande ?", "livrez-vous en islande", "Livrez-vous en Islande ??"):
			talk((text, "Je ne sais pas.", {"signals": ",unanswered,"}))
		talk(("Autre chose ?", "Je ne sais pas.", {"signals": ",unanswered,"}))
		rows = unanswered.find(add_days(nowdate(), -1), add_days(nowdate(), 1))
		self.assertEqual([row["count"] for row in rows], [3, 1])
		self.assertEqual(rows[0]["question"], "Livrez-vous en Islande ?")

	def test_the_question_is_the_one_the_answer_followed_not_another_of_the_thread(self):
		talk(
			("Bonjour", "Bonjour !", {}),
			("Livrez-vous en Islande ?", "Je ne sais pas.", {"signals": ",unanswered,"}),
			("Et les horaires ?", "De 9 h à 18 h.", {}),
		)
		self.assertEqual(list(self.asked()), ["Livrez-vous en Islande ?"])

	def test_the_period_bounds_the_list(self):
		doc = talk(("Livrez-vous en Islande ?", "Je ne sais pas.", {"signals": ",unanswered,"}))
		old = add_days(now_datetime(), -30)
		frappe.db.sql("update `tabShop Assistant Message` set sent_on = %s where parent = %s", (old, doc.name))
		self.assertEqual(self.asked(), {})
		self.assertEqual(len(unanswered.find(add_days(nowdate(), -40), add_days(nowdate(), -20))), 1)

	# --- the report ---------------------------------------------------------------------------------

	def test_the_report_lists_them_with_their_columns(self):
		talk(("Livrez-vous en Islande ?", "Je ne sais pas.", {"signals": ",unanswered,"}))
		columns, rows = report.execute({"from_date": add_days(nowdate(), -1), "to_date": add_days(nowdate(), 1)})
		self.assertEqual([c["fieldname"] for c in columns], ["question", "count", "why", "last_asked", "conversation"])
		(row,) = rows
		self.assertEqual((row["question"], row["count"]), ("Livrez-vous en Islande ?", 1))

	def test_the_report_defaults_to_the_last_week(self):
		_, rows = report.execute({})
		self.assertIsInstance(rows, list)

	# --- the weekly mail ----------------------------------------------------------------------------

	def test_the_weekly_mail_is_off_until_the_merchant_switches_it_on(self):
		talk(("Livrez-vous en Islande ?", "Je ne sais pas.", {"signals": ",unanswered,"}))
		sent = []
		settings = frappe._dict(assistant_weekly_digest=0, store_email="boutique@example.com")
		self.assertIsNone(unanswered.send_weekly_digest(settings=settings, send=lambda **kw: sent.append(kw)))
		self.assertEqual(sent, [])

	def test_the_weekly_mail_names_the_questions_and_goes_to_the_team(self):
		talk(("Livrez-vous en Islande ?", "Je ne sais pas.", {"signals": ",unanswered,"}))
		sent = []
		settings = frappe._dict(assistant_weekly_digest=1, store_email="boutique@example.com", assistant_support_email="")
		unanswered.send_weekly_digest(settings=settings, send=lambda **kw: sent.append(kw))
		(mail,) = sent
		self.assertEqual(mail["recipients"], ["boutique@example.com"])
		self.assertIn("Livrez-vous en Islande ?", mail["message"])
		self.assertIn("No answer", mail["message"])

	def test_the_weekly_mail_escapes_what_visitors_wrote(self):
		talk(('<script>alert(1)</script> Livrez-vous ?', "Je ne sais pas.", {"signals": ",unanswered,"}))
		sent = []
		settings = frappe._dict(assistant_weekly_digest=1, store_email="boutique@example.com", assistant_support_email="")
		unanswered.send_weekly_digest(settings=settings, send=lambda **kw: sent.append(kw))
		self.assertNotIn("<script>", sent[0]["message"])

	def test_no_mail_when_the_week_had_no_unanswered_question(self):
		talk(("Quels sont vos horaires ?", "De 9 h à 18 h.", {}))
		sent = []
		settings = frappe._dict(assistant_weekly_digest=1, store_email="boutique@example.com", assistant_support_email="")
		unanswered.send_weekly_digest(settings=settings, send=lambda **kw: sent.append(kw))
		self.assertEqual(sent, [])

	def test_no_mail_without_an_address_to_send_it_to(self):
		talk(("Livrez-vous en Islande ?", "Je ne sais pas.", {"signals": ",unanswered,"}))
		from webshop.webshop.assistant import escalation

		sent = []
		settings = frappe._dict(assistant_weekly_digest=1, store_email="", assistant_support_email="")
		real = escalation._support_email
		escalation._support_email = lambda _settings: None  # a site whose Website Settings carries an address would use it
		try:
			unanswered.send_weekly_digest(settings=settings, send=lambda **kw: sent.append(kw))
		finally:
			escalation._support_email = real
		self.assertEqual(sent, [])
