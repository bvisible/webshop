# //// Neoffice — added file (no upstream equivalent).
"""The links to a product's sheet: which ones the page offers, and how little room they take.

The page offers the shop's sheet to anybody (when the shop switched it on) and the reseller's own to a
reseller. It draws them as one quiet row of small icons, "PDF" for the first and "PDF" with a "B2B" tag for
the second, not as two buttons (2026-11-02). Nothing here touches the database: the settings are in memory
and the offer is stubbed.
"""

import pathlib
import re
from unittest import mock

import frappe
from frappe import _
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.catalogue import sheet_links

APP = pathlib.Path(frappe.get_app_path("webshop"))
INCLUDE = APP / "templates" / "generators" / "item" / "item_sheet_links.html"
DETAILS = APP / "templates" / "generators" / "item" / "item_details.html"
STYLES = APP / "public" / "scss" / "webshop_product_page.scss"

SHOP_ON = frappe._dict(enable_product_sheet=1)
SHOP_OFF = frappe._dict(enable_product_sheet=0)
DOC = frappe._dict(name="WEB-ITM-0001")


def links_for(settings, user="Guest", offered=False, doc=DOC):
	signed_in_as = frappe.session.user
	frappe.set_user(user)
	try:
		with mock.patch("webshop.webshop.catalogue.access.is_offered", return_value=offered):
			return sheet_links.sheet_links(doc, settings)
	finally:
		frappe.set_user(signed_in_as)


def draw(links):
	return frappe.render_template(INCLUDE.read_text(), {"sheet_links": links})


def anchors(html):
	return re.findall(r"<a [^>]*>.*?</a>", html, re.S)


def heard(link):
	"""What a screen reader reads of a link: its text without what is hidden from it."""
	link = re.sub(r"<svg\b.*?</svg>", "", link, flags=re.S)
	link = re.sub(r"<span\b[^>]*aria-hidden=\"true\"[^>]*>.*?</span>", "", link, flags=re.S)
	return " ".join(re.sub(r"<[^>]+>", " ", link).split())


class TestWhichLinks(FrappeTestCase):
	def test_a_visitor_is_offered_the_shops_sheet_only(self):
		links = links_for(SHOP_ON)
		self.assertEqual([link["own"] for link in links], [False])
		self.assertEqual(links[0]["label"], _("Product sheet (PDF)"))
		self.assertTrue(links[0]["href"].endswith("sheet_api.product_sheet?item=WEB-ITM-0001"))

	def test_nothing_is_offered_when_the_shop_did_not_switch_the_sheet_on(self):
		self.assertEqual(links_for(SHOP_OFF), [])

	def test_a_reseller_is_offered_the_shops_sheet_and_their_own(self):
		links = links_for(SHOP_ON, user="reseller@example.com", offered=True)
		self.assertEqual([link["own"] for link in links], [False, True])
		self.assertEqual(links[1]["label"], _("Product sheet in my name (PDF)"))
		self.assertTrue(links[1]["href"].endswith("sheet_api.my_product_sheet?item=WEB-ITM-0001"))

	def test_a_signed_in_customer_the_shop_does_not_offer_the_catalogue_to_sees_the_shops_sheet_only(self):
		links = links_for(SHOP_ON, user="customer@example.com", offered=False)
		self.assertEqual([link["own"] for link in links], [False])

	def test_the_resellers_own_sheet_does_not_wait_for_the_shops(self):
		links = links_for(SHOP_OFF, user="reseller@example.com", offered=True)
		self.assertEqual([link["own"] for link in links], [True])

	def test_a_visitor_never_reaches_the_own_sheet_even_if_the_offer_says_yes(self):
		self.assertEqual([link["own"] for link in links_for(SHOP_ON, offered=True)], [False])

	def test_the_item_name_is_quoted_in_the_address(self):
		links = links_for(SHOP_ON, doc=frappe._dict(name="A B&c=d/é"))
		self.assertIn("item=A%20B%26c%3Dd/%C3%A9", links[0]["href"])


class TestHowTheyAreDrawn(FrappeTestCase):
	def test_nothing_is_drawn_when_nothing_is_offered(self):
		self.assertEqual(draw([]).strip(), "")

	def test_the_shops_sheet_is_a_small_pdf_icon_and_no_button(self):
		html = draw(links_for(SHOP_ON))
		(link,) = anchors(html)
		self.assertIn("wsp-sheet-link", link)
		self.assertNotIn("btn", html)
		self.assertIn(">PDF</span>", link)
		self.assertNotIn("B2B", link)
		self.assertEqual(link.count("<svg"), 1)
		self.assertIn('aria-hidden="true"', link.split("</svg>")[0])
		self.assertIn('stroke="currentColor"', link)
		self.assertIn('target="_blank" rel="noopener"', link)

	def test_the_resellers_own_sheet_carries_a_b2b_tag(self):
		html = draw(links_for(SHOP_ON, user="reseller@example.com", offered=True))
		shop, own = anchors(html)
		self.assertNotIn("B2B", shop)
		self.assertEqual(own.count("B2B"), 1)
		self.assertIn("wsp-sheet-link--own", own)
		self.assertEqual(html.count("B2B"), 1)

	def test_each_link_says_what_it_is_to_a_cursor_and_to_a_screen_reader(self):
		html = draw(links_for(SHOP_ON, user="reseller@example.com", offered=True))
		for link, label in zip(anchors(html), (_("Product sheet (PDF)"), _("Product sheet in my name (PDF)"))):
			self.assertIn(f'title="{label}"', link)
			self.assertRegex(link, rf'<span class="wsp-sheet-link__name">{re.escape(label)}</span>')
			# what is drawn (the icon, "PDF", "B2B") is hidden from a reader, which hears the full label once
			self.assertEqual(heard(link), label)

	def test_a_label_and_an_address_are_escaped(self):
		html = draw([{"label": '<script>alert(1)</script>"', "href": '/x?a="1"&b=<2>', "own": False}])
		self.assertNotIn("<script>", html)
		self.assertNotIn('"1"', html)
		self.assertIn("&lt;script&gt;", html)


class TestWhereAndHowMuch(FrappeTestCase):
	def test_the_page_includes_the_row_once_after_its_trust_items_and_not_under_a_gift_card(self):
		text = DETAILS.read_text()
		statement = '{% include "templates/generators/item/item_sheet_links.html" %}'
		self.assertEqual(text.count("item_sheet_links.html"), 1)
		self.assertLess(text.index('class="buybox-trust"'), text.index(statement))
		self.assertTrue(text[: text.index(statement)].rstrip().endswith("{% if not doc.is_gift_card %}"))

	def test_the_two_buttons_are_gone(self):
		self.assertNotIn("btn-outline-primary", DETAILS.read_text())
		self.assertNotIn("btn", INCLUDE.read_text().split("{% if sheet_links %}")[1])

	def test_every_class_the_row_prints_is_dressed_and_none_paints_a_ground(self):
		css = STYLES.read_text()
		for name in ("wsp-sheet-links", "wsp-sheet-link", "wsp-sheet-link__tag", "wsp-sheet-link__name"):
			self.assertIn(f".{name}", css, name)
		block = css[css.index(".wsp-product .wsp-sheet-links {") :]
		block = block[: block.index("@media (pointer: coarse)")]
		# ink only: a ground would need its own pair of colours on a dark chrome (test_stylesheet_inks)
		self.assertNotRegex(block, r"background")
		self.assertNotRegex(block, r"#[0-9a-fA-F]{3,8}\b")
