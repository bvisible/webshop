# //// Neoffice — added file (no upstream equivalent): the product page's structured data
# //// (seo/facts.py, seo/jsonld.py). neoffice-maintenance#691 (lot 1, D8), 2026-09-24.
"""What the product page declares to Google, and that it declares only what the page shows.

Google compares the structured data with the page and, once a feed exists, with the feed: a
struck price the page does not print, a rating it does not show or a price a cent away is
a refused item, then a suspended account.
"""

import json
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from webshop.webshop.seo import facts as facts_module
from webshop.webshop.seo import jsonld

SETTINGS = {"show_price": 1, "enable_reviews": 1, "return_days": 0, "free_shipping_from": 0}


def _context(price=None, settings=None, **extra):
	cart_settings = frappe._dict({**SETTINGS, **(settings or {})})
	product_info = {"price": price} if price is not None else {}
	return frappe._dict(
		shopping_cart=frappe._dict(cart_settings=cart_settings, product_info=product_info), **extra
	)


def _doc(**fields):
	return frappe._dict(
		{
			"route": "shop/trail-shoe",
			"web_item_name": "Trail shoe",
			"item_code": "TRAIL 01",
			"is_gift_card": 0,
			"item_condition": "New",
			**fields,
		}
	)


def _offer(price, settings=None, **doc_fields):
	return facts_module.offer_facts(
		_doc(**doc_fields), _context(price, settings), "https://shop.test/shop/trail-shoe", jsonld.SCHEMA + "InStock"
	)


class TestIdentifiers(FrappeTestCase):
	def test_only_a_gtin_whose_check_digit_is_right(self):
		for code in ("4006381333931", "036000291452", "96385074", "10614141000415"):
			with self.subTest(code=code):
				self.assertTrue(facts_module.valid_gtin(code))
		for code in ("4006381333932", "40063813339", "ABC1234567890", "0000000000000", "", None):
			with self.subTest(code=code):
				self.assertFalse(facts_module.valid_gtin(code))

	def test_the_sku_carries_no_whitespace(self):
		self.assertEqual(facts_module.schema_sku("TRAIL 01\t-B "), "TRAIL01-B")


class TestOffer(FrappeTestCase):
	def test_the_offer_is_the_price_the_buy_column_prints(self):
		offer = _offer({"price_list_rate": 49.9, "currency": "CHF", "conversion_factor": 6})
		self.assertEqual(offer.price, 299.4)
		self.assertEqual(offer.currency, "CHF")
		self.assertIsNone(offer.struck_price)

	def test_no_offer_where_the_page_shows_no_price(self):
		price = {"price_list_rate": 49.9, "currency": "CHF"}
		self.assertIsNone(_offer(price, {"show_price": 0}))
		self.assertIsNone(_offer({}))
		self.assertIsNone(_offer({"price_list_rate": 0, "currency": "CHF"}))
		# a gift card's page offers amounts to choose, not the item's price
		self.assertIsNone(_offer(price, is_gift_card=1))

	def test_a_struck_price_only_when_the_page_strikes_it(self):
		sale = {"price_list_rate": 90, "currency": "CHF", "mrp": 100, "formatted_mrp": "CHF 100.00"}
		self.assertEqual(_offer(sale).struck_price, 100)
		# the raw value without the printed one: nothing struck on the page
		self.assertIsNone(_offer({**sale, "formatted_mrp": ""}).struck_price)
		self.assertIsNone(_offer({**sale, "mrp": 90}).struck_price)

	def test_a_running_sale_has_its_dates_and_a_finished_one_no_end(self):
		running = {
			"price_list_rate": 90,
			"currency": "CHF",
			"mrp": 100,
			"formatted_mrp": "CHF 100.00",
			"valid_from": f"{add_days(nowdate(), -3)} 00:00:00",
			"valid_upto": f"{add_days(nowdate(), 5)} 23:59:59",
		}
		offer = _offer(running)
		self.assertTrue(offer.valid_from.startswith(add_days(nowdate(), -3) + "T00:00:00"))
		self.assertTrue(offer.valid_until.startswith(add_days(nowdate(), 5) + "T23:59:59"))
		# ISO 8601 with the site's offset, as Google asks
		self.assertRegex(offer.valid_until, r"[+-]\d{2}:\d{2}$")
		self.assertIsNone(_offer({**running, "valid_upto": f"{add_days(nowdate(), -1)} 23:59:59"}).valid_until)


