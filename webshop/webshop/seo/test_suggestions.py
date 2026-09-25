# //// Neoffice — added file (no upstream equivalent). neoffice-maintenance#691, lot 6.
"""Nora's proposals for a page's title and description (seo/suggestions.py). The model is scripted,
never called: what it is given, what is taken from its answer, and who may ask."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.seo import suggestions

COMPLETE = "webshop.webshop.assistant.llm.complete"


def product(**overrides):
	doc = frappe._dict(
		name="WEB-1",
		web_item_name="Ridge Runner",
		brand="Trailhead",
		item_group="Trail shoes",
		web_long_description="<p>A trail shoe with a <b>rock plate</b>.</p>",
		website_specifications=[frappe._dict(label="Drop", description="6 mm")],
	)
	doc.update(overrides)
	return doc


class TestTheAnswer(FrappeTestCase):
	def test_a_json_object_however_it_is_wrapped(self):
		for content in (
			'{"title": "Ridge Runner trail shoe", "description": "A trail shoe."}',
			'```json\n{"title": "Ridge Runner trail shoe", "description": "A trail shoe."}\n```',
			'Here it is: {"title": "Ridge Runner trail shoe", "description": "A trail shoe."} Hope it helps.',
		):
			with self.subTest(content=content[:20]):
				self.assertEqual(suggestions.parse(content).title, "Ridge Runner trail shoe")

	def test_nothing_usable_is_none(self):
		for content in ("", "no json here", '{"title": ""}', '{"title": "x", "description": ""}', "{not json}"):
			with self.subTest(content=content):
				self.assertIsNone(suggestions.parse(content))


class TestWhatNoraIsGiven(FrappeTestCase):
	def test_the_pages_facts_and_nothing_else(self):
		with patch("webshop.webshop.seo.site.shop_name", return_value="Atelier"):
			text = suggestions.facts("Website Item", product())
		for expected in ("Ridge Runner", "Trailhead", "Trail shoes", "rock plate", "Drop : 6 mm", "Atelier"):
			self.assertIn(expected, text)
		self.assertNotIn("<b>", text)
		self.assertNotIn("CHF", text, "no price: the proposal must not promise one")


class TestAProposal(FrappeTestCase):
	def ask(self, content):
		answer = frappe._dict(content=content, model="nora")
		with (
			patch("frappe.has_permission", return_value=True) as permission,
			patch("frappe.get_doc", return_value=product()),
			patch(COMPLETE, return_value=answer) as complete,
			patch("webshop.webshop.seo.site.shop_name", return_value="Atelier"),
		):
			result = suggestions.suggest("Website Item", "WEB-1")
		return result, permission, complete

	def test_it_asks_for_the_right_to_write_and_writes_nothing(self):
		result, permission, complete = self.ask(
			'{"title": "Ridge Runner, trail shoe by Trailhead", "description": "A trail shoe with a rock plate and a 6 mm drop, made for rocky paths."}'
		)
		permission.assert_called_once_with("Website Item", "write", "WEB-1", throw=True)
		self.assertEqual(result["title"], "Ridge Runner, trail shoe by Trailhead")
		self.assertEqual(result["model"], "nora")
		system = complete.call_args.args[0][0]["content"]
		self.assertIn("n'inventes", system)

	def test_the_title_is_asked_for_the_room_the_shops_name_leaves(self):
		"""The page prints "<title> | <shop>": a proposal written for the whole budget fitted in the
		dialog and overflowed on the page."""
		result, _permission, complete = self.ask(
			'{"title": "Ridge Runner trail shoe", "description": "A trail shoe with a rock plate and a 6 mm drop, made for rocky paths."}'
		)
		system = complete.call_args.args[0][0]["content"]
		self.assertIn("au plus 50 caractères", system, "60, less the 10 of ' | Atelier'")
		self.assertEqual(result["page_title"], "Ridge Runner trail shoe | Atelier")

	def test_the_room_left_by_a_shops_name(self):
		self.assertEqual(suggestions.title_room(""), suggestions.TITLE_LIMIT)
		self.assertEqual(suggestions.title_room("Atelier"), 50)
		self.assertEqual(suggestions.title_room("A shop whose name runs on and on and on"), suggestions.TITLE_FLOOR)

	def test_a_long_answer_is_cut_at_a_word(self):
		result, _permission, _complete = self.ask(
			'{"title": "' + "Ridge Runner " * 10 + '", "description": "' + "A trail shoe. " * 30 + '"}'
		)
		self.assertLessEqual(len(result["title"]), suggestions.TITLE_LIMIT + 10)
		self.assertLessEqual(len(result["description"]), suggestions.DESCRIPTION_LIMIT + 45)

	def test_an_unusable_answer_says_so(self):
		with self.assertRaises(frappe.ValidationError):
			self.ask("I cannot help with that.")

	def test_only_the_three_pages(self):
		with self.assertRaises(frappe.ValidationError):
			suggestions.suggest("User", "Administrator")


class TestADescription(FrappeTestCase):
	"""Nora's proposal for a product page's description (suggestions.describe)."""

	def ask(self, content, doc=None):
		answer = frappe._dict(content=content, model="nora")
		with (
			patch("frappe.has_permission", return_value=True) as permission,
			patch("frappe.get_doc", return_value=doc or product()),
			patch(COMPLETE, return_value=answer) as complete,
			patch("webshop.webshop.seo.site.shop_name", return_value="Atelier"),
		):
			result = suggestions.describe("WEB-1")
		return result, permission, complete

	def test_paragraphs_become_escaped_html_and_nothing_is_written(self):
		result, permission, complete = self.ask(
			'{"paragraphs": ["A trail shoe <b>for</b> rocks & mud.", "Its drop is 6 mm."]}'
		)
		permission.assert_called_once_with("Website Item", "write", "WEB-1", throw=True)
		# the model's markup is dropped, its text escaped: only our <p> reach the page
		self.assertEqual(result["html"], "<p>A trail shoe for rocks &amp; mud.</p><p>Its drop is 6 mm.</p>")
		self.assertEqual(result["words"], 12)
		system = complete.call_args.args[0][0]["content"]
		self.assertIn("n'inventes", system)
		self.assertIn(str(suggestions.DESCRIPTION_WORDS[1]), system)

	def test_a_product_the_page_says_too_little_about_gets_no_proposal(self):
		bare = product(brand=None, item_group=None, web_long_description="", website_specifications=[])
		with (
			patch("frappe.has_permission", return_value=True),
			patch("frappe.get_doc", return_value=bare),
			patch(COMPLETE) as complete,
			self.assertRaises(frappe.ValidationError),
		):
			suggestions.describe("WEB-1")
		complete.assert_not_called()

	def test_what_counts_as_a_fact(self):
		# the test product's description is 31 characters: too short to count
		self.assertEqual(suggestions.known_facts(product()), 3, "brand, group, one characteristic")
		longer = product(web_long_description="<p>" + "A trail shoe with a rock plate for stony paths. " * 2 + "</p>")
		self.assertEqual(suggestions.known_facts(longer), 4)
		self.assertEqual(suggestions.known_facts(product(brand=None, item_group=None, web_long_description="Short.")), 1)

	def test_an_unusable_answer_says_so(self):
		for content in ("no json", '{"paragraphs": []}', '{"paragraphs": "not a list"}', '["a", "b"]'):
			with self.subTest(content=content), self.assertRaises(frappe.ValidationError):
				self.ask(content)
