# //// Neoffice — added file (shop assistant, no upstream equivalent).
"""Anonymised samples of conversations, for improving the service later (lot E of the 2026-10-30 audit).

Nothing is collected until the merchant switches it on, and switching it on is a decision with a legal side (the visitor is told,
the merchant's contract allows it: nLPD, and the RGPD for European customers, to be validated by a person before the switch,
this is not legal advice). What the pipeline does once it is on is checked here:

- it starts from visitors who are not signed in, and from answers a visitor rated (useful, not useful): the pairs a person
  has already judged;
- it keeps neither the conversation, nor the visitor, nor the source of the message, only the day;
- it removes what names a person from the words themselves, and drops a sample that still looks like it holds one;
- it keeps them for a time of their own, shorter than nothing and longer than the conversations' ninety days.

The conversations and samples are real documents written for the test and removed with it.
"""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, nowdate

from webshop.webshop.assistant import anonymise, api, samples

GUEST = "_wstest-samples-guest"
SIGNED_IN = "wstest-samples@example.com"


def conversation(question, answer, feedback="Useful", status="Open", user=None, guest=GUEST, language="fr", **answer_fields):
	doc = frappe.get_doc(
		{"doctype": "Shop Assistant Conversation", "guest_session": None if user else guest, "user": user, "status": status}
	)
	doc.add_message("user", question, language=language)
	doc.add_message("assistant", answer, feedback=feedback, prompt_version="abc123def0", **answer_fields)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc


class TestAnonymise(FrappeTestCase):
	def test_what_names_a_person_is_replaced_by_what_it_was(self):
		cases = {
			"Écrivez-moi à jean.dupont@example.com merci": "Écrivez-moi à [email] merci",
			"Mon numéro : 079 123 45 67": "Mon numéro : [phone]",
			"Appelez le +41 79 123 45 67 svp": "Appelez le [phone] svp",
			"Joignable au 027 123 45 67.": "Joignable au [phone].",
			"Ma commande BC-2026-00012 n'est pas arrivée": "Ma commande [document] n'est pas arrivée",
			"La facture FAC-2026-004512 est fausse": "La facture [document] est fausse",
			"IBAN CH93 0076 2011 6238 5295 7 merci": "IBAN [iban] merci",
			"Ma carte 4111 1111 1111 1111": "Ma carte [number]",
			"Je m'appelle Jean Dupont et je cherche une poêle": "Je m'appelle [name] et je cherche une poêle",
			"My name is Alice Martin, do you ship?": "My name is [name], do you ship?",
			"Ich heiße Anna Keller und suche eine Pfanne": "Ich heiße [name] und suche eine Pfanne",
			"Mi chiamo Luca Rossi, avete una padella?": "Mi chiamo [name], avete una padella?",
		}
		for text, expected in cases.items():
			with self.subTest(text):
				self.assertEqual(anonymise.clean(text), expected)

	def test_names_the_conversation_knows_are_replaced_wherever_they_appear(self):
		text = "Bonjour, c'est Jean. Dupont a commandé hier, pouvez-vous dire à jean dupont que ça arrive ?"
		cleaned = anonymise.clean(text, names=("Jean Dupont",))
		self.assertNotIn("Dupont", cleaned)
		self.assertNotIn("dupont", cleaned.lower())
		self.assertNotIn("Jean", cleaned)

	def test_a_product_a_price_an_hour_and_a_page_are_left_alone(self):
		for text in (
			"Je cherche une imprimante laser Brother HL-L2350DW à moins de 200 francs",
			"Vous êtes ouverts à 9 h 30 le samedi ?",
			"Voir /all-products?brand=Brother",
			"3 souris à 19.90 CHF pièce",
			"Do you have it in size 42 or 43?",
		):
			with self.subTest(text):
				self.assertEqual(anonymise.clean(text), text)

	def test_a_text_that_still_looks_like_it_names_somebody_is_not_clean(self):
		self.assertTrue(anonymise.looks_clean("Je cherche une poêle"))
		self.assertTrue(anonymise.looks_clean("Écrivez à [email]"))
		self.assertFalse(anonymise.looks_clean("Écrivez à jean@example.com"))
		self.assertFalse(anonymise.looks_clean("Appelez le 0791234567"))
		self.assertFalse(anonymise.looks_clean("Dossier 123456789012"))


