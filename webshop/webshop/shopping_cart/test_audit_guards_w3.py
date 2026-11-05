# //// Neoffice — added file (no upstream equivalent).
# Copyright (c) 2026, Neoffice and contributors
# License: GNU General Public License v3. See license.txt
"""What a stranger may not do to the shop, and what its own people keep doing (neoffice-maintenance#2296).

Each guard has its two sides here: the account or the request that is refused, and the one that must still
pass. The shop's scripts are played with node against a stub of the page: what they print is read, not their
source.
"""

import contextlib
import json
import os
import re
import shutil
import subprocess
from unittest.mock import patch

import frappe
from frappe.core.doctype.user_permission.test_user_permission import create_user
from frappe.tests.utils import FrappeTestCase
from frappe.utils import set_request
from frappe.utils.typing_validations import FrappeTypeError
from frappe.website.serve import get_response

import webshop.hooks
from webshop.templates.pages import product_search
from webshop.webshop.doctype.item_review import item_review
from webshop.webshop.doctype.website_item import website_item
from webshop.webshop.doctype.website_item.website_item import make_website_item
from webshop.webshop.doctype.webshop_settings import webshop_settings
from webshop.webshop.report.shop_assistant_usage import shop_assistant_usage
from webshop.webshop.seo import sitemaps
from webshop.webshop.seo.feeds import google
from webshop.webshop.shopping_cart import product_info
from webshop.webshop.tests.utils import PREFIX, make_test_item, portal_customer
from webshop.webshop.utils import builder, utils

USER = "wstest-w3-customer@yopmail.com"
CUSTOMER = f"{PREFIX} W3 Customer"
OTHER_USER = "wstest-w3-other@yopmail.com"
OTHER_CUSTOMER = f"{PREFIX} W3 Other"
STOCK_USER = "wstest-w3-stock@yopmail.com"
WEBSITE_MANAGER = "wstest-w3-web@yopmail.com"
SALES_USER = "wstest-w3-sales@yopmail.com"
ITEM = f"{PREFIX} W3 Item"
HIDDEN_ITEM = f"{PREFIX} W3 Hidden"
MODEL = f"{PREFIX} W3 Model"
VARIANT = f"{PREFIX} W3 Variant"

TAG = "<img src=x onerror=alert(1)>"
QUOTED_TAG = json.dumps(TAG)
ATTRIBUTE = 'x" onload="alert(1)//'

UTILS = "webshop.webshop.utils.utils"
PRODUCT_INFO = "webshop.webshop.shopping_cart.product_info"
REVIEW = "webshop.webshop.doctype.item_review.item_review"
OFFER = "webshop.webshop.doctype.website_offer.website_offer.get_offer_details"
WAREHOUSES = "webshop.webshop.doctype.website_item.website_item.get_item_warehouses"
SETTINGS = "webshop.webshop.doctype.webshop_settings.webshop_settings"
SEARCH = "webshop.templates.pages.product_search"
BUILDER_CONTENT = "webshop.webshop.utils.builder.get_builder_page_content"


def http(path, **kwargs):
	"""The way the HTTP handler calls a method."""
	method = frappe.get_attr(path)
	frappe.is_whitelisted(method)
	return frappe.call(method, **kwargs)


def app_file(*parts):
	return os.path.join(frappe.get_app_path("webshop"), *parts)


def read_app_file(*parts):
	with open(app_file(*parts)) as source:
		return source.read()


@contextlib.contextmanager
def nothing_stays():
	"""A method under test that commits and clears the caches, played in a transaction that is thrown away."""
	frappe.db.savepoint("audit_w3")
	with patch.object(frappe.local.db, "commit"), patch("frappe.clear_cache"):
		try:
			yield
		finally:
			frappe.db.rollback(save_point="audit_w3")


@contextlib.contextmanager
def over_http(method):
	"""frappe.local.form_dict as the handler leaves it while it serves `method`."""
	saved = frappe.local.form_dict
	frappe.local.form_dict = frappe._dict(cmd=method)
	try:
		yield
	finally:
		frappe.local.form_dict = saved


def page(path, **query):
	"""What a visitor receives for `path`, through the website router."""
	set_request(method="GET", path=path, base_url="http://audit-w3.test")
	frappe.form_dict.clear()
	frappe.form_dict.update(query)
	try:
		response = get_response()
		return response.status_code, response.get_data(as_text=True)
	finally:
		frappe.local.request = None
		frappe.form_dict.clear()
		frappe.clear_messages()


