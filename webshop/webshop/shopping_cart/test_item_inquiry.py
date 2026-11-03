# //// Neoffice — added file (no upstream equivalent): a question about a product.
"""A question the shop cannot answer is worth nothing: it is refused without an e-mail address or a phone (one of
the two at least) or without a question, whatever the page sent. With the theme it goes the way of the site's other messages (the inbox, the bell,
the owner's mail, the anti-spam rules) instead of becoming a Lead that told nobody."""

import sys
import types
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.shopping_cart import cart

LEAD = {"lead_name": "A visitor", "email_id": "visitor@example.com", "phone": "+41 21 000 00 00"}


def _theme_door(submit):
	"""The theme's message door, replaced by `submit`. Where the theme is installed its package stays the real one: the
	translations of the apps are read from it."""
	messages = types.ModuleType("neoffice_theme.website_messages")
	messages.submit = submit
	modules = {"neoffice_theme.website_messages": messages}
	try:
		import neoffice_theme  # noqa: F401
	except ImportError:
		modules["neoffice_theme"] = types.ModuleType("neoffice_theme")
	return patch.dict(sys.modules, modules)


class TestAProductQuestion(FrappeTestCase):
	def ask(self, lead=None, message="Is it in stock?", item=None, theme=False):
		# the theme is said there or not by the shop's own question, not by frappe's list of apps: the hooks read it too
		with patch.object(cart, "_theme_installed", return_value=theme):
			return cart.create_lead_for_item_inquiry(frappe.as_json(lead or LEAD), message=message, item=item)

	def test_it_is_refused_without_an_email_address_or_a_phone(self):
		for email, phone in (("", ""), ("  ", " "), ("", "12 34")):
			with self.subTest(email=email, phone=phone), self.assertRaises(frappe.ValidationError):
				self.ask({**LEAD, "email_id": email, "phone": phone})

	def test_it_is_refused_with_a_wrong_address_or_without_a_question(self):
		with self.assertRaises(frappe.ValidationError):
			self.ask({**LEAD, "email_id": "not an address"})
		with self.assertRaises(frappe.ValidationError):
			self.ask(message=" ")

	def test_a_phone_alone_is_enough(self):
		submit = MagicMock(return_value={"ok": True})
		with _theme_door(submit):
			self.ask({**LEAD, "email_id": ""}, theme=True)
		self.assertEqual("", submit.call_args.kwargs["sender"])
		self.assertEqual("+41 21 000 00 00", submit.call_args.kwargs["phone"])

	def test_with_the_theme_it_is_a_site_message_that_names_the_product(self):
		submit = MagicMock(return_value={"ok": True})
		product = frappe._dict(
			web_item_name="A mouse", item_code="MOUSE-1", route="products/a-mouse", url="https://shop.example/products/a-mouse"
		)
		with _theme_door(submit), patch.object(cart, "_inquiry_product", return_value=product):
			answer = self.ask(item="WEB-ITM-1", theme=True)

		self.assertEqual({"ok": True}, answer)
		sent = submit.call_args.kwargs
		self.assertEqual("visitor@example.com", sent["sender"])
		self.assertEqual("+41 21 000 00 00", sent["phone"])
		self.assertIn("A mouse", sent["subject"])
		self.assertIn("MOUSE-1", sent["message"])
		self.assertIn("https://shop.example/products/a-mouse", sent["message"])

	def test_without_the_theme_it_is_a_lead_whose_question_is_escaped(self):
		lead = self.ask({**LEAD, "email_id": "inquiry-test@example.com"}, message="<b>Is it in stock?</b>")

		self.assertEqual("inquiry-test@example.com", lead.email_id)
		comments = frappe.get_all(
			"Comment", filters={"reference_doctype": "Lead", "reference_name": lead.name}, pluck="content"
		)
		self.assertTrue(any("&lt;b&gt;" in (comment or "") for comment in comments), comments)
		self.assertFalse(any("<b>" in (comment or "") for comment in comments), comments)
