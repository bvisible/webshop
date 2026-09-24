# //// Neoffice — added file (no upstream equivalent).
"""What the shop tells search engines: the hygiene lot of the SEO study (2026-09-24, #691).

Each class pins one defect measured on osiris and on a client shop in production, so that it
cannot come back unseen: the polluted microdata, `og:site_name = "ERPNext"`, the availability
that followed what the page displayed, the empty robots.txt, the sitemap without products,
the listings without a canonical, the dead /product_search, the route change that left a 404.
"""

import os
import re
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.seo import availability, meta, robots, sitemaps, text
from webshop.webshop.tests.utils import leaf_item_group, make_test_item, root_item_group

ITEM = "_WSTEST SEO product"
EMPTY_GROUP = "_WSTEST SEO empty group"
CARRYING_GROUP = "_WSTEST SEO carrying group"


def _robots_blocks(robots_txt, url):
	"""Whether `url` (path + query) is disallowed for `*`, with Google's matching rules.

	`*` matches any run of characters, a final `$` anchors the end, and a rule matches from
	the start of the path. Only Disallow lines are written by the default, so no Allow
	precedence is needed here.
	"""
	for line in robots_txt.splitlines():
		if not line.lower().startswith("disallow:"):
			continue
		rule = line.split(":", 1)[1].strip()
		if not rule:
			continue
		anchored = rule.endswith("$")
		pattern = re.escape(rule[:-1] if anchored else rule).replace(r"\*", ".*")
		if re.match(pattern + ("$" if anchored else ""), url):
			return True
	return False


class TestPlainText(FrappeTestCase):
	def test_paragraphs_and_list_items_stay_apart(self):
		html = "<p>Coton bio, 180 g/m²</p><ul><li>Col rond</li><li>Lavage 30&nbsp;°C</li></ul>"
		self.assertEqual(text.html_to_text(html), "Coton bio, 180 g/m²\nCol rond\nLavage 30 °C")
		self.assertEqual(text.one_line(html), "Coton bio, 180 g/m² Col rond Lavage 30 °C")

	def test_a_cut_falls_between_words(self):
		cut = text.truncate("La Ridge Runner est faite pour les sentiers qui montent", 30)
		self.assertLessEqual(len(cut), 30)
		self.assertTrue(cut.endswith("…"))
		self.assertTrue(" ".join(cut[:-1].split()) in "La Ridge Runner est faite pour les sentiers qui montent")


class TestDefaultRobots(FrappeTestCase):
	def setUp(self):
		self.robots = robots.default_robots_txt()

	def test_it_names_the_sitemap(self):
		self.assertIn("User-agent: *", self.robots)
		self.assertRegex(self.robots, r"(?m)^Sitemap: https?://\S+/sitemap\.xml$")

	def test_private_routes_are_closed_and_shop_pages_open(self):
		for url in ("/cart", "/cart?add=X&qty=1", "/checkout", "/me", "/orders/SO-0001", "/app/item", "/login"):
			self.assertTrue(_robots_blocks(self.robots, url), url)
		for url in (
			"/cartes-cadeaux",  # a French category must not fall under "/cart"
			"/media/logo.png",
			"/membres",
			"/products/chaussures/ridge-runner-fjdk1",
			"/all-products",
			"/all-products?start=24",
			# the category grids still load through the API: blocking it empties them for Google
			"/api/method/webshop.webshop.api.get_product_filter_data",
		):
			self.assertFalse(_robots_blocks(self.robots, url), url)

	def test_filtered_and_searched_listings_are_closed(self):
		self.assertTrue(_robots_blocks(self.robots, '/all-products?field_filters={"brand":["Canon"]}'))
		self.assertTrue(_robots_blocks(self.robots, "/all-products?search=chaussure"))

	def test_the_default_fills_an_empty_robots_txt_only(self):
		with _request_path("/robots.txt"):
			context = frappe._dict(robots_txt="")
			meta.update_website_context(context)
			self.assertIn("Sitemap:", context.robots_txt)

			written = "User-agent: *\nDisallow: /private\n"
			context = frappe._dict(robots_txt=written)
			meta.update_website_context(context)
			self.assertEqual(context.robots_txt, written)