class Fixture(FrappeTestCase):
	"""Two portal customers, the staff, a published item and a hidden one."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		muted = frappe.flags.mute_emails
		frappe.flags.mute_emails = True
		cls.addClassCleanup(setattr, frappe.flags, "mute_emails", muted)
		portal_customer(USER, CUSTOMER)
		portal_customer(OTHER_USER, OTHER_CUSTOMER)
		for email in (USER, OTHER_USER):
			frappe.get_doc("User", email).add_roles("Customer")
		create_user(STOCK_USER, "Stock User")
		create_user(WEBSITE_MANAGER, "Website Manager")
		create_user(SALES_USER, "Sales User")
		cls.web_item = cls.published(ITEM)
		cls.hidden_web_item = cls.published(HIDDEN_ITEM, published=0)
		frappe.set_user("Administrator")

	@classmethod
	def published(cls, code, published=1, **properties):
		item = make_test_item(code, **properties)
		if not frappe.db.get_value("Website Item", {"item_code": code}):
			make_website_item(item, save=True)
		name = frappe.db.get_value("Website Item", {"item_code": code})
		frappe.db.set_value("Website Item", name, {"published": published, "sold": 0})
		return name

	def tearDown(self):
		frappe.set_user("Administrator")


class TestFirstName(Fixture):
	METHOD = f"{UTILS}.get_first_name"

	def test_a_guest_learns_nothing_about_an_account(self):
		frappe.set_user("Guest")
		self.assertIsNone(http(self.METHOD, user=USER))

	def test_a_filter_for_an_account_is_refused_before_the_body_runs(self):
		frappe.set_user("Guest")
		for shape in ({"name": ["like", "%"]}, {"name": USER}, ["like", "%"]):
			with self.subTest(shape=shape), self.assertRaises(FrappeTypeError):
				http(self.METHOD, user=shape)

	def test_a_customer_reads_their_own_name_and_no_other(self):
		frappe.set_user(USER)
		self.assertEqual(http(self.METHOD, user=USER), CUSTOMER)
		self.assertEqual(http(self.METHOD), CUSTOMER)
		self.assertIsNone(http(self.METHOD, user=OTHER_USER))
		self.assertIsNone(http(self.METHOD, user="_no-such-account@yopmail.com"), "whether it exists shows nothing")

	def test_the_staff_keep_reading_a_name(self):
		self.assertEqual(http(self.METHOD, user=USER), CUSTOMER)


class TestMaintenanceUtilities(Fixture):
	ACTS = (
		("warehouse_update.update_all_website_items_warehouse", {"warehouse_name": "warehouse"}),
		("warehouse_update.update_website_items_warehouse_by_item_group", {"warehouse_name": "warehouse"}),
		("route_regeneration.regenerate_all_website_item_routes", {}),
		("route_regeneration.regenerate_routes_for_item_group", {"item_group": "_no such group"}),
		("variant_update.update_website_items_variant_of", {}),
		("variant_update.fix_inconsistent_variants", {}),
		("sync_creation_dates.sync_creation_dates_from_items", {}),
		("sync_creation_dates.update_specific_website_item_date", {"website_item_name": "_no such item"}),
	)
	READS = (
		("route_regeneration.check_duplicate_routes", {}),
		("variant_update.get_variant_statistics", {}),
		("sync_creation_dates.preview_creation_date_changes", {}),
		("sync_creation_dates.get_newest_products", {}),
	)

	def arguments(self, kwargs):
		warehouse = frappe.get_all("Warehouse", pluck="name", limit=1)[0]
		return {key: warehouse if value == "warehouse" else value for key, value in kwargs.items()}

	def test_a_portal_customer_is_refused_every_one_of_them(self):
		for name, kwargs in self.ACTS + self.READS:
			with self.subTest(method=name), nothing_stays():
				arguments = self.arguments(kwargs)
				frappe.set_user(USER)
				with self.assertRaises(frappe.PermissionError):
					http(f"webshop.webshop.utils.{name}", **arguments)
			frappe.set_user("Administrator")

	def test_the_stock_team_keeps_the_tools(self):
		with nothing_stays():
			warehouse = frappe.get_all("Warehouse", pluck="name", limit=1)[0]
			frappe.set_user(STOCK_USER)
			answer = http(
				"webshop.webshop.utils.warehouse_update.update_website_items_warehouse_by_item_group",
				warehouse_name=warehouse,
				item_group="_no such group",
			)
			self.assertEqual(answer["total_items"], 0)
			self.assertIn("duplicates", str(http("webshop.webshop.utils.route_regeneration.check_duplicate_routes")))


class TestGatewayConfiguration(Fixture):
	def test_no_path_leaves_the_apps(self):
		self.assertEqual(utils.get_gateway_configuration("../../../../../sites/common_site_config"), {})

	def test_a_stored_template_path_cannot_leave_the_apps_either(self):
		method = frappe._dict(template_path="apps/webshop/../../../sites/common_site_config.html")
		with patch("frappe.get_doc", return_value=method), patch("frappe.log_error") as logged:
			self.assertEqual(utils.get_gateway_configuration("stripe", "an account"), {})
		logged.assert_called_once()

	def test_the_configuration_of_a_method_still_reads(self):
		self.assertTrue(utils.get_gateway_configuration("stripe"))

	def test_a_custom_template_path_still_reads_its_json(self):
		method = frappe._dict(template_path="apps/webshop/webshop/templates/payments/stripe.html")
		with patch("frappe.get_doc", return_value=method):
			self.assertEqual(
				utils.get_gateway_configuration("anything", "an account"), utils.get_gateway_configuration("stripe")
			)

	def test_a_template_cannot_ask_for_it(self):
		methods = webshop.hooks.jinja["methods"]
		self.assertNotIn(UTILS, methods, "the whole module: every function in it is a template global")
		self.assertNotIn(f"{UTILS}.get_gateway_configuration", methods)

	def test_the_helpers_of_the_templates_stay(self):
		methods = webshop.hooks.jinja["methods"]
		for name in (
			"format_currency_value",
			"webshop_fmt_money",
			"get_user_header_info",
			"get_user_avatar_html",
			"get_first_name",
			"description_excerpt",
		):
			with self.subTest(helper=name):
				self.assertIn(f"{UTILS}.{name}", methods)
				self.assertTrue(callable(frappe.get_attr(f"{UTILS}.{name}")))


class TestReviewsPrint(FrappeTestCase):
	def rendered(self, **review):
		row = frappe._dict(
			review_title="A title",
			comment="A comment",
			customer="A customer",
			published_on="1 November 2026",
			rating=0.8,
			verified_purchase=1,
		)
		row.update(review)
		return frappe.render_template(
			'{% from "webshop/templates/includes/macros.html" import user_review %}{{ user_review(reviews) }}',
			{"reviews": [row]},
		)

	def test_what_a_customer_wrote_is_text(self):
		for field in ("review_title", "comment", "customer"):
			with self.subTest(field=field):
				html = self.rendered(**{field: QUOTED_TAG})
				self.assertNotIn("<img", html)
				self.assertIn("&lt;img", html)

	def test_an_ordinary_review_reads_as_it_was_written(self):
		html = self.rendered(review_title="Solid & light", comment="Works well", customer="R&D Ltd")
		self.assertIn("Solid &amp; light", html)
		self.assertIn("Works well", html)
		self.assertIn("R&amp;D Ltd", html)
		self.assertIn("4/5", html)


class TestCatalogueMarkup(FrappeTestCase):
	"""A catalogue field holds text: printed in an attribute or between two tags, it stays text."""

	TEMPLATES = (
		"templates/includes/macros.html",
		"templates/includes/cart/cart_items.html",
		"templates/includes/order_summary_items.html",
		"templates/generators/item/item.html",
		"templates/generators/item/item_add_to_cart.html",
		"templates/generators/item/item_bundle_components.html",
		"templates/generators/item/item_configure.html",
		"templates/generators/item/item_details.html",
		"templates/generators/item/item_image.html",
	)
	FIELDS = re.compile(
		r"web_item_name|website_image_alt|\bp\.alt\b|\bp\.image\b|photos\[0\]\.(?:alt|image)|offer_title"
	)
	# not printed as such: data for a script, a first letter, a value handed to a macro or to a function
	NOT_PRINTED = re.compile(r"\|\s*e\b|\|\s*tojson|\|\s*upper|get_abbr|picture_attrs\(")

	def card(self, **item):
		return frappe.render_template(
			'{% from "webshop/templates/includes/macros.html" import item_card %}{{ item_card(item) }}',
			{"item": frappe._dict(route="a-product", website_image="/files/a.png", **item)},
		)

	def test_no_catalogue_field_is_printed_raw(self):
		for template in self.TEMPLATES:
			source = read_app_file(template)
			for printed in re.findall(r"\{\{.*?\}\}", source):
				if self.FIELDS.search(printed):
					with self.subTest(template=template, printed=printed):
						self.assertRegex(printed, self.NOT_PRINTED)

	def test_a_name_cannot_leave_its_attribute(self):
		html = self.card(web_item_name=ATTRIBUTE)
		self.assertNotIn('" onload="', html)
		self.assertIn("&#34;", html)

	def test_a_picture_or_an_address_cannot_either(self):
		html = frappe.render_template(
			'{% from "webshop/templates/includes/macros.html" import item_card %}{{ item_card(item) }}',
			{"item": frappe._dict(web_item_name="A", route=ATTRIBUTE, website_image=ATTRIBUTE)},
		)
		self.assertNotIn('" onload="', html)

	def test_a_name_with_an_ampersand_stays_a_name(self):
		self.assertIn('alt="Salt &amp; pepper"', self.card(web_item_name="Salt & pepper"))

	def test_the_cart_line_keeps_its_picture_and_name(self):
		doc = frappe.new_doc("Quotation")
		doc.currency = "CHF"
		line = doc.append("items", {"item_code": "_no such item", "item_name": "A", "qty": 1, "rate": 1})
		line.web_item_name = ATTRIBUTE
		line.website_image = "/files/a.png"
		html = frappe.render_template(
			"webshop/templates/includes/cart/cart_items.html", {"doc": doc, "cart_settings": frappe._dict()}
		)
		self.assertIn('src="', html)
		self.assertNotIn('" onload="', html)


class TestReviewRights(Fixture):
	def setUp(self):
		self.addCleanup(frappe.cache().hdel, "item_reviews", self.web_item)
		frappe.cache().hdel("item_reviews", self.web_item)
		frappe.set_user("Administrator")
		frappe.db.delete("Item Review", {"website_item": self.web_item})
		self.settings = patch.object(
			item_review, "get_shopping_cart_settings", return_value=frappe._dict(enable_reviews=1)
		)
		self.settings.start()
		self.addCleanup(self.settings.stop)

	def posted(self, user=USER):
		frappe.set_user(user)
		http(f"{REVIEW}.add_item_review", web_item=self.web_item, title="Good", rating=0.8, comment="Fine")
		frappe.set_user("Administrator")

	def test_a_customer_has_no_right_on_the_doctype(self):
		rules = json.loads(read_app_file("webshop/doctype/item_review/item_review.json"))["permissions"]
		self.assertNotIn("Customer", [rule["role"] for rule in rules])

	def test_a_customer_still_posts_through_the_shop(self):
		self.posted()
		review = frappe.get_all(
			"Item Review",
			filters={"website_item": self.web_item},
			fields=["user", "customer", "verified_purchase"],
		)
		self.assertEqual(len(review), 1)
		self.assertEqual(review[0].user, USER)
		self.assertEqual(review[0].customer, CUSTOMER)
		self.assertEqual(review[0].verified_purchase, 0, "the badge comes from the orders, never from the request")

	def test_a_second_review_of_one_customer_writes_nothing(self):
		self.posted()
		self.posted()
		self.assertEqual(frappe.db.count("Item Review", {"website_item": self.web_item}), 1)

	def test_a_filter_for_an_item_is_refused(self):
		frappe.set_user(USER)
		with self.assertRaises(FrappeTypeError):
			http(f"{REVIEW}.add_item_review", web_item={"name": "x"}, title="Good", rating=0.8)
		with self.assertRaises(FrappeTypeError):
			http(f"{REVIEW}.get_item_reviews", web_item=["like", "%"])

	def test_the_reviews_name_no_address(self):
		self.posted()
		frappe.set_user(OTHER_USER)
		answer = http(f"{REVIEW}.get_item_reviews", web_item=self.web_item)
		self.assertEqual(len(answer["reviews"]), 1)
		text = frappe.as_json(answer["reviews"])
		for address in (USER, "Administrator"):
			self.assertNotIn(address, text)
		self.assertFalse({"user", "owner", "modified_by", "name"} & set(answer["reviews"][0]))

	def test_a_page_already_in_the_cache_names_no_address_either(self):
		stale = frappe._dict(
			reviews=[frappe._dict(user=USER, owner=USER, modified_by=USER, review_title="Good", rating=0.8)],
			average_rating=4,
			total_reviews=1,
		)
		frappe.cache().hset("item_reviews", self.web_item, stale)
		answer = http(f"{REVIEW}.get_item_reviews", web_item=self.web_item)
		self.assertNotIn(USER, frappe.as_json(answer))
		self.assertEqual(answer["reviews"][0]["review_title"], "Good")

	def test_a_page_of_reviews_has_a_limit(self):
		self.posted()
		with patch.object(item_review, "get_queried_reviews", wraps=item_review.get_queried_reviews) as query:
			http(f"{REVIEW}.get_item_reviews", web_item=self.web_item, start=1, end=0)
		self.assertTrue(0 < query.call_args.args[2] <= item_review.MAX_REVIEWS_PER_PAGE)

	def test_the_pages_read_what_they_print(self):
		self.posted()
		answer = item_review.get_item_reviews(self.web_item)
		row = answer.reviews[0]
		for field in item_review.REVIEW_FIELDS:
			self.assertIn(field, row)
		self.assertTrue(row.review_title and row.comment and row.rating and row.customer and row.creation)
		self.assertTrue(answer.average_rating)


class TestItemWarehouses(Fixture):
	def test_a_portal_customer_reads_no_stock(self):
		frappe.set_user(USER)
		with self.assertRaises(frappe.PermissionError):
			http(WAREHOUSES, item_code=ITEM)

	def test_a_filter_for_a_code_is_refused(self):
		with self.assertRaises(FrappeTypeError):
			http(WAREHOUSES, item_code=["like", "%"])

	def test_whoever_reads_the_stock_or_publishes_keeps_it(self):
		for user in (STOCK_USER, WEBSITE_MANAGER):
			frappe.set_user(user)
			with self.subTest(user=user):
				self.assertEqual(http(WAREHOUSES, item_code=ITEM), [])

	def test_a_page_a_guest_reads_keeps_its_stock(self):
		frappe.set_user("Guest")
		self.assertEqual(website_item.stock_by_warehouse(ITEM), [])


class TestSearchLimits(Fixture):
	def test_a_page_of_the_grid_has_a_limit(self):
		frappe.set_user("Guest")
		with patch.object(product_search, "get_product_data", return_value=[]) as data:
			http(f"{SEARCH}.get_product_list", limit=100000)
		self.assertLessEqual(data.call_args.args[2], product_search.MAX_PAGE_LENGTH)

	def test_a_page_of_the_dropdown_has_a_limit(self):
		frappe.set_user("Guest")
		real = frappe.db.sql
		seen = []

		def spy(query, values=None, *args, **kwargs):
			if isinstance(values, dict) and "limit" in values:
				seen.append(values["limit"])
			return real(query, values, *args, **kwargs)

		with patch.object(frappe.local.db, "sql", spy):
			http(f"{SEARCH}.product_search", query="_no such product", limit=100000)
		self.assertEqual(len(seen), 1)
		self.assertLessEqual(seen[0], product_search.MAX_PAGE_LENGTH)

	def test_the_shop_keeps_its_twelve_cards(self):
		frappe.set_user("Guest")
		with patch.object(product_search, "get_product_data", return_value=[]) as data:
			http(f"{SEARCH}.get_product_list")
		self.assertEqual(data.call_args.args[2], 12)

	def test_a_filter_for_a_search_is_refused(self):
		frappe.set_user("Guest")
		with self.assertRaises(FrappeTypeError):
			http(f"{SEARCH}.get_product_list", search={"a": 1})

	def test_a_connection_that_keeps_asking_is_turned_away(self):
		frappe.set_user("Guest")
		set_request(method="GET", path="/api/method/x", base_url="http://audit-w3.test")
		self.addCleanup(setattr, frappe.local, "request", None)
		with patch("webshop.webshop.utils.throttle.hit", return_value=10**6):
			for method, kwargs in (("get_product_list", {}), ("search", {"query": "x"})):
				with self.subTest(method=method), self.assertRaises(frappe.RateLimitExceededError):
					http(f"{SEARCH}.{method}", **kwargs)

	def test_a_visitor_typing_is_not(self):
		frappe.set_user("Guest")
		set_request(method="GET", path="/api/method/x", base_url="http://audit-w3.test")
		self.addCleanup(setattr, frappe.local, "request", None)
		with patch("webshop.webshop.utils.throttle.hit", return_value=1):
			self.assertEqual(http(f"{SEARCH}.search", query="_no such product")["product_results"], [])


class TestProductHelpers(Fixture):
	INFO = f"{PRODUCT_INFO}.get_product_info_for_website"
	NAME = f"{PRODUCT_INFO}.get_website_item_name"

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("Item Attribute", f"{PREFIX} W3 Size"):
			frappe.get_doc(
				{
					"doctype": "Item Attribute",
					"attribute_name": f"{PREFIX} W3 Size",
					"item_attribute_values": [{"attribute_value": "S", "abbr": "S"}],
				}
			).insert(ignore_permissions=True)
		cls.published(MODEL, has_variants=1, attributes=[{"attribute": f"{PREFIX} W3 Size"}])
		if not frappe.db.exists("Item", VARIANT):
			from erpnext.controllers.item_variant import create_variant

			variant = create_variant(MODEL, {f"{PREFIX} W3 Size": "S"})
			variant.item_code = VARIANT
			variant.insert(ignore_permissions=True)

	def info(self, code):
		settings = frappe._dict(enabled=1, show_price=0, show_stock_availability=0)
		with patch.object(product_info, "get_shopping_cart_settings", return_value=settings), patch.object(
			product_info, "_get_cart_quotation", return_value=frappe._dict()
		), over_http(self.INFO):
			return http(self.INFO, item_code=code, skip_quotation_creation=True)

	def test_a_visitor_reads_nothing_of_an_item_the_shop_does_not_show(self):
		for user in ("Guest", USER):
			frappe.set_user(user)
			for code in (HIDDEN_ITEM, "_no such item"):
				with self.subTest(user=user, code=code):
					self.assertEqual(self.info(code)["product_info"], {})

	def test_a_sold_unit_is_out_of_the_shop(self):
		frappe.db.set_value("Website Item", self.web_item, "sold", 1)
		self.addCleanup(frappe.db.set_value, "Website Item", self.web_item, "sold", 0)
		frappe.set_user("Guest")
		self.assertEqual(self.info(ITEM)["product_info"], {})

	def test_a_visitor_reads_a_product_the_shop_shows(self):
		frappe.set_user("Guest")
		self.assertIn("uom", self.info(ITEM)["product_info"])

	def test_a_variant_is_shown_on_the_page_of_its_model(self):
		frappe.set_user("Guest")
		self.assertIn("uom", self.info(VARIANT)["product_info"])

	def test_the_staff_keep_their_preview(self):
		frappe.set_user(WEBSITE_MANAGER)
		self.assertIn("uom", self.info(HIDDEN_ITEM)["product_info"])

	def test_a_python_caller_keeps_its_answer(self):
		frappe.set_user("Guest")
		settings = frappe._dict(enabled=1, show_price=0, show_stock_availability=0)
		with patch.object(product_info, "get_shopping_cart_settings", return_value=settings):
			answer = product_info.get_product_info_for_website(HIDDEN_ITEM, skip_quotation_creation=True)
		self.assertIn("uom", answer["product_info"])

	def test_a_name_is_read_for_a_product_the_shop_shows(self):
		frappe.set_user("Guest")
		name = frappe.db.get_value("Website Item", self.web_item, "item_name")
		self.assertEqual(http(self.NAME, item_code=ITEM), name)
		self.assertIsNone(http(self.NAME, item_code=HIDDEN_ITEM))

	def test_a_filter_for_a_code_is_refused(self):
		frappe.set_user("Guest")
		with self.assertRaises(FrappeTypeError):
			http(self.NAME, item_code=["like", "%"])

	def test_loyalty_points_are_not_read_for_a_hidden_item(self):
		frappe.set_user("Guest")
		method = "webshop.webshop.utils.loyalty_points.get_item_loyalty_points"
		self.assertFalse(http(method, item_code=HIDDEN_ITEM))
		with self.assertRaises(FrappeTypeError):
			http(method, item_code=["like", "%"])


def closed_catalogue():
	"""login_required_to_view_products on, for what reads it, without a write on the Single."""
	real = frappe.db.get_single_value

	def answer(doctype, field, *args, **kwargs):
		if (doctype, field) == ("Webshop Settings", "login_required_to_view_products"):
			return 1
		return real(doctype, field, *args, **kwargs)

	return patch.object(frappe.local.db, "get_single_value", answer)


class TestClosedCatalogue(Fixture):
	PAGES = ("/all-products", "/occasions", "/shop-by-category")

	def group_route(self):
		return "/" + frappe.db.get_value("Item Group", {"show_in_website": 1, "route": ["is", "set"]}, "route")

	def test_a_guest_reads_no_listing_of_a_closed_catalogue(self):
		frappe.set_user("Guest")
		with closed_catalogue():
			for path in (*self.PAGES, self.group_route()):
				with self.subTest(path=path):
					status, html = page(path)
					self.assertEqual(status, 403)
					self.assertIn("/login", html)

	def test_a_signed_in_customer_reads_them(self):
		frappe.set_user(USER)
		with closed_catalogue():
			for path in self.PAGES:
				with self.subTest(path=path):
					self.assertEqual(page(path)[0], 200)

	def test_an_open_catalogue_stays_open_to_a_guest(self):
		frappe.set_user("Guest")
		for path in (*self.PAGES, self.group_route()):
			with self.subTest(path=path):
				self.assertEqual(page(path)[0], 200)

	def test_the_shop_search_of_a_closed_catalogue_answers_nothing_to_a_guest(self):
		frappe.set_user("Guest")
		with closed_catalogue():
			self.assertEqual(http(f"{SEARCH}.search", query=ITEM)["product_results"], [])

	def test_nor_does_the_offer_of_a_product(self):
		offer = website_offer(self.web_item)
		frappe.set_user("Guest")
		with closed_catalogue():
			self.assertIsNone(http(OFFER, offer_id=offer))

	def test_the_sitemaps_of_a_closed_catalogue_list_no_product(self):
		frappe.set_user("Guest")
		with closed_catalogue():
			self.assertEqual(sitemaps.product_links(), [])
			self.assertEqual(sitemaps.category_links(), [])
			self.assertEqual(sitemaps.brand_links(), [])

	def test_a_closed_catalogue_has_no_feed(self):
		shop = frappe._dict(enabled=1, show_price=1, hide_price_for_guest=0, login_required_to_view_products=1)
		self.assertTrue(google.site_refusal(shop))


def website_offer(web_item):
	row = frappe.get_doc(
		{
			"doctype": "Website Offer",
			"name": frappe.generate_hash(length=10),
			"parent": web_item,
			"parenttype": "Website Item",
			"parentfield": "offers",
			"offer_title": "An offer",
			"offer_details": "The details",
		}
	)
	row.db_insert()
	return row.name


class TestOffer(Fixture):
	def test_a_filter_for_an_offer_is_refused(self):
		frappe.set_user("Guest")
		with self.assertRaises(FrappeTypeError):
			http(OFFER, offer_id=["like", "%"])

	def test_the_offer_of_a_published_item_reads(self):
		offer = website_offer(self.web_item)
		frappe.set_user("Guest")
		self.assertEqual(http(OFFER, offer_id=offer), "The details")

	def test_the_offer_of_a_hidden_item_does_not(self):
		offer = website_offer(self.hidden_web_item)
		frappe.set_user("Guest")
		self.assertIsNone(http(OFFER, offer_id=offer))

	def test_the_staff_see_it_on_their_preview(self):
		offer = website_offer(self.hidden_web_item)
		frappe.set_user(WEBSITE_MANAGER)
		self.assertEqual(http(OFFER, offer_id=offer), "The details")


class TestSettingsRights(Fixture):
	def test_a_portal_account_has_no_row_on_the_settings(self):
		rules = json.loads(read_app_file("webshop/doctype/webshop_settings/webshop_settings.json"))["permissions"]
		roles = [rule["role"] for rule in rules]
		self.assertNotIn("All", roles)
		self.assertIn("Desk User", roles, "the forms and the pages of the desk keep reading it")

	def test_the_order_page_reads_the_settings_on_the_server(self):
		rendered = frappe.render_template(read_app_file("templates/pages/order.js"), {})
		self.assertNotIn("frappe.db.get_single_value", rendered)
		self.assertRegex(rendered, r"const payment_gateway_account = (\"[^\"]*\"|\"\"|null);")

	def test_the_buttons_of_the_form_need_a_write_right(self):
		frappe.set_user(STOCK_USER)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Webshop Settings").regenerate_sitemap()
		with self.assertRaises(frappe.PermissionError):
			http(f"{SETTINGS}.regenerate_sitemap")
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Webshop Settings").calculate_frequently_bought_together_items()

	def test_whoever_writes_the_settings_keeps_them(self):
		doc = frappe.get_doc("Webshop Settings")
		with patch("webshop.webshop.seo.sitemaps.clear_caches") as clear, patch.object(
			webshop_settings.WebshopSettings, "db_set"
		) as written:
			self.assertTrue(doc.regenerate_sitemap())
		clear.assert_called_once()
		written.assert_called_once()

	def test_the_shop_renders_for_a_guest(self):
		frappe.set_user("Guest")
		self.assertEqual(page("/all-products")[0], 200)


@contextlib.contextmanager
def rules_of_the_json(doctype, path):
	"""The rows of the doctype's JSON, in place of the ones this site holds until its next migrate."""
	real = frappe.model.meta.get_meta
	meta = frappe.model.meta.load_meta(doctype)
	meta.permissions = [
		frappe._dict({"permlevel": 0, "if_owner": 0, **rule})
		for rule in json.loads(read_app_file(path))["permissions"]
	]

	def answer(name, cached=True):
		return meta if name == doctype else real(name, cached=cached)

	frappe.local.role_permissions = {}
	with patch("frappe.model.meta.get_meta", answer):
		try:
			yield
		finally:
			frappe.local.role_permissions = {}


