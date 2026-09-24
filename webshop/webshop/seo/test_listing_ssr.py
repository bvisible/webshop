# //// Neoffice — added file (no upstream equivalent): the first page of a listing, rendered on the
# //// server (product_data_engine/listing_context.py server_listing, templates/includes/
# //// listing_ssr.html). neoffice-maintenance#691 (lot 2, D14), 2026-09-24.
"""A listing a crawler can read without JavaScript: the cards of its first page and real links to
the others. Before this, a category, /all-products and /occasions held no product and no page link
in their HTML: every card came from the script, and the pager was made of buttons."""

from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.product_data_engine import listing_context
from webshop.webshop.seo import meta

TEMPLATE = Path(__file__).resolve().parents[2] / "templates" / "includes" / "listing_ssr.html"


class _FormDict:
	"""frappe.form_dict for one test."""

	def __init__(self, **values):
		self.values = frappe._dict(values)

	def __enter__(self):
		self.saved = frappe.local.form_dict
		frappe.local.form_dict = self.values

	def __exit__(self, *args):
		frappe.local.form_dict = self.saved


def _labels(pager):
	return [("…" if link.gap else link.label) + ("*" if link.current else "") for link in pager.links]


class TestPager(FrappeTestCase):
	def test_one_page_needs_no_pager(self):
		self.assertIsNone(listing_context.pager("/all-products", 0, 12, 12))
		self.assertIsNone(listing_context.pager("/all-products", 0, 12, 0))

	def test_the_script_s_window_first_last_previous_next(self):
		first = listing_context.pager("/all-products", 0, 12, 120)
		self.assertEqual(_labels(first), ["1*", "2", "3", "4", "5", "6", "7", "…", "10", "›"])
		middle = listing_context.pager("/all-products", 48, 12, 120)
		self.assertEqual(_labels(middle), ["‹", "1", "2", "3", "4", "5*", "6", "7", "8", "…", "10", "›"])
		last = listing_context.pager("/all-products", 108, 12, 120)
		self.assertEqual(_labels(last), ["‹", "1", "…", "4", "5", "6", "7", "8", "9", "10*"])

	def test_page_one_is_the_listing_itself_and_the_others_carry_their_start(self):
		links = listing_context.pager("/shop/shoes", 12, 12, 40).links
		hrefs = {link.label: link.href for link in links if not link.gap}
		self.assertEqual(hrefs["1"], "/shop/shoes")
		self.assertEqual(hrefs["3"], "/shop/shoes?start=24")
		self.assertEqual([link.rel for link in links if link.rel], ["prev", "next"])


class TestServerListing(FrappeTestCase):
	PAYLOAD = {"items": [{"card_html": "<div class='wsp-card'>A</div>"}, {"card_html": "<div>B</div>"}], "total_count": 30}

	def listing(self, form=None, payload=None, **kwargs):
		with (
			_FormDict(**(form or {})),
			patch("webshop.webshop.api.get_product_filter_data", return_value=payload or self.PAYLOAD) as api,
		):
			result = listing_context.server_listing("/all-products", **kwargs)
		return result, api

	def test_the_first_page_as_the_script_asks_for_it(self):
		settings = frappe._dict(
			products_per_page=12,
			enable_stock_filter=1,
			stock_filter_default_checked=1,
			default_product_sort="new_arrivals",
		)
		with patch("frappe.get_cached_doc", return_value=settings):
			result, api = self.listing(
				form={"start": "12"}, locked_field_filters={"item_condition": ["Second-hand"]}
			)
		args = api.call_args.args[0]
		self.assertEqual(args["start"], 12)
		self.assertEqual(args["sort_order"], "new_arrivals")
		self.assertEqual(args["field_filters"], {"item_condition": ["Second-hand"], "in_stock": ["1"]})
		self.assertEqual(len(result.cards), 2)
		self.assertEqual((result.total, result.pager.current, result.pager.pages), (30, 2, 3))

	def test_a_searched_or_filtered_listing_stays_the_script_s(self):
		for form in ({"search": "shoe"}, {"field_filters": '{"brand": ["X"]}'}, {"attribute_filters": "{}"}):
			with self.subTest(form=form):
				result, api = self.listing(form=form)
				self.assertIsNone(result)
				api.assert_not_called()

	def test_a_page_beyond_the_last_one_does_not_exist(self):
		with self.assertRaises(frappe.PageDoesNotExistError):
			self.listing(form={"start": "480"}, payload={"items": [], "total_count": 30})
		# the first page of an empty listing is the listing, empty
		result, _api = self.listing(payload={"items": [], "total_count": 0})
		self.assertEqual(result.cards, [])


class TestCanonical(FrappeTestCase):
	def test_each_page_is_its_own_reference_and_a_facet_is_the_listing(self):
		with patch("webshop.webshop.seo.meta.site_url", side_effect=lambda path: "https://shop.test" + path):
			with _FormDict(start="24"):
				self.assertEqual(meta.listing_canonical("/all-products"), "https://shop.test/all-products?start=24")
			with _FormDict(start="24", field_filters='{"brand": ["X"]}'):
				self.assertEqual(meta.listing_canonical("/all-products"), "https://shop.test/all-products")
			with _FormDict():
				self.assertEqual(meta.listing_canonical("/shop/shoes"), "https://shop.test/shop/shoes")


class TestTemplate(FrappeTestCase):
	def render(self, listing_ssr):
		return frappe.render_template(TEMPLATE.read_text(), {"listing_ssr": listing_ssr})

	def test_cards_and_page_links_a_crawler_can_follow(self):
		listing = frappe._dict(
			cards=["<div class='wsp-card'><a href='/shop/trail-shoe'>Trail shoe</a></div>"],
			total=30,
			pager=listing_context.pager("/all-products", 0, 12, 30),
		)
		html = self.render(listing)
		self.assertIn("<a href='/shop/trail-shoe'>Trail shoe</a>", html)
		self.assertIn('<a class="btn btn-default btn-page" href="/all-products?start=12">2</a>', html)
		self.assertIn('aria-current="page">1</span>', html)
		self.assertIn('rel="next"', html)
		# an old handler of the listing templates binds these classes and would send start=undefined
		self.assertNotIn("btn-prev", html)
		self.assertNotIn("btn-next", html)
		self.assertNotIn("itemscope", html)

	def test_nothing_without_cards(self):
		self.assertEqual(self.render(None).strip(), "")
		self.assertEqual(self.render(frappe._dict(cards=[], total=0, pager=None)).strip(), "")


class TestBeyondTheLastPage(FrappeTestCase):
	def test_a_www_listing_answers_404_itself(self):
		"""frappe renders a PageDoesNotExistError raised during a render at the request's own
		status, 200 (serve.handle_exception): the listing sets its status instead."""
		context = frappe._dict(metatags={})
		with (
			_FormDict(start="999999"),
			patch(
				"webshop.webshop.product_data_engine.listing_context.server_listing",
				side_effect=frappe.PageDoesNotExistError,
			),
			patch("webshop.webshop.shopping_cart.guest_cart.check_and_merge_guest_cart"),
		):
			listing_context.build_listing_context(context, "All Products")
		self.assertEqual(context.http_status_code, 404)
		self.assertIsNone(context.listing_ssr)
		self.assertEqual(context.metatags.get("robots"), "noindex, follow")
