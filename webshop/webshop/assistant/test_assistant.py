# //// Neoffice — added file (shop assistant, no upstream equivalent).
# //// Neoffice — below: settings are read once into an in-memory copy instead of written
# //// via frappe.db.set_single_value, since a write to tabSingles on a shared site (osiris)
# //// waited on another suite's lock, twice, until timeout (807c98474e "test(assistant): des
# //// réglages en mémoire, pas d'écriture dans tabSingles")
"""The assistant without a model: `llm.complete` is replaced by a fake that
answers what each test scripts, so what is exercised is everything around it —
the identity of the tools, the loop, what gets written on the conversation,
the limits, the endpoints.

Settings are never written: `api.settings()` is replaced by an in-memory copy
of Webshop Settings with the switches this class needs. A Single survives the
test rollback, and on a shared site (osiris) a write to `tabSingles` waits on
whatever another test run holds — twice a lock timeout, before this.
Fixtures are committed in setUpClass and purged in tearDownClass.
"""

import json

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from webshop.webshop.assistant import api, engine, llm, tools
from webshop.webshop.doctype.website_item.website_item import make_website_item
from webshop.webshop.tests.utils import (
	PREFIX,
	default_company,
	leaf_customer_group,
	make_test_item,
	portal_customer,
	# //// Neoffice — removed restore_webshop_settings import (807c98474e "test(assistant): des
	# //// réglages en mémoire, pas d'écriture dans tabSingles"): settings are no longer snapshotted
	# //// and restored via Webshop Settings, so this helper is unused here.
	selling_price_list,
	# //// Neoffice — removed snapshot_webshop_settings import (807c98474e, same commit): same
	# //// reason as above.
)

# //// Neoffice — removed SETTINGS_FIELDS constant (807c98474e, same commit): it only listed the
# //// fields snapshotted/restored around Webshop Settings, now replaced by an in-memory copy.
CUSTOMER = f"{PREFIX} Assistant Customer"
USER = "wstest-assistant@example.com"
OTHER_CUSTOMER = f"{PREFIX} Assistant Stranger"
ITEM = f"{PREFIX} Espresso Machine"


