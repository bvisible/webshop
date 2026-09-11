# //// Neoffice — added file (no upstream equivalent).
"""The one product card, in each of its variants.

The macro in templates/includes/product_card.html replaced three hand-kept copies
(grid.js, list.js, the carousel's Jinja, the wishlist macro). These tests render it
with an in-memory item and in-memory settings — nothing is written to the site —
and check the hooks the stylesheet, the cart and the wishlist handlers read.
"""

import re

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.utils.product_card import attach_cards, render_product_card


def _item(**overrides):
	item = frappe._dict(
		name="WEB-ITEM-0001",
		item_code="ITEM-0001",
		web_item_name="A very fine product",
		item_name="A very fine product",
		route="products/a-very-fine-product",
		item_group="Products",
		website_image="/files/product.png",
		formatted_price="CHF 120.00",
		in_stock=1,
		stock_qty=12,
		has_variants=0,
		wished=0,
		in_cart=0,
	)
	item.update(overrides)
	return item


def _settings(**overrides):
	settings = frappe._dict(
		enabled=1,
		enable_checkout=1,
		enable_wishlist=1,
		enable_guest_cart=1,
		show_stock_availability=1,
		allow_items_not_in_stock=0,
		product_image_fit="Contain",
		product_image_aspect_ratio="1/1",
	)
	settings.update(overrides)
	return settings


class TestProductCard(FrappeTestCase):
	def test_grid_carries_every_hook_the_handlers_read(self):
		html = render_product_card(_item(), _settings(), "grid")
		self.assertIn('class="col-sm-4 item-card wsp-card wsp-card--grid"', html)
		self.assertIn('class="product-title wsp-card__title"', html)
		self.assertIn("A very fine product", html)
		self.assertIn('data-item-code="ITEM-0001"', html)
		self.assertIn("like-action", html)
		self.assertIn("cart-indicator", html)
		self.assertIn("btn-add-to-cart-list", html)
		self.assertIn("go-to-cart-grid", html)
		self.assertIn("CHF 120.00", html)
		self.assertIn('class="stock-badge in-stock"', html)
		self.assertIn("(12)", html)

	def test_wishlist_and_cart_controls_follow_the_settings(self):
		html = render_product_card(_item(), _settings(enable_wishlist=0, enabled=0), "grid")
		self.assertNotIn("like-action", html)
		self.assertNotIn("cart-indicator", html)
		self.assertNotIn("btn-add-to-cart-list", html)

	def test_a_variant_parent_and_a_gift_card_are_explored_not_bought(self):
		for overrides in ({"has_variants": 1}, {"is_gift_card": 1}):
			html = render_product_card(_item(**overrides), _settings(), "grid")
			self.assertIn("btn-explore-variants", html)
			self.assertNotIn("btn-add-to-cart-list", html)
		self.assertNotIn("product-price", render_product_card(_item(is_gift_card=1), _settings(), "grid"))

	def test_stock_words_are_written_not_only_coloured(self):
		low = render_product_card(_item(stock_qty=3), _settings(), "grid")
		self.assertIn('class="stock-badge low-stock"', low)
		self.assertIn("(3)", low)
		gone = render_product_card(_item(in_stock=0, stock_qty=0), _settings(), "grid")
		self.assertIn('class="stock-badge out-of-stock"', gone)
		self.assertIn(frappe._("Out of stock"), gone)
		self.assertNotIn("btn-add-to-cart-list", gone)
		sold = render_product_card(_item(in_stock=0, stock_qty=0, item_condition="Second-hand"), _settings(), "grid")
		self.assertIn(frappe._("Sold"), sold)
		self.assertIn("condition-badge", sold)

	def test_discount_badge_and_struck_price(self):
		html = render_product_card(
			_item(discount_percent=20.0, discount="20%", formatted_mrp="CHF 150.00"), _settings(), "grid"
		)
		self.assertIn("- 20%", html)
		self.assertIn("<s>CHF150.00</s>", html)
		self.assertIn("product-info-green", html)

	def test_cover_fit_writes_the_focus_inline(self):
		html = render_product_card(
			_item(image_focus="Top Left"), _settings(product_image_fit="Cover", product_image_aspect_ratio="4/5"), "grid"
		)
		self.assertIn("aspect-ratio: 4/5;", html)
		self.assertIn("object-position: left top;", html)
		self.assertNotIn("aspect-ratio", render_product_card(_item(), _settings(), "grid"))

	def test_list_row_keeps_its_own_hooks(self):
		html = render_product_card(_item(short_description="Short and sweet"), _settings(), "list")
		self.assertIn("list-row", html)
		self.assertIn("like-action-list", html)
		self.assertIn("cart-action-container", html)
		self.assertIn("list-indicator", html)
		self.assertIn("go-to-cart", html)
		self.assertIn("Short and sweet", html)
		self.assertIn(frappe._("Item Code"), html)

	def test_carousel_has_no_control_a_builder_page_could_not_serve(self):
		html = render_product_card(_item(price=120, currency="CHF"), {}, "carousel")
		self.assertIn("wsp-card--carousel", html)
		self.assertNotIn("col-sm-4", html)
		self.assertNotIn("like-action", html)
		self.assertNotIn("cart-indicator", html)
		self.assertNotIn("btn-add-to-cart-list", html)
		self.assertIn("btn-explore-variants", html)
		self.assertIn("120", html)

	def test_wishlist_card_offers_the_move_and_the_cross(self):
		html = render_product_card(
			_item(image="/files/product.png", available=1), _settings(), "wishlist", cart_settings=_settings()
		)
		self.assertIn("wishlist-card", html)
		self.assertIn("remove-wish", html)
		self.assertIn(frappe._("Move to Cart"), html)
		gone = render_product_card(_item(available=0), _settings(), "wishlist", cart_settings=_settings())
		self.assertIn("out-of-stock", gone)
		self.assertNotIn("btn-add-to-cart", gone)

	def test_the_title_is_escaped_and_cut(self):
		html = render_product_card(_item(web_item_name="<b>" + "x" * 100), _settings(), "grid")
		self.assertNotIn("<b>", html)
		self.assertIn("&lt;b&gt;", html)
		self.assertRegex(html, r"x{87}\.\.\.")

	def test_attach_cards_gives_every_item_both_tiles(self):
		items = [_item(), _item(item_code="ITEM-0002", name="WEB-ITEM-0002")]
		attach_cards(items, _settings())
		for item in items:
			self.assertIn("wsp-card--grid", item["card_html"])
			self.assertIn("wsp-card--list", item["list_html"])
		self.assertEqual(len(re.findall('data-item-code="ITEM-0002"', items[1]["card_html"])), 4)