class TestRightsOfTheJson(Fixture):
	"""What the rows do once a migrate has brought them, on the site's own routes."""

	REVIEW_RULES = ("Item Review", "webshop/doctype/item_review/item_review.json")
	SETTINGS_RULES = ("Webshop Settings", "webshop/doctype/webshop_settings/webshop_settings.json")
	READ = "frappe.client.get_single_value"

	def review(self, **values):
		return frappe.get_doc(
			{"doctype": "Item Review", "website_item": self.web_item, "rating": 1, "user": OTHER_USER, **values}
		)

	def test_a_customer_forges_no_review(self):
		with rules_of_the_json(*self.REVIEW_RULES):
			frappe.set_user(USER)
			with self.assertRaises(frappe.PermissionError):
				self.review(verified_purchase=1).insert()

	def test_a_customer_deletes_no_review(self):
		name = self.review().insert(ignore_permissions=True).name
		self.addCleanup(frappe.delete_doc, "Item Review", name, force=True, ignore_permissions=True)
		with rules_of_the_json(*self.REVIEW_RULES):
			frappe.set_user(USER)
			with self.assertRaises(frappe.PermissionError):
				frappe.delete_doc("Item Review", name)

	def test_a_customer_still_reviews_through_the_shop(self):
		frappe.db.delete("Item Review", {"website_item": self.web_item, "user": USER})
		with rules_of_the_json(*self.REVIEW_RULES):
			frappe.set_user(USER)
			http(f"{REVIEW}.add_item_review", web_item=self.web_item, title="Good", rating=0.8)
		self.assertTrue(frappe.db.exists("Item Review", {"website_item": self.web_item, "user": USER}))

	def test_a_portal_account_reads_no_setting(self):
		with rules_of_the_json(*self.SETTINGS_RULES):
			frappe.set_user(USER)
			with self.assertRaises(frappe.PermissionError):
				http(self.READ, doctype="Webshop Settings", field="google_feed_token")

	def test_a_desk_account_still_does(self):
		with rules_of_the_json(*self.SETTINGS_RULES):
			frappe.set_user(STOCK_USER)
			http(self.READ, doctype="Webshop Settings", field="enabled")

	def test_the_shop_renders_for_a_customer_and_a_guest(self):
		with rules_of_the_json(*self.SETTINGS_RULES):
			for user in (USER, "Guest"):
				frappe.set_user(user)
				for path in ("/all-products", "/shop-by-category", "/cart"):
					with self.subTest(user=user, path=path):
						self.assertEqual(page(path)[0], 200)


