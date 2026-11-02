# //// Neoffice — added file (no upstream equivalent): the mobile menu brings its own stylesheet.
"""A Builder navbar includes this menu, and a Builder page loads no shop bundle. With its rules in the shop's stylesheet, a page of the Builder lost the hamburger and
the links of the menu ran off a phone's screen, while every page of the shop still looked right (maintenance#2154). So the include prints the sheet of the component,
and the rules live in that sheet and nowhere else, for nothing to be served twice."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCSS = ROOT / "public" / "scss"
TEMPLATE = ROOT / "templates" / "includes" / "mobile_menu.html"
SHEET = SCSS / "webshop_mobile_menu.bundle.scss"


def rules_of(path: Path) -> dict[str, str]:
	"""{selector: declarations} of the flat rules of a stylesheet, comments left out."""
	text = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.DOTALL)
	text = re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)
	return {m.group(1).strip(): m.group(2) for m in re.finditer(r"([^{};]+)\{([^{}]*)\}", text)}


class TestTheMenuBringsItsStylesheet(unittest.TestCase):
	def render(self, css: str) -> str:
		from jinja2 import Environment

		text = TEMPLATE.read_text(encoding="utf-8")
		start = text.index('{%- set _component_css')
		end = text.index("<script>", start)
		return Environment().from_string(text[start:end]).render(webshop_component_css=lambda bundle: css if bundle == "webshop_mobile_menu" else "")

	def test_the_include_prints_the_sheet_of_the_component(self):
		self.assertIn("<style>.mobile-menu{}</style>", self.render(".mobile-menu{}"))

	def test_a_sheet_that_cannot_be_read_leaves_no_empty_tag(self):
		self.assertNotIn("<style>", self.render(""))

	def test_the_sheet_is_a_bundle_of_its_own_that_the_shop_does_not_import(self):
		self.assertTrue(SHEET.exists())
		self.assertNotIn("webshop_mobile_menu", (SCSS / "webshop-web.bundle.scss").read_text(encoding="utf-8"))


class TestTheRulesLiveInOnePlace(unittest.TestCase):
	def test_the_drawer_stays_off_screen_and_the_hamburger_has_its_size(self):
		rules = rules_of(SHEET)
		self.assertIn("position: fixed", rules[".mobile-menu"])
		self.assertIn("right: -300px", rules[".mobile-menu"])
		self.assertIn("display: none", rules[".mobile-menu-overlay"])
		self.assertIn("height: 40px", rules[".mobile-menu-toggle"])

	def test_the_shop_stylesheet_no_longer_holds_them(self):
		self.assertFalse([selector for selector in rules_of(SCSS / "webshop_shell.scss") if "mobile-menu" in selector])

	def test_the_sheet_reads_the_tokens_of_the_shop(self):
		self.assertIn('@import "./webshop_tokens";', SHEET.read_text(encoding="utf-8"))
