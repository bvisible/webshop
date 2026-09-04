# //// Neoffice — added file (shop assistant, no upstream equivalent).
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
	selling_price_list,
)

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
		turn = self.turns.pop(0) if self.turns else "…"
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


class TestAssistant(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.purge()
		# no standard_rate: ERPNext would write its own Item Price, and a second
		# one on the same list is a duplicate
		item = make_test_item(ITEM, item_name="Machine à espresso", is_stock_item=0)
		price_list = selling_price_list()
		if not frappe.db.exists("Item Price", {"item_code": item.name, "price_list": price_list}):
			frappe.get_doc(
				{"doctype": "Item Price", "item_code": item.name, "price_list": price_list, "price_list_rate": 349}
			).insert(ignore_permissions=True)
		website_item = make_website_item(item)
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
		super().tearDownClass()

	@classmethod
	def purge(cls):
		frappe.set_user("Administrator")
		for name in frappe.get_all("Shop Assistant Conversation", filters={"user": USER}, pluck="name"):
			frappe.delete_doc("Shop Assistant Conversation", name, force=True, ignore_permissions=True)
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
		self.real_complete = llm.complete
		self.real_settings = api.settings
		self.settings = test_settings()
		api.settings = lambda: self.settings

	def tearDown(self):
		llm.complete = self.real_complete
		api.settings = self.real_settings
		frappe.set_user("Administrator")

	def guest_context(self, session="_WSTEST-guest-1"):
		return frappe._dict(
			user="Guest", customer=None, guest_session=session, settings=self.settings, page_route="", conversation=None, summary=None
		)

	def customer_context(self):
		return frappe._dict(
			user=USER, customer=CUSTOMER, guest_session=None, settings=self.settings, page_route="", conversation=None, summary=None
		)

	def new_conversation(self, ctx):
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
		self.assertEqual(conversation.message_count, 2)
		last_call = fake.seen[-1]
		self.assertEqual(last_call[-1]["role"], "tool")
		self.assertIn("configured", last_call[-1]["content"])

	def test_the_loop_stops_after_four_rounds_of_tools(self):
		ctx = self.guest_context("_WSTEST-guest-loop")
		conversation = self.new_conversation(ctx)
		llm.complete = FakeModel([[("get_store_info", {})]] * 6 + ["Fin."])
		out = engine.respond(conversation, "encore", ctx)
		self.assertEqual(out.rounds, engine.MAX_TOOL_ROUNDS)
		self.assertEqual(out.reply, "Fin.")

	def test_an_empty_answer_falls_back_to_a_sentence(self):
		ctx = self.guest_context("_WSTEST-guest-empty")
		conversation = self.new_conversation(ctx)
		llm.complete = FakeModel([""])
		out = engine.respond(conversation, "?", ctx)
		self.assertEqual(out.reply, engine.FALLBACK)

	def test_the_system_prompt_names_the_signed_in_customer(self):
		from webshop.webshop.assistant import prompt

		text = prompt.build(self.customer_context())
		self.assertIn(CUSTOMER, text)
		self.assertIn("connecté", text)
		guest = prompt.build(self.guest_context())
		self.assertIn("n'est pas connecté", guest)

	# --- the endpoints ---------------------------------------------------------

	def test_config_is_off_when_the_switch_is_off(self):
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
		self.settings.assistant_user_daily_limit = 1
		frappe.set_user(USER)
		try:
			api.send("Un")
			out = api.send("Deux")
		finally:
			frappe.set_user("Administrator")
		self.assertTrue(out.get("limited"))

	def test_a_model_failure_is_a_calm_sentence_not_a_traceback(self):
		def broken(*args, **kwargs):
			raise RuntimeError("model down")

		llm.complete = broken
		frappe.set_user(USER)
		try:
			out = api.send("Ça marche ?")
		finally:
			frappe.set_user("Administrator")
		self.assertTrue(out.get("failed"))
		self.assertEqual(out["reply"], engine.FALLBACK)