class TestUsageReport(Fixture):
	def setUp(self):
		frappe.set_user("Administrator")
		self.rows = [
			frappe.get_doc(
				{
					"doctype": "Shop Assistant Conversation",
					"customer": customer,
					"status": "Open",
					"last_message_on": frappe.utils.now_datetime(),
					"message_count": 2,
				}
			)
			.insert(ignore_permissions=True, ignore_links=True)
			.name
			for customer in (CUSTOMER, OTHER_CUSTOMER)
		]
		self.addCleanup(frappe.db.delete, "Shop Assistant Conversation", {"name": ("in", self.rows)})
		self.limit = frappe.get_doc(
			{"doctype": "User Permission", "user": SALES_USER, "allow": "Customer", "for_value": CUSTOMER}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "User Permission", self.limit.name, force=True)
		frappe.clear_cache(user=SALES_USER)

	def customers(self, user):
		frappe.set_user(user)
		_columns, rows = shop_assistant_usage.execute({"group_by": "Customer"})
		return {row.grouping for row in rows}

	def test_a_limited_seller_reads_the_customers_they_may_read(self):
		customers = self.customers(SALES_USER)
		self.assertIn(CUSTOMER, customers)
		self.assertNotIn(OTHER_CUSTOMER, customers)

	def test_the_managers_read_them_all(self):
		self.assertTrue({CUSTOMER, OTHER_CUSTOMER} <= self.customers(WEBSITE_MANAGER))

	def test_the_counters_of_the_site_are_read_by_who_may_read_them(self):
		day = {"2026-01-02": {"received": 7, "refused": 3}}
		filters = {"from_date": "2026-01-01", "to_date": "2026-01-03"}
		with patch("webshop.webshop.assistant.usage.by_day", return_value=day):
			frappe.set_user(SALES_USER)
			columns, rows = shop_assistant_usage.execute(filters)
			self.assertFalse(rows)
			self.assertNotIn("requests", [column["fieldname"] for column in columns])
			frappe.set_user(WEBSITE_MANAGER)
			columns, rows = shop_assistant_usage.execute(filters)
			self.assertEqual([row.requests for row in rows], [7])
			self.assertIn("requests", [column["fieldname"] for column in columns])


