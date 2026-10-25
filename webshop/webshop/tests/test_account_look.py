# //// Neoffice — added file (no upstream equivalent).
"""The account's one look is made of the site's tokens, not of colours (2026-10-25).

Measured on osiris before it: the gift card and loyalty pages carried a black block, white ink, a
#f5f5f5 chip and black step badges as inline literals, which no site could restyle and which a
dark site printed as black on dark. The account's templates say a class; the class says a token.
"""

import re
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[2]
ACCOUNT_STYLESHEET = APP / "public" / "scss" / "webshop_account.scss"
ACCOUNT_TEMPLATES = (
	APP / "templates" / "pages" / "gift_cards.html",
	APP / "templates" / "pages" / "loyalty_points.html",
	APP / "www" / "my_addresses.html",
)
LITERAL_COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\b(?:black|white)\b(?!-)")


def without_comments(source):
	source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
	return re.sub(r"(?m)(^|[ \t])//.*$", r"\1", source)


class TestTheAccountLook(unittest.TestCase):
	def test_the_account_stylesheet_writes_no_colour(self):
		found = LITERAL_COLOUR.findall(without_comments(ACCOUNT_STYLESHEET.read_text()))
		self.assertEqual(found, [], "a colour is a token: var(--wsh-…)")

	def test_the_account_templates_carry_no_inline_colour(self):
		for template in ACCOUNT_TEMPLATES:
			for style in re.findall(r'style="([^"]*)"', template.read_text()):
				self.assertNotRegex(style, LITERAL_COLOUR, f"{template.name}: style=\"{style}\"")

	def test_the_account_stylesheet_is_in_the_shop_bundle(self):
		bundle = (APP / "public" / "scss" / "webshop-web.bundle.scss").read_text()
		self.assertIn('@import "./webshop_account";', bundle)

	def test_a_page_title_the_chrome_already_prints_steps_aside(self):
		# The rule that hides it names every title the account's pages print by themselves.
		rule = without_comments(ACCOUNT_STYLESHEET.read_text())
		for title in (".my-account-header", ".web-form-title", ".page-card-head", ".mrz-head .nb-title--lg"):
			self.assertIn(title, rule)
		self.assertIn(":has(.site-page-header)", rule)