class TestRatingAndReviews(FrappeTestCase):
	def test_the_rating_is_the_one_the_block_prints(self):
		context = _context(total_reviews=12, average_rating=4.46)
		self.assertEqual(facts_module.rating_facts(context), {"value": 4.5, "count": 12})
		self.assertIsNone(facts_module.rating_facts(_context(total_reviews=0, average_rating=0)))
		self.assertIsNone(
			facts_module.rating_facts(_context(settings={"enable_reviews": 0}, total_reviews=12, average_rating=4.5))
		)

	def test_the_reviews_are_the_ones_shown_on_five(self):
		reviews = [
			frappe._dict(customer=f"Reviewer {n}", rating=0.8, creation="2026-09-01 10:00:00", comment="<p>Good</p>")
			for n in range(6)
		]
		reviews.insert(0, frappe._dict(customer="", rating=1, creation="2026-09-01 10:00:00"))
		found = facts_module.review_facts(_context(reviews=reviews))
		self.assertEqual(len(found), 3)  # four shown, one of them without an author
		self.assertEqual((found[0].rating, found[0].date, found[0].text), (4, "2026-09-01", "Good"))


class TestProductGraph(FrappeTestCase):
	def facts(self, **overrides):
		return frappe._dict(
			{
				"url": "https://shop.test/shop/trail-shoe",
				"name": "Trail shoe",
				"sku": "TRAIL01",
				"brand": "Trailhead",
				"description": "Light.\n\nGrippy.",
				"images": ["https://shop.test/files/a.jpg", "https://shop.test/files/b.jpg"],
				"category": "Shoes > Trail",
				"identifiers": {"gtin13": "4006381333931", "mpn": "TH-01"},
				"properties": [("Weight", "280 g")],
				"offer": frappe._dict(
					url="https://shop.test/shop/trail-shoe",
					price=90.0,
					currency="CHF",
					availability=jsonld.SCHEMA + "InStock",
					condition=jsonld.SCHEMA + "NewCondition",
					struck_price=100.0,
					valid_from=None,
					valid_until="2026-12-31T23:59:59+01:00",
				),
				"rating": frappe._dict(value=4.5, count=12),
				"reviews": [
					frappe._dict(author="Ada", author_type="Person", rating=5, date="2026-09-01", title="", text="Good")
				],
				"videos": [
					frappe._dict(
						name="On the trail",
						thumbnail="https://i.ytimg.com/vi/abcdefghijk/hqdefault.jpg",
						uploaded="2026-09-01",
						embed_url="https://www.youtube-nocookie.com/embed/abcdefghijk",
					)
				],
				**overrides,
			}
		)

	def graph(self, policies=None, name="Atelier Test", **overrides):
		policies = frappe._dict({"returns": False, "shipping": False, **(policies or {})})
		with patch("webshop.webshop.seo.jsonld.site_policies", return_value=policies), patch(
			"webshop.webshop.seo.site.shop_name", return_value=name
		):
			return jsonld.product_graph(self.facts(**overrides))

	def test_one_product_one_offer_and_the_struck_price_beside_it(self):
		graph = self.graph()
		self.assertEqual(graph["@type"], "Product")
		self.assertEqual(graph["offers"]["@type"], "Offer")
		self.assertEqual(graph["offers"]["price"], 90.0)
		self.assertNotIn("priceType", graph["offers"])
		struck = graph["offers"]["priceSpecification"]
		self.assertEqual((struck["priceType"], struck["price"]), (jsonld.SCHEMA + "StrikethroughPrice", 100.0))
		self.assertEqual(graph["offers"]["priceValidUntil"], "2026-12-31T23:59:59+01:00")
		self.assertNotIn("AggregateOffer", json.dumps(graph))

	def test_identifiers_pictures_category_and_characteristics(self):
		graph = self.graph()
		self.assertEqual((graph["gtin13"], graph["mpn"], graph["sku"]), ("4006381333931", "TH-01", "TRAIL01"))
		self.assertEqual(len(graph["image"]), 2)
		self.assertEqual(graph["category"], "Shoes > Trail")
		self.assertEqual(graph["additionalProperty"][0]["name"], "Weight")
		self.assertEqual(graph["aggregateRating"]["ratingValue"], 4.5)
		self.assertEqual(graph["review"][0]["reviewRating"]["ratingValue"], 5)
		self.assertEqual(graph["subjectOf"][0]["@type"], "VideoObject")

	def test_the_policies_are_pointed_at_only_when_the_shop_states_them(self):
		self.assertNotIn("hasMerchantReturnPolicy", self.graph()["offers"])
		self.assertNotIn("shippingDetails", self.graph()["offers"])
		offer = self.graph(policies={"returns": True, "shipping": True})["offers"]
		self.assertTrue(offer["hasMerchantReturnPolicy"]["@id"].endswith("/#returns"))
		self.assertTrue(offer["shippingDetails"]["hasShippingService"]["@id"].endswith("/#shipping"))

	def test_a_product_without_price_rating_or_review_says_nothing_of_them(self):
		graph = self.graph(offer=None, rating=None, reviews=[], videos=[], name="")
		for key in ("offers", "aggregateRating", "review", "subjectOf"):
			self.assertNotIn(key, graph)