class TestNoindex(FrappeTestCase):
	def test_private_pages_are_not_indexed(self):
		for path in ("/cart", "/wishlist", "/orders/SO-0001", "/search"):
			with _request_path(path):
				context = frappe._dict(metatags=frappe._dict())
				meta.update_website_context(context)
				self.assertEqual(context.metatags.get("robots"), "noindex, follow", path)

	def test_a_product_page_is_indexed(self):
		with _request_path("/products/chaussures/ridge-runner-fjdk1"):
			context = frappe._dict(metatags=frappe._dict())
			meta.update_website_context(context)
			self.assertNotIn("robots", context.metatags)

	def test_a_searched_listing_is_not_indexed(self):
		with _request_path("/all-products"), _form_dict(search="chaussure"):
			context = frappe._dict(metatags=frappe._dict())
			meta.update_website_context(context)
			self.assertEqual(context.metatags.get("robots"), "noindex, follow")


class TestNoMicrodata(FrappeTestCase):
	"""One structured-data graph per page, in JSON-LD: no microdata left in the shop.

	The product page carried a second Product in microdata, named "Code article:", holding
	the names and prices of the recommended products, an empty rating and an empty review;
	listing containers and category pages declared themselves Products.
	"""

	def test_no_template_or_listing_script_carries_microdata(self):
		root = frappe.get_app_path("webshop")
		scanned = [os.path.join(root, "public", "js", "product_ui", "views.js")]
		for base in (os.path.join(root, "templates"), os.path.join(root, "www")):
			for folder, _dirs, files in os.walk(base):
				scanned += [os.path.join(folder, name) for name in files if name.endswith(".html")]
		offenders = []
		for path in scanned:
			with open(path, encoding="utf-8") as handle:
				for number, line in enumerate(handle, 1):
					if "//// Neoffice" in line:
						continue
					if re.search(r"\bitem(scope|prop|type)\b", line):
						offenders.append(f"{os.path.relpath(path, root)}:{number}")
		self.assertEqual(offenders, [], "microdata found: " + ", ".join(offenders))


class TestSiteName(FrappeTestCase):
	def test_a_product_page_is_announced_as_the_shop(self):
		doc = frappe.get_doc(
			{"doctype": "Website Item", "item_code": ITEM, "web_item_name": ITEM, "description": "<p>A product</p>"}
		)
		context = frappe._dict(route="products/x", website_image=None)
		with patch("webshop.webshop.seo.site.shop_name", return_value="A Shop"):
			doc.set_metatags(context)
		self.assertEqual(context.metatags.get("og:site_name"), "A Shop")

	def test_the_site_chrome_names_the_site_before_website_settings(self):
		"""The home page declares its WebSite under the chrome's name (builder's site graph): the
		pages of the shop announce the same one, per site (2026-09-24)."""
		from webshop.webshop.seo import site

		with patch.object(site, "chrome_site_name", return_value="Atelier Nord"):
			self.assertEqual(site.shop_name(), "Atelier Nord")
		with patch.object(site, "chrome_site_name", return_value=""):
			with patch.object(site, "app_name", return_value="Maison Test"):
				self.assertEqual(site.shop_name(), "Maison Test")
			with patch.object(site, "app_name", return_value="ERPNext"):
				self.assertEqual(site.shop_name(), "")

	def test_a_site_never_named_announces_nothing(self):
		doc = frappe.get_doc({"doctype": "Website Item", "item_code": ITEM, "web_item_name": ITEM, "description": ""})
		context = frappe._dict(route="products/x", website_image=None)
		with patch("webshop.webshop.seo.site.shop_name", return_value=""):
			doc.set_metatags(context)
		self.assertNotIn("og:site_name", context.metatags)
		self.assertNotEqual(context.metatags.get("og:site_name"), "ERPNext")