class TestDraftOfBuilder(Fixture):
	def draft(self):
		page_doc = frappe.get_doc(
			{
				"doctype": "Builder Page",
				"page_title": f"{PREFIX} W3 Draft",
				"route": "wstest-w3-draft",
				"published": 0,
				"blocks": "[]",
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "Builder Page", page_doc.name, force=True)
		return page_doc.name

	def test_a_guest_never_gets_a_draft_the_staff_rendered(self):
		name = self.draft()
		frappe.set_user(WEBSITE_MANAGER)
		seen = http(BUILDER_CONTENT, page_name=name, content_only=True)
		self.assertTrue(seen.get("success"), seen)
		frappe.set_user("Guest")
		answer = http(BUILDER_CONTENT, page_name=name, content_only=True)
		self.assertFalse(answer.get("success"), answer)

	def test_a_published_page_is_still_cached(self):
		name = self.draft()
		frappe.db.set_value("Builder Page", name, "published", 1)
		frappe.clear_document_cache("Builder Page", name)
		with patch.object(builder.frappe.cache(), "set_value", wraps=builder.frappe.cache().set_value) as stored:
			http(BUILDER_CONTENT, page_name=name, content_only=True)
		self.assertTrue(any("builder_page_content" in str(call.args[0]) for call in stored.call_args_list))


ESCAPE = """
const escape_map = {
	"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;", "`": "&#x60;", "=": "&#x3D;",
};
const escape_html = (txt) =>
	txt == null ? "" : String(txt).replace(/[&<>"'`=]/g, (c) => escape_map[c] || c);
global.window = global;
global.__ = (text) => text;
global.frappe = {
	utils: {escape_html, get_query_params: () => global.query || {}},
	provide: () => {},
	ready: () => {},
	ui: {form: {on: () => {}}},
	boot: {},
};
global.webshop = {filter_store: {get: () => null, set: () => {}}, shopping_cart: {}};
global.printed = [];
function element() {
	return new Proxy(function () {}, {
		apply: () => element(),
		get(target, name) {
			if (name === "length") return 1;
			if (name === Symbol.toPrimitive) return () => "";
			if (name === "append") return (html) => (global.printed.push(String(html)), element());
			if (name === "hasClass") return () => false;
			if (name === "text" || name === "attr") return () => "";
			return () => element();
		},
	});
}
global.$ = (what) => {
	if (typeof what === "string" && what.trim().startsWith("<")) global.printed.push(what);
	return element();
};
global.document = {dispatchEvent: () => {}, title: ""};
global.CustomEvent = class {};
"""


class TestScripts(FrappeTestCase):
	"""The scripts as a browser runs them: what they hand to the page."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not shutil.which("node"):
			raise cls.failureException("node is needed to play the shop's scripts")

	def play(self, script, **sources):
		"""Run `script` in node with `sources` as global strings; what it prints is its answer."""
		lines = [ESCAPE]
		for name, path in sources.items():
			lines.append(f"const {name} = require('fs').readFileSync({json.dumps(path)}, 'utf8');")
		lines.append(script)
		result = subprocess.run(
			["node", "-e", "\n".join(lines)], capture_output=True, text=True, timeout=30, check=False
		)
		self.assertEqual(result.returncode, 0, result.stderr[-2000:])
		return result.stdout

	def listing(self, method, setup):
		return self.play(
			f"""
			new Function(views)();
			const view = Object.create(webshop.ProductView.prototype);
			{setup}
			view.{method}();
			console.log(JSON.stringify(global.printed));
			""",
			views=app_file("public/js/product_ui/views.js"),
		)

	def test_a_search_in_the_address_stays_text_in_the_breadcrumb(self):
		printed = self.listing("update_page_header_for_search", f"view.search_term = {json.dumps(TAG)};")
		self.assertIn("&lt;img", printed)
		self.assertNotIn("<img", printed)

	def test_filters_in_the_address_stay_text_in_their_chips(self):
		query = {
			"field_filters": json.dumps({"item_group": [f'x"{TAG}']}),
			"attribute_filters": json.dumps({TAG: [TAG]}),
			"price_range": json.dumps({"min": TAG, "max": TAG}),
		}
		printed = self.listing("update_active_filters_display", f"global.query = {json.dumps(query)};")
		self.assertIn("active-filter-badge", printed)
		self.assertNotIn("<img", printed)
		self.assertIn("&lt;img", printed)

	def test_an_ordinary_filter_keeps_its_chip(self):
		query = {"field_filters": json.dumps({"brand": ["Acme"]})}
		printed = self.listing("update_active_filters_display", f"global.query = {json.dumps(query)};")
		self.assertIn('data-filter-value=\\"Acme\\"', printed)

	def test_a_category_name_stays_inside_its_attribute_in_the_settings_form(self):
		nodes = [{"name": ATTRIBUTE, "label": TAG, "weightage": 1, "children": [{"name": "child", "label": "c"}]}]
		printed = self.play(
			f"""
			const render = new Function(form + "; return render_tree_nodes;")();
			render(element(), {json.dumps(nodes)}, 0);
			console.log(JSON.stringify(global.printed));
			""",
			form=app_file("webshop/doctype/webshop_settings/webshop_settings.js"),
		)
		self.assertNotIn('\\" onload=\\"', printed)
		self.assertNotIn("<img", printed)
		self.assertIn("category-tree-item", printed)

	def test_a_review_read_from_the_server_stays_text(self):
		review = {"review_title": TAG, "comment": TAG, "customer": TAG, "published_on": TAG, "rating": 0.8}
		printed = self.play(
			f"""
			global.jQuery = global.$;
			let ready;
			const plain = global.$;
			global.$ = (what) => (typeof what === "function" ? (ready = what, element()) : plain(what));
			new Function(reviews.replace("new CustomerReviews()", "global.reviews_page = new CustomerReviews()"))();
			ready();
			global.reviews_page.get_user_review_html([{json.dumps(review)}]);
			console.log(JSON.stringify(global.printed));
			""",
			reviews=app_file("public/js/customer_reviews.js"),
		)
		self.assertNotIn("<img", printed)
		self.assertIn("&lt;img", printed)

	def recently_viewed(self, template):
		source = read_app_file(template)
		block = source[source.index("recently-viewed-items") :]
		block = block[block.index("<script>") + len("<script>") : block.index("</script>")]
		block = frappe.render_template(block, {})
		entry = {"name": ATTRIBUTE, "image": "/a.png" + ATTRIBUTE, "route": "a" + ATTRIBUTE, "price": TAG}
		return self.play(
			f"""
			const box = {{innerHTML: ""}};
			global.localStorage = {{getItem: () => {json.dumps(json.dumps([entry]))}}};
			global.document = {{getElementById: (id) => id === "recently-viewed-items" ? box : {{style: {{}}}}}};
			new Function({json.dumps(block)})();
			console.log(box.innerHTML);
			"""
		)

	def test_a_name_in_the_recently_viewed_strip_stays_in_its_attribute(self):
		for template in ("www/all-products/index.html", "templates/generators/item_group.html"):
			with self.subTest(template=template):
				html = self.recently_viewed(template)
				self.assertIn("rv-card", html)
				self.assertNotIn('" onload="', html)
				self.assertNotIn("<img src=x", html)
				self.assertNotIn(TAG, html)