class FakeModel:
	"""Scripts the model's turns: a list of replies, each either text or tool calls."""

	def __init__(self, turns):
		self.turns = list(turns)
		self.seen = []

	def __call__(self, messages, tools_schema=None, settings=None, **kwargs):
		self.seen.append(messages)
		# //// Neoffice — records whether tools were offered on each call, so a test can check
		# //// the last round of the loop was made without tools (a1c7c75f97 "fix(assistant):
		# //// après le dernier tour d'outils, le modèle répond sans outils")
		self.tools_offered = getattr(self, "tools_offered", []) + [bool(tools_schema)]
		turn = self.turns.pop(0) if self.turns else "…"
		# //// Neoffice — TO REVIEW: "test(assistant): des réglages en mémoire, pas d'écriture dans
		# //// tabSingles" (807c98474e) — reformatted only (line-length), reason not stated in the commit
		out = frappe._dict(
			content="", tool_calls=[], prompt_tokens=100, completion_tokens=20, model="fake", duration_ms=5, finish_reason="stop"
		)
		if isinstance(turn, str):
			out.content = turn
		else:
			out.tool_calls = [
				{"id": f"call_{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
				for i, (name, args) in enumerate(turn)
			]
		return out


# //// Neoffice — added: builds the in-memory Webshop Settings copy that api.settings() is
# //// monkeypatched to return during these tests, instead of writing to the Single via
# //// frappe.db.set_single_value (807c98474e "test(assistant): des réglages en mémoire, pas
# //// d'écriture dans tabSingles").
def test_settings(**overrides):
	"""Webshop Settings as this class wants them, in memory only."""
	doc = frappe.get_doc("Webshop Settings")
	doc.enable_assistant = 1
	doc.assistant_name = "Nora"
	doc.assistant_guest_daily_limit = 30
	doc.assistant_user_daily_limit = 200
	doc.assistant_monthly_token_cap = 0
	doc.assistant_llm_base_url = "http://fake.invalid/v1"
	for key, value in overrides.items():
		setattr(doc, key, value)
	return doc


# //// Neoffice — added (c81fe963b2 "test(assistant): un site neuf reçoit une liste de
# //// prix et l'affichage des prix"): CI runs on an empty shop, so without a price
# //// list the search rendered "price on request"; write only what is missing.
def ensure_shop_settings():
	"""A fresh site (CI) has no price list and hides prices; osiris has both.

	Only what is missing is written — a Single survives the rollback, and on a
	shared site a write to `tabSingles` waits on other suites' locks. What was
	written is returned so tearDownClass can put it back.
	"""
	# //// Neoffice — added "company" (8165e65994 "test(assistant): la boutique neuve a aussi
	# //// besoin de sa société pour un prix"): a fresh shop's price list also needs its company set.
	wanted = {"enabled": 1, "show_price": 1, "price_list": selling_price_list(), "company": default_company()}
	written = {}
	for field, value in wanted.items():
		current = frappe.db.get_single_value("Webshop Settings", field)
		if not current:
			written[field] = current
			frappe.db.set_single_value("Webshop Settings", field, value)
	if written:
		frappe.db.commit()
		frappe.local.shopping_cart_settings = None
		frappe.clear_cache()
	return written


class TestAssistant(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# //// Neoffice — added (c81fe963b2 "test(assistant): un site neuf reçoit une liste
		# //// de prix et l'affichage des prix"): write what a fresh site is missing, restored below
		cls.settings_written = ensure_shop_settings()
		cls.purge()
		# no standard_rate: ERPNext would write its own Item Price, and a second
		# one on the same list is a duplicate
		item = make_test_item(ITEM, item_name="Machine à espresso", is_stock_item=0)
		price_list = selling_price_list()
		if not frappe.db.exists("Item Price", {"item_code": item.name, "price_list": price_list}):
			frappe.get_doc(
				{"doctype": "Item Price", "item_code": item.name, "price_list": price_list, "price_list_rate": 349}
			).insert(ignore_permissions=True)
		# //// Neoffice — make_website_item returns [name, web_item_name], not the document
		# //// (3348ed273a "test(assistant): make_website_item rend des noms, pas le document");
		# //// re-fetch the Website Item explicitly before editing it.
		make_website_item(item)  # returns [name, web_item_name], not the document
		website_item = frappe.get_doc("Website Item", {"item_code": item.name})
		website_item.published = 1
		website_item.short_description = "Une machine à espresso compacte pour le bureau"
		website_item.save(ignore_permissions=True)
		cls.item_code = item.name
		portal_customer(USER, CUSTOMER)
		cls.order = cls.make_order(CUSTOMER)
		cls.stranger_order = cls.make_order(OTHER_CUSTOMER)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		cls.purge()
		# //// Neoffice — added (c81fe963b2 "test(assistant): un site neuf reçoit une liste
		# //// de prix et l'affichage des prix"): put back only what ensure_shop_settings() wrote
		# only what ensure_shop_settings() wrote on a fresh site goes back
		for field, value in cls.settings_written.items():
			frappe.db.set_single_value("Webshop Settings", field, value)
		if cls.settings_written:
			frappe.db.commit()
			frappe.local.shopping_cart_settings = None
			frappe.clear_cache()
		super().tearDownClass()

	@classmethod
	def purge(cls):
		frappe.set_user("Administrator")
		for name in frappe.get_all("Shop Assistant Conversation", filters={"user": USER}, pluck="name"):
			frappe.delete_doc("Shop Assistant Conversation", name, force=True, ignore_permissions=True)
		# //// Neoffice — TO REVIEW: "test(assistant): des réglages en mémoire, pas d'écriture dans
		# //// tabSingles" (807c98474e) — reformatted only (line-length), reason not stated in the commit
		for name in frappe.get_all(
			"Shop Assistant Conversation", filters={"guest_session": ["like", f"{PREFIX}%"]}, pluck="name"
		):
			frappe.delete_doc("Shop Assistant Conversation", name, force=True, ignore_permissions=True)
		for customer in (CUSTOMER, OTHER_CUSTOMER):
			for so in frappe.get_all("Sales Order", filters={"customer": customer}, pluck="name"):
				doc = frappe.get_doc("Sales Order", so)
				if doc.docstatus == 1:
					doc.flags.ignore_permissions = True
					doc.cancel()
				frappe.delete_doc("Sales Order", so, force=True, ignore_permissions=True)
		for wi in frappe.get_all("Website Item", filters={"item_code": ITEM}, pluck="name"):
			frappe.delete_doc("Website Item", wi, force=True, ignore_permissions=True)
		frappe.db.delete("Item Price", {"item_code": ITEM})
		if frappe.db.exists("Item", ITEM):
			frappe.delete_doc("Item", ITEM, force=True, ignore_permissions=True)
		if frappe.db.exists("Customer", OTHER_CUSTOMER):
			frappe.delete_doc("Customer", OTHER_CUSTOMER, force=True, ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def make_order(cls, customer):
		if not frappe.db.exists("Customer", customer):
			frappe.get_doc(
				{
					"doctype": "Customer",
					"customer_name": customer,
					"customer_group": leaf_customer_group(),
					"territory": frappe.db.get_value("Territory", {"lft": 1}, "name"),
					"default_currency": frappe.db.get_single_value("Global Defaults", "default_currency")
					or frappe.db.get_value("Company", {}, "default_currency"),
				}
			).insert(ignore_permissions=True)
		so = frappe.get_doc(
			{
				"doctype": "Sales Order",
				"customer": customer,
				"company": default_company(),
				"transaction_date": nowdate(),
				"delivery_date": add_days(nowdate(), 5),
				"selling_price_list": selling_price_list(),
				# //// Neoffice — TO REVIEW: "test(assistant): des réglages en mémoire, pas d'écriture
				# //// dans tabSingles" (807c98474e) — reformatted only (line-length), reason not stated
				"items": [
					{"item_code": cls.item_code, "qty": 1, "rate": 349, "delivery_date": add_days(nowdate(), 5)}
				],
			}
		)
		so.flags.ignore_permissions = True
		so.insert()
		so.submit()
		return so.name

	def setUp(self):
		frappe.set_user("Administrator")
		# //// Neoffice — frappe.log_error commits, so a conversation saved by a failing-model
		# //// test in this class was still on the database for the next test of the same user;
		# //// purge them here first (a1c7c75f97 "fix(assistant): après le dernier tour d'outils,
		# //// le modèle répond sans outils")
		# frappe.log_error commits: a conversation saved by a failing-model test
		# would otherwise be found again by the next test of the same user
		for name in frappe.get_all("Shop Assistant Conversation", filters={"user": USER}, pluck="name"):
			frappe.delete_doc("Shop Assistant Conversation", name, force=True, ignore_permissions=True)
		frappe.db.commit()
		self.real_complete = llm.complete
		# //// Neoffice — added: api.settings() is monkeypatched to return an in-memory copy for the
		# //// duration of each test, so nothing is written to Webshop Settings (807c98474e
		# //// "test(assistant): des réglages en mémoire, pas d'écriture dans tabSingles").
		self.real_settings = api.settings
		self.settings = test_settings()
		api.settings = lambda: self.settings
		# //// Neoffice — the outage flag lives in Redis, which no rollback touches
		api.clear_outage()

	def tearDown(self):
		llm.complete = self.real_complete
		# //// Neoffice — added: restores api.settings (807c98474e, same commit).
		api.settings = self.real_settings
		api.clear_outage()
		frappe.set_user("Administrator")

	def guest_context(self, session="_WSTEST-guest-1"):
		# //// Neoffice — uses self.settings (the in-memory copy) instead of calling api.settings(),
		# //// which used to read Webshop Settings from the database (807c98474e, same commit).
		return frappe._dict(
			user="Guest", customer=None, guest_session=session, settings=self.settings, page_route="", conversation=None, summary=None
		)

	def customer_context(self):
		# //// Neoffice — same reason as guest_context above: self.settings replaces api.settings()
		# //// (807c98474e, same commit).
		return frappe._dict(
			user=USER, customer=CUSTOMER, guest_session=None, settings=self.settings, page_route="", conversation=None, summary=None
		)

	def new_conversation(self, ctx):
		# //// Neoffice — TO REVIEW: "test(assistant): des réglages en mémoire, pas d'écriture dans
		# //// tabSingles" (807c98474e) — reformatted only (line-length), reason not stated in the commit
		doc = frappe.get_doc(
			{
				"doctype": "Shop Assistant Conversation",
				"user": ctx.user if ctx.user != "Guest" else None,
				"customer": ctx.customer,
				"guest_session": ctx.guest_session,
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
		ctx.conversation = doc
		return doc

	# --- the tools themselves -------------------------------------------------

	def test_a_product_search_shows_the_selling_price_and_nothing_else(self):
		out = tools.run("search_products", {"query": "espresso"}, self.guest_context())
		self.assertGreaterEqual(out["count"], 1)
		card = next(p for p in out["products"] if p["item_code"] == self.item_code)
		self.assertIn("349", card["price"])
		self.assertTrue(card["url"].startswith("/"))
		forbidden = {"valuation_rate", "last_purchase_rate", "purchase_rate", "buying", "cost"}
		self.assertFalse(forbidden & set(card))

	def test_a_product_detail_carries_the_description(self):
		out = tools.run("get_product", {"item_code": self.item_code}, self.guest_context())
		self.assertIn("espresso", out["product"]["description"].lower())

	def test_a_guest_cannot_read_orders(self):
		out = tools.run("get_my_orders", {}, self.guest_context())
		self.assertIn("error", out)
		self.assertIn("connect", out["error"].lower())

	def test_the_customer_reads_their_own_order_and_nobody_else_s(self):
		ctx = self.customer_context()
		mine = tools.run("get_my_orders", {}, ctx)
		self.assertIn(self.order, [o["number"] for o in mine["orders"]])
		self.assertNotIn(self.stranger_order, [o["number"] for o in mine["orders"]])
		detail = tools.run("get_order", {"number": self.order}, ctx)
		self.assertEqual(detail["number"], self.order)
		self.assertEqual(len(detail["lines"]), 1)
		stranger = tools.run("get_order", {"number": self.stranger_order}, ctx)
		self.assertIn("error", stranger)

	def test_an_unknown_tool_is_refused_not_executed(self):
		out = tools.run("drop_database", {}, self.guest_context())
		self.assertIn("error", out)

	def test_the_toolbox_is_exactly_what_the_model_is_told(self):
		names = {t["function"]["name"] for t in tools.schemas()}
		self.assertEqual(names, set(tools.BY_NAME))
		self.assertTrue(all(t["function"]["description"] for t in tools.schemas()))

	# --- the loop ------------------------------------------------------------

	def test_a_tool_call_is_executed_and_written_on_the_conversation(self):
		ctx = self.guest_context()
		conversation = self.new_conversation(ctx)
		fake = FakeModel([[("get_store_hours", {})], "Voici nos horaires."])
		llm.complete = fake
		out = engine.respond(conversation, "Vos horaires ?", ctx)
		self.assertEqual(out.reply, "Voici nos horaires.")
		self.assertEqual(out.prompt_tokens, 200)
		roles = [m.role for m in conversation.messages]
		self.assertEqual(roles, ["user", "assistant", "tool", "assistant"])
		self.assertEqual(conversation.messages[2].tool_name, "get_store_hours")
		self.assertEqual(conversation.prompt_tokens, 200)
		# //// Neoffice — was 3: message_count no longer counts the model's tool-call requests, only
		# //// what the visitor saw (807c98474e "test(assistant): des réglages en mémoire, pas
		# //// d'écriture dans tabSingles"); see shop_assistant_conversation.py validate().
		self.assertEqual(conversation.message_count, 2)
		last_call = fake.seen[-1]
		self.assertEqual(last_call[-1]["role"], "tool")
		self.assertIn("configured", last_call[-1]["content"])

	def test_the_loop_stops_after_four_rounds_of_tools(self):
		ctx = self.guest_context("_WSTEST-guest-loop")
		conversation = self.new_conversation(ctx)
		# //// Neoffice — script exactly MAX_TOOL_ROUNDS tool turns (was 6, an arbitrary
		# //// overshoot) plus the final worded reply, and check the last call was made
		# //// without tools (a1c7c75f97 "fix(assistant): après le dernier tour d'outils,
		# //// le modèle répond sans outils")
		fake = FakeModel([[("get_store_info", {})]] * engine.MAX_TOOL_ROUNDS + ["Fin."])
		llm.complete = fake
		out = engine.respond(conversation, "encore", ctx)
		self.assertEqual(out.rounds, engine.MAX_TOOL_ROUNDS)
		self.assertEqual(out.reply, "Fin.")
		# the last call carried no tools: the model had to answer in words
		self.assertEqual(len(fake.seen), engine.MAX_TOOL_ROUNDS + 1)
		self.assertFalse(fake.tools_offered[-1])

	def test_an_empty_answer_falls_back_to_a_sentence(self):
		ctx = self.guest_context("_WSTEST-guest-empty")
		conversation = self.new_conversation(ctx)
		llm.complete = FakeModel([""])
		out = engine.respond(conversation, "?", ctx)
		self.assertEqual(out.reply, engine.FALLBACK)

	def test_the_system_prompt_names_the_signed_in_customer(self):
		from webshop.webshop.assistant import prompt

		# //// Neoffice — TO REVIEW: "test(assistant): des réglages en mémoire, pas d'écriture dans
		# //// tabSingles" (807c98474e) — reformatted only (line-length), reason not stated in the commit
		text = prompt.build(self.customer_context())
		self.assertIn(CUSTOMER, text)
		self.assertIn("connecté", text)
		guest = prompt.build(self.guest_context())
		self.assertIn("n'est pas connecté", guest)

	# --- the endpoints ---------------------------------------------------------

	def test_config_is_off_when_the_switch_is_off(self):
		# //// Neoffice — flips the in-memory settings copy directly instead of writing
		# //// enable_assistant via frappe.db.set_single_value and clearing the doctype cache
		# //// afterwards (807c98474e "test(assistant): des réglages en mémoire, pas d'écriture
		# //// dans tabSingles").
		self.settings.enable_assistant = 0
		self.assertEqual(api.get_config(), {"enabled": False})

	def test_config_greets_the_customer_by_first_name(self):
		frappe.set_user(USER)
		try:
			cfg = api.get_config()
		finally:
			frappe.set_user("Administrator")
		self.assertTrue(cfg["enabled"])
		self.assertTrue(cfg["signed_in"])
		self.assertIn("Bonjour", cfg["greeting"])
		self.assertEqual(cfg["labels"]["send"], "Envoyer")

	def test_send_answers_and_resumes_the_same_conversation(self):
		llm.complete = FakeModel(["Bien sûr.", "Encore moi."])
		frappe.set_user(USER)
		try:
			first = api.send("Bonjour")
			second = api.send("Encore ?")
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(first["reply"], "Bien sûr.")
		self.assertEqual(second["conversation"], first["conversation"])
		doc = frappe.get_doc("Shop Assistant Conversation", first["conversation"])
		self.assertEqual(doc.customer, CUSTOMER)
		self.assertEqual(doc.user, USER)
		self.assertEqual([m.content for m in doc.messages if m.role == "user"], ["Bonjour", "Encore ?"])

	def test_the_daily_limit_stops_the_visitor_politely(self):
		llm.complete = FakeModel(["Oui.", "Non."])
		# //// Neoffice — same reason as test_config_is_off_when_the_switch_is_off above: flips the
		# //// in-memory settings copy directly (807c98474e, same commit).
		self.settings.assistant_user_daily_limit = 1
		frappe.set_user(USER)
		try:
			api.send("Un")
			out = api.send("Deux")
		finally:
			frappe.set_user("Administrator")
		# //// Neoffice — removed: restoring assistant_user_daily_limit to 200 via
		# //// frappe.db.set_single_value and clearing the cache (807c98474e, same commit) — the
		# //// in-memory settings copy is discarded with the test, nothing to restore.
		self.assertTrue(out.get("limited"))
		# //// Neoffice — the limit is the answering machine now: a reason, an invitation, the form
		self.assertEqual(out["unavailable"], "limit")
		self.assertTrue(out["leave_message"])
		self.assertFalse(out["email_required"])
		self.assertIn("limite", out["reply"])
		self.assertIn("message", out["reply"])

	# //// Neoffice — was test_a_model_failure_is_a_calm_sentence_not_a_traceback, which only
	# //// checked the canned FALLBACK; the failure now switches the bubble to the answering
	# //// machine and arms an outage flag that spares the next visitors the 25 s wait.
	def test_a_model_failure_switches_to_the_answering_machine(self):
		def broken(*args, **kwargs):
			raise RuntimeError("model down")

		llm.complete = broken
		frappe.set_user(USER)
		try:
			out = api.send("Ça marche ?")
			# //// Neoffice — checks the outage flag actually skips the model, and that get_config's notice reflects it too (814347b504 "feat(assistant): un répondeur quand le modèle tombe ou la limite est atteinte")
			# the failure armed the flag: the next message is answered at once, the model is not called
			fake = FakeModel(["Oui."])
			llm.complete = fake
			again = api.send("Et maintenant ?")
			cfg = api.get_config()
			api.clear_outage()
			after = api.send("Et maintenant ?")
		finally:
			frappe.set_user("Administrator")
		self.assertTrue(out.get("failed"))
		# //// Neoffice ▼▼▼ — new coverage for the answering machine: outage assertions, then the "leave a message" tape (team notified with no model involved, guest email required, a broken SMTP config never surfacing to the visitor, the confirmation bypassing the follow-ups' unsubscribe) and the merchant-worded notice (814347b504 "feat(assistant): un répondeur quand le modèle tombe ou la limite est atteinte")
		self.assertEqual(out["unavailable"], "outage")
		self.assertTrue(out["leave_message"])
		self.assertNotIn("Traceback", out["reply"])
		self.assertIn("message", out["reply"])
		self.assertEqual(again["unavailable"], "outage")
		self.assertEqual(cfg["notice"]["unavailable"], "outage")
		self.assertEqual(after["reply"], "Oui.")
		self.assertEqual(len(fake.seen), 1)
		doc = frappe.get_doc("Shop Assistant Conversation", out["conversation"])
		self.assertEqual([m.role for m in doc.messages], ["user", "assistant"] * 3)

	# --- the answering machine's tape ------------------------------------------

	def _muted_team(self, escalation, posted, mailed):
		"""Raven and the mail recorded instead of sent; returns what to put back."""
		real = (escalation._post_to_raven, frappe.sendmail)
		escalation._post_to_raven = lambda channel, text: bool(posted.append((channel, text))) or True
		frappe.sendmail = lambda *args, **kwargs: mailed.append(kwargs)
		return real

	@staticmethod
	def _recipients(mailed):
		out = []
		for call in mailed:
			r = call.get("recipients") or []
			out += [r] if isinstance(r, str) else list(r)
		return out

	def test_a_broken_mail_server_never_reaches_the_visitor(self):
		"""When frappe.sendmail throws on a misconfigured SMTP, no message reaches the browser."""
		from webshop.webshop.assistant import escalation

		def boom(*args, **kwargs):
			frappe.msgprint("Serveur de messagerie sortant ou port invalide", title="Configuration incorrecte")
			raise frappe.OutgoingEmailError("smtp down")

		real = frappe.sendmail
		frappe.sendmail = boom
		frappe.clear_messages()
		ctx = self.customer_context()
		self.new_conversation(ctx)
		try:
			out = escalation.contact_team(ctx, summary="Rappelez-moi", email=USER)
		finally:
			frappe.sendmail = real
		self.assertTrue(out["escalated"])
		# the SMTP error was swallowed: nothing queued for the browser to pop up
		self.assertEqual(frappe.local.message_log, [])

	def test_leave_message_reaches_the_team_without_the_model(self):
		from webshop.webshop.assistant import escalation

		def broken(*args, **kwargs):
			raise AssertionError("the model must not be called")

		llm.complete = broken
		self.settings.assistant_support_email = "team@example.com"
		self.settings.assistant_escalation_channel = "_WSTEST channel"
		posted, mailed = [], []
		real_raven, real_sendmail = self._muted_team(escalation, posted, mailed)
		frappe.set_user(USER)
		try:
			out = api.leave_message("Ma souris est arrivée cassée.")
		finally:
			frappe.set_user("Administrator")
			escalation._post_to_raven, frappe.sendmail = real_raven, real_sendmail
		self.assertTrue(out["escalated"])
		self.assertEqual(out["via"], "raven")
		self.assertIn(USER, out["reply"])
		doc = frappe.get_doc("Shop Assistant Conversation", out["conversation"])
		self.assertEqual(doc.status, "Escalated")
		self.assertEqual(doc.escalated_to, "Team")
		self.assertEqual(doc.escalation_note, "Ma souris est arrivée cassée.")
		self.assertEqual([m.role for m in doc.messages], ["user", "assistant"])
		self.assertEqual(posted[0][0], "_WSTEST channel")
		self.assertIn("cassée", posted[0][1])
		# the team's email and the customer's confirmation
		recipients = self._recipients(mailed)
		self.assertIn("team@example.com", recipients)
		self.assertIn(USER, recipients)

	def test_leave_message_as_a_guest_needs_a_valid_email(self):
		from webshop.webshop.assistant import escalation

		ctx = self.guest_context("_WSTEST-guest-leave")
		self.new_conversation(ctx)
		with self.assertRaises(frappe.ValidationError):
			api.leave(ctx, "Aidez-moi", email="pas-un-email")
		posted, mailed = [], []
		real_raven, real_sendmail = self._muted_team(escalation, posted, mailed)
		try:
			out = api.leave(ctx, "Aidez-moi", email="visiteur@example.com")
		finally:
			escalation._post_to_raven, frappe.sendmail = real_raven, real_sendmail
		self.assertTrue(out["escalated"])
		self.assertIn("visiteur@example.com", out["reply"])
		self.assertEqual(ctx.conversation.status, "Escalated")
		self.assertIn("visiteur@example.com", self._recipients(mailed))

	def test_the_confirmation_reaches_a_customer_who_stopped_the_follow_ups(self):
		"""The follow-ups' unsubscribe must not swallow a transactional receipt."""
		from webshop.webshop.assistant import escalation

		ctx = self.customer_context()
		self.new_conversation(ctx)
		# the customer once clicked the follow-ups' unsubscribe link, scoped to their Customer
		unsub = {"email": USER, "reference_doctype": "Customer", "reference_name": CUSTOMER}
		if not frappe.db.exists("Email Unsubscribe", unsub):
			frappe.get_doc({"doctype": "Email Unsubscribe", **unsub}).insert(ignore_permissions=True)
		# //// Neoffice — the mail is captured, not read back from Email Queue: under test
		# //// Frappe mutes outgoing mail, so a queue assertion passed on osiris (where a run
		# //// had left an account behind) and failed on CI's fresh site.
		mailed = []
		real = frappe.sendmail
		frappe.sendmail = lambda *args, **kwargs: mailed.append(kwargs)
		try:
			escalation._notify_customer(USER, "Votre demande a été transmise", "Bonjour", ctx)
		finally:
			frappe.sendmail = real
		self.assertEqual([c.get("recipients") for c in mailed], [[USER]])
		# the giveaway of the follow-ups' path, the one that carries the unsubscribe
		self.assertNotIn("unsubscribe_message", mailed[0])
		self.assertTrue(
			frappe.db.exists("Communication", {"reference_doctype": "Customer", "reference_name": CUSTOMER, "subject": "Votre demande a été transmise"})
		)

	def test_the_support_email_falls_back_without_a_website_settings_field(self):
		"""A stock Frappe has no Website Settings.email: asking for it used to raise."""
		from webshop.webshop.assistant import escalation

		self.settings.assistant_support_email = "support@example.com"
		self.assertEqual(escalation._support_email(self.settings), "support@example.com")
		self.settings.assistant_support_email = ""
		self.settings.store_email = "boutique@example.com"
		self.assertEqual(escalation._support_email(self.settings), "boutique@example.com")
		self.settings.store_email = ""
		# whatever the site carries, it must answer instead of raising
		escalation._support_email(self.settings)

	def test_the_answering_machine_speaks_the_merchant_s_words(self):
		self.settings.assistant_offline_message = "Nora fait une pause."
		guest = api.unavailable(self.guest_context(), "outage")
		self.assertTrue(guest["reply"].startswith("Nora fait une pause."))
		self.assertIn("message", guest["reply"])
		self.assertTrue(guest["email_required"])
		customer = api.unavailable(self.customer_context(), "cap")
		self.assertFalse(customer["email_required"])
		limit = api.unavailable(self.customer_context(), "limit")
		self.assertTrue(limit["reply"].startswith("Vous avez atteint la limite"))
		# the shop's opening status is part of the notice whenever hours are published
		status = api.store_status_line(self.settings)
		if status:
			self.assertIn(status, guest["reply"])
		# //// Neoffice ▲▲▲