class TestAvailability(FrappeTestCase):
	"""What the structured data declares, whatever the page chooses to display."""

	def _settings(self, allow=0):
		return frappe._dict(allow_items_not_in_stock=allow)

	def test_backorder(self):
		with patch.object(availability.frappe.db, "get_value", return_value=1):
			self.assertEqual(availability.schema_availability("X", self._settings()), availability.BACK_ORDER)

	def test_in_stock_and_out_of_stock(self):
		with patch.object(availability.frappe.db, "get_value", return_value=0):
			with patch.object(availability, "item_can_be_bought", return_value=True):
				self.assertEqual(availability.schema_availability("X", self._settings()), availability.IN_STOCK)
			with patch.object(availability, "item_can_be_bought", return_value=False):
				self.assertEqual(availability.schema_availability("X", self._settings()), availability.OUT_OF_STOCK)
				# a shop that takes orders beyond its stock is on backorder, not out of stock
				self.assertEqual(availability.schema_availability("X", self._settings(1)), availability.BACK_ORDER)

	def test_a_model_is_available_when_one_variant_is(self):
		with patch.object(availability.frappe.db, "get_value", return_value=1), patch.object(
			availability.frappe, "get_all", return_value=["V-S", "V-M", "V-L"]
		), patch.object(availability, "_in_stock", side_effect=lambda code: code == "V-L"):
			self.assertTrue(availability.item_can_be_bought("MODEL"))
		with patch.object(availability.frappe.db, "get_value", return_value=1), patch.object(
			availability.frappe, "get_all", return_value=["V-S"]
		), patch.object(availability, "_in_stock", return_value=False):
			self.assertFalse(availability.item_can_be_bought("MODEL"))


class TestDescriptions(FrappeTestCase):
	def test_what_a_category_holds(self):
		self.assertIn("Trailhead", meta.summary_description("Chaussures", 12, ["Trailhead", "Salomon"]))
		self.assertLessEqual(len(meta.summary_description("x" * 300, 12, ["a", "b", "c"])), meta.DESCRIPTION_LIMIT)