class TestSamples(FrappeTestCase):
	def setUp(self):
		self.purge()
		self.settings = frappe._dict(assistant_collect_samples=1, assistant_sample_retention_days=0)

	def tearDown(self):
		self.purge()

	@staticmethod
	def purge():
		for name in frappe.get_all(
			"Shop Assistant Conversation", filters={"guest_session": GUEST}, pluck="name"
		) + frappe.get_all("Shop Assistant Conversation", filters={"user": SIGNED_IN}, pluck="name"):
			frappe.delete_doc("Shop Assistant Conversation", name, force=True, ignore_permissions=True)
		frappe.db.delete("Shop Assistant Sample", {"question": ["like", "%[wstest]%"]})

	def collect(self):
		return samples.collect(settings=self.settings)

	def mine(self):
		return frappe.get_all(
			"Shop Assistant Sample",
			filters={"question": ["like", "%[wstest]%"]},
			fields=["*"],
		)

	# --- nothing without the switch --------------------------------------------------------------

	def test_nothing_is_collected_while_the_switch_is_off(self):
		conversation("Livrez-vous en Islande ? [wstest]", "Non, désolé.")
		self.settings.assistant_collect_samples = 0
		self.assertEqual(self.collect(), 0)
		self.assertEqual(self.mine(), [])

	def test_the_switch_is_off_by_default(self):
		field = frappe.get_meta("Webshop Settings").get_field("assistant_collect_samples")
		self.assertEqual(str(field.default or "0"), "0")

	# --- what is collected ---------------------------------------------------------------------

	def test_a_rated_pair_of_a_visitor_becomes_a_sample_without_its_origin(self):
		conversation("Livrez-vous en Islande ? [wstest]", "Non, nous livrons en Suisse.", feedback="Not useful")
		self.assertEqual(self.collect(), 1)
		(sample,) = self.mine()
		self.assertEqual((sample.opinion, sample.language), ("Not useful", "fr"))
		self.assertEqual(sample.answer, "Non, nous livrons en Suisse.")
		self.assertEqual(sample.prompt_version, "abc123def0")
		self.assertEqual(str(sample.day), nowdate())
		for column in frappe.get_meta("Shop Assistant Sample").get_valid_columns():
			self.assertNotIn(column, ("conversation", "guest_session", "user", "customer", "ip_hash"))

	def test_an_answer_nobody_rated_is_not_collected(self):
		conversation("Livrez-vous en Islande ? [wstest]", "Non.", feedback="")
		self.assertEqual(self.collect(), 0)

	def test_a_signed_in_customer_is_not_collected(self):
		if not frappe.db.exists("User", SIGNED_IN):
			frappe.get_doc(
				{"doctype": "User", "email": SIGNED_IN, "first_name": "Sample", "send_welcome_email": 0, "user_type": "Website User"}
			).insert(ignore_permissions=True)
		try:
			conversation("Où est ma commande ? [wstest]", "Elle arrive.", user=SIGNED_IN)
			self.assertEqual(self.collect(), 0)
		finally:
			self.purge()
			frappe.delete_doc("User", SIGNED_IN, force=True, ignore_permissions=True)

	def test_a_conversation_handed_to_the_team_is_not_collected(self):
		conversation("Mon colis est cassé [wstest]", "J'ai prévenu l'équipe.", status="Escalated")
		self.assertEqual(self.collect(), 0)

	def test_what_names_a_person_does_not_reach_the_sample(self):
		conversation(
			"Je m'appelle Jean Dupont, écrivez-moi à jean@example.com [wstest]", "Bien noté, Jean Dupont.", feedback="Useful"
		)
		self.assertEqual(self.collect(), 1)
		(sample,) = self.mine()
		self.assertNotIn("Dupont", sample.question + sample.answer)
		self.assertNotIn("jean@example.com", sample.question + sample.answer)

	def test_a_pair_that_still_looks_like_it_names_somebody_is_left_out_and_counted(self):
		conversation("Mon dossier 12345678 [wstest]", "Merci.", feedback="Useful")
		conversation("Livrez-vous en Islande ? [wstest]", "Non.", feedback="Useful")
		self.assertEqual(self.collect(), 1)
		self.assertEqual(samples.last_skipped, 1)

	def test_the_same_pair_is_collected_once(self):
		conversation("Livrez-vous en Islande ? [wstest]", "Non.", feedback="Useful")
		self.assertEqual(self.collect(), 1)
		self.assertEqual(self.collect(), 0)
		self.assertEqual(len(self.mine()), 1)

	def test_a_sample_is_kept_for_the_time_the_merchant_sets_and_a_year_when_none(self):
		conversation("Livrez-vous en Islande ? [wstest]", "Non.", feedback="Useful")
		self.collect()
		(sample,) = self.mine()
		self.assertEqual(getdate(sample.kept_until), getdate(add_days(nowdate(), samples.DEFAULT_RETENTION_DAYS)))
		self.settings.assistant_sample_retention_days = 30
		conversation("Et les horaires ? [wstest]", "9 h.", feedback="Useful")
		self.collect()
		kept = {row.question: getdate(row.kept_until) for row in self.mine()}
		self.assertEqual(kept["Et les horaires ? [wstest]"], getdate(add_days(nowdate(), 30)))

	def test_expired_samples_are_forgotten(self):
		conversation("Livrez-vous en Islande ? [wstest]", "Non.", feedback="Useful")
		self.collect()
		(sample,) = self.mine()
		frappe.db.set_value("Shop Assistant Sample", sample.name, "kept_until", add_days(nowdate(), -1))
		self.assertGreaterEqual(samples.purge_expired(), 1)
		self.assertEqual(self.mine(), [])

	def test_a_sample_is_not_used_until_a_person_has_read_it(self):
		field = frappe.get_meta("Shop Assistant Sample").get_field("reviewed")
		self.assertEqual(str(field.default or "0"), "0")


class TestTheConsentLine(FrappeTestCase):
	def test_the_visitor_is_told_only_while_samples_are_collected_and_only_a_visitor(self):
		self.assertIsNone(api.consent_line(frappe._dict(assistant_collect_samples=0), signed_in=False))
		self.assertIsNone(api.consent_line(frappe._dict(assistant_collect_samples=1), signed_in=True))
		line = api.consent_line(frappe._dict(assistant_collect_samples=1), signed_in=False)
		self.assertIn("improve the service", line)

	def test_the_merchant_s_own_sentence_wins(self):
		settings = frappe._dict(assistant_collect_samples=1, assistant_consent_text="Vos messages servent à améliorer Nora.")
		self.assertEqual(api.consent_line(settings, signed_in=False), "Vos messages servent à améliorer Nora.")