class TestProductPageTemplate(FrappeTestCase):
	def test_the_page_prints_the_graph_built_from_its_own_context(self):
		"""item.html prints context.product_jsonld, once, as JSON; nothing else is Product."""
		source = (Path(__file__).resolve().parents[2] / "templates" / "generators" / "item" / "item.html").read_text()
		start = source.index("{%- if product_jsonld %}")
		end = source.index("{%- endif %}", start) + len("{%- endif %}")
		graph = {"@context": "https://schema.org", "@type": "Product", "name": "Trail </script> shoe"}
		html = frappe.render_template(source[start:end], {"product_jsonld": graph})
		self.assertEqual(html.count('<script type="application/ld+json">'), 1)
		# a name cannot close the script it sits in
		self.assertNotIn("</script> shoe", html)
		body = html.split('<script type="application/ld+json">', 1)[1].rsplit("</script>", 1)[0]
		self.assertEqual(json.loads(body), graph)
		self.assertEqual(source.count("application/ld+json"), 1)


class TestSiteOrganization(FrappeTestCase):
	"""The shop's share of the Organization the site chrome declares on the home page."""

	def organization(self, settings, country="CH", company=("Atelier Test SA", "CHE-123.456.789 TVA")):
		organization = {"@type": "Organization", "name": "Atelier Test"}
		real_get_cached_value = frappe.get_cached_value

		def get_cached_value(doctype, name, fieldname="name", *args, **kwargs):
			if doctype == "Company":
				return company
			return real_get_cached_value(doctype, name, fieldname, *args, **kwargs)

		with (
			patch(
				"webshop.webshop.doctype.webshop_settings.webshop_settings.get_shopping_cart_settings",
				return_value=frappe._dict({"enabled": 1, "company": "Atelier Test SA", **settings}),
			),
			patch("webshop.webshop.seo.jsonld.shop_country", return_value=country),
			patch("webshop.webshop.seo.jsonld.shop_currency", return_value="CHF"),
			patch("webshop.webshop.seo.jsonld.frappe.get_cached_value", side_effect=get_cached_value),
		):
			jsonld.site_organization(organization)
		return organization

	def test_a_site_that_sells_is_an_online_store_with_its_policies(self):
		organization = self.organization({"return_days": 30, "free_shipping_from": 100})
		self.assertEqual(organization["@type"], "OnlineStore")
		returns = organization["hasMerchantReturnPolicy"]
		self.assertEqual(returns["@id"], jsonld.policy_id("returns"))
		self.assertEqual((returns["applicableCountry"], returns["merchantReturnDays"]), ("CH", 30))
		self.assertEqual(returns["returnPolicyCategory"], jsonld.SCHEMA + "MerchantReturnFiniteReturnWindow")
		conditions = organization["hasShippingService"]["shippingConditions"]
		self.assertEqual(organization["hasShippingService"]["@id"], jsonld.policy_id("shipping"))
		self.assertEqual(conditions["orderValue"]["minValue"], 100)
		self.assertEqual((conditions["shippingRate"]["value"], conditions["shippingRate"]["currency"]), (0, "CHF"))
		self.assertEqual(conditions["shippingDestination"]["addressCountry"], "CH")

	def test_nothing_is_declared_that_the_shop_does_not_state(self):
		organization = self.organization({"return_days": 0, "free_shipping_from": 0})
		self.assertNotIn("hasMerchantReturnPolicy", organization)
		self.assertNotIn("hasShippingService", organization)
		self.assertNotIn("hasMerchantReturnPolicy", self.organization({"return_days": 30}, country=""))
		# a site that does not sell is left as the chrome declared it
		self.assertEqual(self.organization({"enabled": 0, "return_days": 30})["@type"], "Organization")

	def test_only_a_swiss_uid_is_published_as_the_vat_id(self):
		self.assertEqual(self.organization({})["vatID"], "CHE-123.456.789 TVA")
		self.assertEqual(self.organization({})["legalName"], "Atelier Test SA")
		self.assertNotIn("vatID", self.organization({}, company=("Atelier Test SA", "12-3456789")))