class TestSitemaps(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		item = make_test_item(ITEM, is_stock_item=0)
		cls.web_item = frappe.db.get_value("Website Item", {"item_code": item.name}, "name")
		if not cls.web_item:
			doc = frappe.get_doc(
				{
					"doctype": "Website Item",
					"item_code": item.name,
					"web_item_name": ITEM,
					"item_group": leaf_item_group(),
					"published": 1,
				}
			)
			doc.flags.ignore_permissions = True
			doc.insert()
			cls.web_item = doc.name
		for group in (EMPTY_GROUP, CARRYING_GROUP):
			if not frappe.db.exists("Item Group", group):
				frappe.get_doc(
					{
						"doctype": "Item Group",
						"item_group_name": group,
						"parent_item_group": root_item_group(),
						"show_in_website": 1,
					}
				).insert(ignore_permissions=True)
		# the fixture groups of a fresh site are not shown on the website: this one is
		frappe.db.set_value("Website Item", cls.web_item, {"published": 1, "item_group": CARRYING_GROUP})
		frappe.db.commit()
		sitemaps.clear_caches()

	@classmethod
	def tearDownClass(cls):
		frappe.db.set_value("Website Item", cls.web_item, "item_group", leaf_item_group())
		for group in (EMPTY_GROUP, CARRYING_GROUP):
			if frappe.db.exists("Item Group", group):
				frappe.delete_doc("Item Group", group, force=True, ignore_permissions=True)
		frappe.db.commit()
		sitemaps.clear_caches()
		super().tearDownClass()

	def test_sitemap_xml_is_the_index(self):
		from webshop.www import sitemap

		locs = [entry["loc"] for entry in sitemap.get_context(frappe._dict())["sitemaps"]]
		for name in ("sitemap_pages.xml", "sitemap_products.xml", "sitemap_categories.xml"):
			self.assertTrue(any(loc.endswith("/" + name) for loc in locs), name)
		self.assertFalse(any(loc.endswith("/sitemap_brands.xml") for loc in locs))

	def test_products_are_listed(self):
		route = frappe.db.get_value("Website Item", self.web_item, "route")
		links = sitemaps.product_links()
		self.assertTrue(any(link["loc"].endswith(route.strip("/")) for link in links), route)
		self.assertTrue(all("priority" not in link and "changefreq" not in link for link in links))

	def test_an_empty_category_is_not_listed(self):
		route = frappe.db.get_value("Item Group", EMPTY_GROUP, "route")
		locs = [link["loc"] for link in sitemaps.category_links()]
		self.assertFalse(any(route and loc.endswith(route.strip("/")) for loc in locs))
		carrying = frappe.db.get_value("Item Group", CARRYING_GROUP, "route")
		self.assertTrue(carrying)
		self.assertTrue(any(loc.endswith(carrying.strip("/")) for loc in locs), (carrying, locs))

	def test_brand_filters_are_not_pages(self):
		from webshop.www import sitemap_brands

		self.assertEqual(sitemap_brands.get_context(frappe._dict())["links"], [])


class TestRouteRedirects(FrappeTestCase):
	def _redirect_of(self, path):
		from frappe.website.path_resolver import resolve_redirect

		# Frappe's resolve_redirect does `redirects = frappe.get_hooks(...)` then `redirects +=
		# frappe.get_all(...)`: it extends the hooks list, which is cached for the request, so
		# within ONE request every call stacks the rules it read in front of the next call's.
		# A page view makes one call; a test making several starts from a fresh request cache.
		frappe.local.cache.clear()
		frappe.flags.redirect_location = None
		try:
			resolve_redirect(path)
		except frappe.Redirect:
			return frappe.flags.redirect_location
		return None

	def test_a_renamed_page_leaves_a_permanent_redirect_without_chains(self):
		from webshop.webshop.seo.redirects import add_route_redirect

		add_route_redirect("_wstest-seo/old-route", "_wstest-seo/new-route")
		self.assertEqual(self._redirect_of("_wstest-seo/old-route"), "/_wstest-seo/new-route")

		add_route_redirect("_wstest-seo/new-route", "_wstest-seo/newer-route")
		self.assertEqual(self._redirect_of("_wstest-seo/old-route"), "/_wstest-seo/newer-route")
		self.assertEqual(self._redirect_of("_wstest-seo/new-route"), "/_wstest-seo/newer-route")

		# back to an address it used to have: the redirect from that address is gone
		add_route_redirect("_wstest-seo/newer-route", "_wstest-seo/old-route")
		self.assertIsNone(self._redirect_of("_wstest-seo/old-route"))

	def test_the_hook_reads_the_route_before_the_save(self):
		before = SimpleNamespace(get=lambda field: "_wstest-seo/before" if field == "route" else None)
		doc = SimpleNamespace(get_doc_before_save=lambda: before, get=lambda field: "_wstest-seo/after")
		from webshop.webshop.seo.redirects import remember_old_route

		remember_old_route(doc)
		self.assertEqual(self._redirect_of("_wstest-seo/before"), "/_wstest-seo/after")


class TestProductSearch(FrappeTestCase):
	def test_the_dead_search_page_sends_to_the_catalogue_search(self):
		from webshop.templates.pages import product_search

		with _form_dict(search="trail shoe"):
			with self.assertRaises(frappe.Redirect):
				product_search.get_context(frappe._dict())
		self.assertEqual(frappe.local.flags.redirect_location, "/all-products?search=trail+shoe")


class TestSiteScope(FrappeTestCase):
	def test_an_item_of_another_site_does_not_exist_here(self):
		doc = frappe.get_doc({"doctype": "Website Item", "item_code": ITEM, "web_item_name": ITEM})
		doc.name = "_WSTEST-SEO-OTHER-SITE"
		with patch("webshop.webshop.multi_site.excluded_item_names", return_value=[doc.name]):
			with self.assertRaises(frappe.PageDoesNotExistError):
				doc.get_context(frappe._dict())


class _request_path:
	"""frappe.local.request with a given path, for the hooks that read it."""

	def __init__(self, path):
		self.path = path

	def __enter__(self):
		self.previous = getattr(frappe.local, "request", None)
		frappe.local.request = SimpleNamespace(path=self.path, host="shop.test", headers={})

	def __exit__(self, *exc):
		frappe.local.request = self.previous


class _form_dict:
	def __init__(self, **values):
		self.values = values

	def __enter__(self):
		self.previous = getattr(frappe.local, "form_dict", None)
		frappe.local.form_dict = frappe._dict(self.values)

	def __exit__(self, *exc):
		frappe.local.form_dict = self.previous
