# //// Neoffice — added file (no upstream equivalent): a model's page and its variants, one
# //// ProductGroup (seo/variants.py). neoffice-maintenance#691, decision D-1, 2026-09-25.
"""A model's variants as its page sells them. Google reads the ProductGroup, the shopper uses the
variant selector and Merchant Center reads the feed, and all three come from one reading of the
variants: Google compares them, and refuses an item that disagrees with the page it links.
"""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.seo import availability, facts, jsonld, variants
from webshop.webshop.tests.utils import (
	default_company,
	ensure_shop_settings,
	make_test_item,
	restore_webshop_settings,
	selling_price_list,
	snapshot_webshop_settings,
)

SCHEMA = jsonld.SCHEMA
NO_POLICIES = frappe._dict(returns=False, shipping=False)


def _offer(price, url="https://shop.test/tee?variant=TEE-GRY-M", **extra):
	return frappe._dict(
		url=url,
		price=price,
		currency="CHF",
		availability=SCHEMA + "InStock",
		condition=SCHEMA + "NewCondition",
		struck_price=None,
		valid_from=None,
		valid_until=None,
		**extra,
	)


def _group(variant_list, **fields):
	return frappe._dict(
		{
			"url": "https://shop.test/tee",
			"group_id": "TEE",
			"name": "Coastline tee",
			"brand": "Trailhead",
			"description": "A soft tee.",
			"images": ["https://shop.test/files/tee.jpg"],
			"category": "Clothing > Tees",
			"properties": [],
			"varies_by": ["color", "size"],
			"variants": variant_list,
			"rating": None,
			"reviews": [],
			"videos": [],
			**fields,
		}
	)


class TestTheGroupGraph(FrappeTestCase):
	def graph(self, group):
		with (
			patch.object(jsonld, "seller_node", return_value=None) as seller,
			patch.object(jsonld, "site_policies", return_value=NO_POLICIES) as policies,
		):
			node = jsonld.product_graph(frappe._dict(group=group))
		return node, seller.call_count, policies.call_count

	def test_one_product_per_variant_each_with_its_own_offer(self):
		grey = frappe._dict(
			name="Coastline tee – Grey, M",
			sku="TEE-GRY-M",
			identifiers={"gtin13": "4006381333931"},
			image="https://shop.test/files/grey.jpg",
			properties={"color": "Grey", "size": "M"},
			others=[],
			offer=_offer(40.0),
		)
		sand = frappe._dict(
			name="Coastline tee – Sand, L",
			sku="TEE-SND-L",
			identifiers={},
			image="https://shop.test/files/tee.jpg",
			properties={"color": "Sand", "size": "L"},
			others=[("Fit", "Slim")],
			offer=None,
		)
		node, seller_calls, policy_calls = self.graph(_group([grey, sand]))

		self.assertEqual(node["@type"], "ProductGroup")
		self.assertEqual(node["productGroupID"], "TEE")
		self.assertEqual(node["url"], "https://shop.test/tee")
		self.assertEqual(node["variesBy"], [SCHEMA + "color", SCHEMA + "size"])
		self.assertNotIn("offers", node, "the group itself sells nothing: its variants do")

		first, second = node["hasVariant"]
		self.assertEqual(first["@type"], "Product")
		self.assertEqual((first["name"], first["sku"], first["gtin13"]), ("Coastline tee – Grey, M", "TEE-GRY-M", "4006381333931"))
		self.assertEqual((first["color"], first["size"]), ("Grey", "M"))
		self.assertEqual(first["offers"]["url"], "https://shop.test/tee?variant=TEE-GRY-M")
		self.assertEqual(first["offers"]["price"], 40.0)
		self.assertNotIn("brand", first, "the brand is the group's (Google: no need to repeat it)")
		self.assertNotIn("offers", second, "a variant the page does not price has no offer")
		self.assertEqual(second["additionalProperty"], [{"@type": "PropertyValue", "name": "Fit", "value": "Slim"}])
		# the shop's seller and policies are read once for the whole group, not once per variant
		self.assertEqual((seller_calls, policy_calls), (1, 1))

	def test_a_page_without_a_group_keeps_its_product(self):
		with (
			patch.object(jsonld, "seller_node", return_value=None),
			patch.object(jsonld, "site_policies", return_value=NO_POLICIES),
		):
			node = jsonld.product_graph(frappe._dict(group=None, url="https://shop.test/mug", name="Mug"))
		self.assertEqual(node["@type"], "Product")


class TestAVariantsOffer(FrappeTestCase):
	def row(self, price=None, mrp=0):
		return frappe._dict(
			item_code="TEE-GRY-M",
			availability=SCHEMA + "InStock",
			price=frappe._dict(price=price, mrp=mrp, currency="CHF", valid_from=None, valid_upto=None)
			if price is not None
			else None,
		)

	def test_only_where_the_page_prints_a_price(self):
		self.assertIsNone(facts.variant_offer(self.row(), "https://shop.test/tee?variant=X", SCHEMA + "NewCondition"))
		self.assertIsNone(facts.variant_offer(self.row(0), "https://shop.test/tee?variant=X", SCHEMA + "NewCondition"))
		offer = facts.variant_offer(self.row(36.0), "https://shop.test/tee?variant=X", SCHEMA + "NewCondition")
		self.assertEqual((offer.price, offer.struck_price, offer.url), (36.0, None, "https://shop.test/tee?variant=X"))

	def test_a_struck_price_only_above_the_price(self):
		offer = facts.variant_offer(self.row(36.0, mrp=45.0), "u", SCHEMA + "NewCondition")
		self.assertEqual(offer.struck_price, 45.0)
		offer = facts.variant_offer(self.row(36.0, mrp=36.0), "u", SCHEMA + "NewCondition")
		self.assertIsNone(offer.struck_price)


class TestNamesAndAttributes(FrappeTestCase):
	def test_the_attributes_google_knows_and_the_others(self):
		from webshop.webshop.seo.feeds.google import attribute_map

		mapping = attribute_map(frappe._dict())
		known, others = variants.schema_attributes([("Couleurs", "Gris"), ("Taille", "XL"), ("Coupe", "Slim")], mapping)
		# "Couleurs": a shop names the attribute after its list of values (osiris, 2026-09-25)
		self.assertEqual(known, {"color": "Gris", "size": "XL"})
		self.assertEqual(others, [("Coupe", "Slim")])

	def test_a_variant_is_named_more_precisely_than_its_model(self):
		self.assertEqual(
			variants.variant_label("Coastline tee", [("Colour", "Grey"), ("Size", "XL")]), "Coastline tee – Grey, XL"
		)
		self.assertEqual(variants.variant_label("Coastline tee", []), "Coastline tee")

	def test_the_page_opened_on_a_variant_names_it_in_its_address(self):
		self.assertEqual(
			variants.variant_link("https://shop.test/tee", "TEE GRY/M"), "https://shop.test/tee?variant=TEE%20GRY%2FM"
		)


class TestWhichPageCarriesTheGroup(FrappeTestCase):
	def test_a_model_its_variants_and_a_shop_without_the_selector(self):
		selling = frappe._dict(enable_variants=1)
		model = frappe._dict(item_code="TEE", has_variants=1)
		variant = frappe._dict(item_code="TEE-GRY-M", variant_of="TEE")
		plain = frappe._dict(item_code="MUG")
		with patch.object(variants, "model_page_name", return_value="WEB-TEE"):
			self.assertEqual(variants.group_model(model, selling), "TEE")
			self.assertEqual(variants.group_model(variant, selling), "TEE")
			self.assertIsNone(variants.group_model(plain, selling))
			# the selector off, the model's page sells nothing: each variant is a product of its own
			self.assertIsNone(variants.group_model(model, frappe._dict(enable_variants=0)))
			self.assertIsNone(variants.group_model(variant, frappe._dict(enable_variants=0)))
		# a model this site does not publish cannot be a variant's canonical page
		with patch.object(variants, "model_page_name", return_value=None):
			self.assertIsNone(variants.group_model(variant, selling))


class TestTheChosenVariant(FrappeTestCase):
	def rows(self):
		return [
			frappe._dict(
				item_code="TEE-GRY-M",
				image="/files/grey.jpg",
				choices=[("Colour", "Grey"), ("Size", "M")],
				price=frappe._dict(price=36.0, mrp=45.0, currency="CHF"),
				availability=SCHEMA + "InStock",
				qty=3.0,
			)
		]

	def test_what_the_footer_prints_for_the_variant_named(self):
		chosen = variants.chosen_variant(self.rows(), "TEE-GRY-M", frappe._dict(show_stock_availability=1))
		self.assertEqual((chosen.item_code, chosen.label, chosen.image), ("TEE-GRY-M", "Grey · M", "/files/grey.jpg"))
		self.assertIn("36", chosen.price["formatted_price"])
		self.assertIn("45", chosen.price["formatted_mrp"])
		self.assertEqual(chosen.price["discount_percent"], 20)
		self.assertTrue(chosen.in_stock)
		self.assertEqual(chosen.few_left, 3)
		# a shop that hides its stock does not count what is left
		self.assertIsNone(variants.chosen_variant(self.rows(), "TEE-GRY-M", frappe._dict()).few_left)

	def test_a_variant_the_page_does_not_sell_is_not_chosen(self):
		self.assertIsNone(variants.chosen_variant(self.rows(), "TEE-SND-L", frappe._dict()))
		self.assertIsNone(variants.chosen_variant(self.rows(), None, frappe._dict()))


MODEL = "WSP-D1-TEE"
COLOUR, SIZE = "WSP D1 Colour", "WSP D1 Size"
SETTINGS_FIELDS = [
	"enable_variants",
	"hide_price_for_guest",
	"show_stock_availability",
	"allow_items_not_in_stock",
	"google_feed_attribute_map",
]
PICTURE = "/files/wsp-d1-tee.jpg"


def _purge():
	codes = frappe.get_all("Item", filters={"variant_of": MODEL}, pluck="name") + [MODEL]
	for name in frappe.get_all("Website Item", filters={"item_code": ["in", codes]}, pluck="name"):
		frappe.delete_doc("Website Item", name, force=True, ignore_permissions=True)
	for name in frappe.get_all("Item Price", filters={"item_code": ["in", codes]}, pluck="name"):
		frappe.delete_doc("Item Price", name, force=True, ignore_permissions=True)
	frappe.db.delete("Bin", {"item_code": ["in", codes]})
	for code in codes[:-1] + [MODEL]:
		if frappe.db.exists("Item", code):
			frappe.delete_doc("Item", code, force=True, ignore_permissions=True)
	for attribute in (COLOUR, SIZE):
		if frappe.db.exists("Item Attribute", attribute):
			frappe.delete_doc("Item Attribute", attribute, force=True, ignore_permissions=True)


def _list_price(item_code, price_list, customer_group=None, company=None, qty=1, party=None, warehouse=None):
	"""get_price as the fleet's ERPNext fork answers without a pricing rule: the list rate. The CI's
	stock ERPNext knows no `warehouse` keyword, and reads `mrp` unset for a priced item without a
	rule (CLAUDE.md, "The quick order"): the page and the pricing it calls are what is tested here."""
	found = frappe.db.get_value(
		"Item Price",
		{"item_code": item_code, "price_list": price_list, "selling": 1},
		["price_list_rate", "currency"],
		as_dict=True,
	)
	if not found:
		return None
	return frappe._dict(
		price_list_rate=found.price_list_rate,
		currency=found.currency,
		formatted_price=frappe.utils.fmt_money(found.price_list_rate, currency=found.currency),
	)


def _publish(item_code):
	from webshop.webshop.doctype.website_item.website_item import make_website_item

	name = frappe.db.get_value("Website Item", {"item_code": item_code}, "name")
	if not name:
		name = make_website_item(frappe.get_doc("Item", item_code), save=True)[0]
	frappe.db.set_value("Website Item", name, "published", 1)
	return name


class TestAModelPage(FrappeTestCase):
	"""A tee in two colours and two sizes: three variants published, two priced on the shop's list,
	one with five pieces in the shop's warehouse."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		from erpnext.controllers.item_variant import create_variant

		cls.written = ensure_shop_settings()
		cls.snapshot = snapshot_webshop_settings(SETTINGS_FIELDS)
		frappe.db.set_single_value("Webshop Settings", "enable_variants", 1)
		frappe.db.set_single_value("Webshop Settings", "hide_price_for_guest", 0)
		frappe.db.set_single_value("Webshop Settings", "show_stock_availability", 1)
		frappe.db.set_single_value("Webshop Settings", "allow_items_not_in_stock", 0)
		frappe.db.set_single_value(
			"Webshop Settings", "google_feed_attribute_map", f"{COLOUR} = color\n{SIZE} = size"
		)
		_purge()
		for attribute, values in ((COLOUR, (("Graphite", "GRA"), ("Sand", "SND"))), (SIZE, (("S", "S"), ("M", "M")))):
			frappe.get_doc(
				{
					"doctype": "Item Attribute",
					"attribute_name": attribute,
					"item_attribute_values": [{"attribute_value": value, "abbr": abbr} for value, abbr in values],
				}
			).insert(ignore_permissions=True)
		make_test_item(
			MODEL,
			item_name="D1 tee",
			has_variants=1,
			is_stock_item=1,
			attributes=[{"attribute": COLOUR}, {"attribute": SIZE}],
		)
		cls.codes = {}
		for colour in ("Graphite", "Sand"):
			for size in ("S", "M"):
				variant = create_variant(MODEL, {COLOUR: colour, SIZE: size})
				variant.insert(ignore_permissions=True)
				cls.codes[(colour, size)] = variant.name
		cls.model_page = _publish(MODEL)
		for key in (("Graphite", "S"), ("Graphite", "M"), ("Sand", "S")):
			_publish(cls.codes[key])
		# the model's warehouse, which its variants use (get_web_item_qty_in_stock), and its picture
		from erpnext.stock.utils import get_or_make_bin

		cls.warehouse = frappe.db.get_value("Warehouse", {"company": default_company(), "is_group": 0}, "name")
		frappe.db.set_value(
			"Website Item", cls.model_page, {"website_warehouse": cls.warehouse, "website_image": PICTURE}
		)
		frappe.db.set_value("Bin", get_or_make_bin(cls.codes[("Graphite", "S")], cls.warehouse), "actual_qty", 5)
		price_list = selling_price_list()
		for key, rate in ((("Graphite", "S"), 30), (("Graphite", "M"), 40)):
			frappe.get_doc(
				{
					"doctype": "Item Price",
					"item_code": cls.codes[key],
					"price_list": price_list,
					"price_list_rate": rate,
					"selling": 1,
				}
			).insert(ignore_permissions=True)
		# class fixtures survive FrappeTestCase's rollback only committed (CLAUDE.md, Testing Strategy)
		frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit
		frappe.local.shopping_cart_settings = None
		frappe.clear_cache(doctype="Webshop Settings")

	@classmethod
	def tearDownClass(cls):
		frappe.set_user("Administrator")
		_purge()
		# class fixtures survive FrappeTestCase's rollback only committed (CLAUDE.md, Testing Strategy)
		frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit
		restore_webshop_settings({**cls.snapshot, **cls.written})
		super().tearDownClass()

	def setUp(self):
		from webshop.webshop.shopping_cart.product_info import clear_variant_prices

		clear_variant_prices()
		frappe.local.webshop_model_views = {}
		frappe.local.shopping_cart_settings = None
		self.prices = [
			patch("webshop.webshop.shopping_cart.product_info.get_price", side_effect=_list_price),
			patch("erpnext.utilities.product.get_price", side_effect=_list_price),
		]
		for price in self.prices:
			price.start()

	def tearDown(self):
		for price in self.prices:
			price.stop()
		frappe.set_user("Administrator")

	def settings(self, **changes):
		from webshop.webshop.doctype.webshop_settings.webshop_settings import get_shopping_cart_settings

		settings = frappe._dict(get_shopping_cart_settings())
		settings.update(changes)
		return settings

	def context(self, item_code, variant=None):
		doc = frappe.get_doc("Website Item", {"item_code": item_code})
		context = frappe._dict(metatags={}, shopping_cart=frappe._dict(), route=doc.route)
		with (
			patch.object(frappe.local, "request", None, create=True),
			patch.object(frappe.local, "form_dict", frappe._dict(variant=variant) if variant else frappe._dict()),
		):
			doc.get_context(context)
		return context

	def test_the_page_sells_its_published_variants_at_their_prices(self):
		rows = variants.offered_variants(MODEL, self.settings())
		by_code = {row.item_code: row for row in rows}
		self.assertEqual(
			set(by_code), {self.codes[("Graphite", "S")], self.codes[("Graphite", "M")], self.codes[("Sand", "S")]}
		)
		graphite_s = by_code[self.codes[("Graphite", "S")]]
		self.assertEqual(graphite_s.choices, [(COLOUR, "Graphite"), (SIZE, "S")], "in the model's order")
		self.assertEqual(graphite_s.price.price, 30)
		self.assertEqual(by_code[self.codes[("Graphite", "M")]].price.price, 40)
		self.assertIsNone(by_code[self.codes[("Sand", "S")]].price, "no price on the list, none declared")

	def test_bulk_availability_agrees_with_the_single_rule(self):
		codes = list(self.codes.values())
		bulk = availability.bulk_availability(codes, self.settings())
		for code in codes:
			with self.subTest(code=code):
				self.assertEqual(bulk[code].availability, availability.schema_availability(code, self.settings()))

	def test_the_selector_prices_only_what_the_page_prices(self):
		from webshop.webshop import api

		frappe.set_user("Guest")
		for hidden in (0, 1):
			with (
				self.subTest(hide_price_for_guest=hidden),
				patch(
					"webshop.webshop.doctype.webshop_settings.webshop_settings.get_shopping_cart_settings",
					return_value=self.settings(hide_price_for_guest=hidden),
				),
			):
				from webshop.webshop.shopping_cart.product_info import clear_variant_prices

				clear_variant_prices()
				answer = api.get_all_variants_info(MODEL)
				priced = {v["item_code"]: v["price"]["price_list_rate"] for v in answer["variants"] if v.get("price")}
				if hidden:
					self.assertEqual(priced, {}, "a visitor to whom the shop hides its prices reads none here")
					self.assertFalse(answer["show_prices"])
				else:
					self.assertEqual(
						priced, {self.codes[("Graphite", "S")]: 30, self.codes[("Graphite", "M")]: 40}
					)
					self.assertTrue(answer["show_prices"])

	def test_the_selector_answers_only_for_a_published_model(self):
		from webshop.webshop import api

		self.assertEqual(api.get_all_variants_info(self.codes[("Graphite", "S")]), {"variants": []})
		self.assertEqual(api.get_all_variants_info("WSP-NO-SUCH-ITEM"), {"variants": []})
		self.assertTrue(api.get_all_variants_info(MODEL)["variants"])

	def test_the_model_page_declares_its_group(self):
		context = self.context(MODEL)
		graph = context.product_jsonld
		self.assertEqual(graph["@type"], "ProductGroup")
		self.assertEqual(graph["productGroupID"], MODEL)
		self.assertEqual(graph["variesBy"], [SCHEMA + "color", SCHEMA + "size"])
		offers = {variant["sku"]: variant.get("offers") for variant in graph["hasVariant"]}
		self.assertEqual(len(offers), 3)
		graphite_m = offers[self.codes[("Graphite", "M")]]
		self.assertEqual(graphite_m["price"], 40)
		self.assertTrue(graphite_m["url"].endswith("?variant=" + self.codes[("Graphite", "M")]))
		# each variant's own stock: five pieces of one, none of the other
		self.assertEqual(offers[self.codes[("Graphite", "S")]]["availability"], SCHEMA + "InStock")
		self.assertEqual(graphite_m["availability"], SCHEMA + "OutOfStock")
		self.assertIsNone(offers[self.codes[("Sand", "S")]])
		self.assertTrue(context.canonical_url.endswith(context.route.strip("/")))

	def test_a_variant_page_names_the_model_and_carries_its_group(self):
		model = self.context(MODEL)
		page = self.context(self.codes[("Graphite", "S")])
		self.assertEqual(page.canonical_url, model.canonical_url)
		self.assertEqual(page.product_jsonld["productGroupID"], MODEL)
		self.assertEqual(
			[v["sku"] for v in page.product_jsonld["hasVariant"]], [v["sku"] for v in model.product_jsonld["hasVariant"]]
		)

	def test_the_page_opened_on_a_variant_prints_it(self):
		code = self.codes[("Graphite", "M")]
		context = self.context(MODEL, variant=code)
		self.assertEqual(context.chosen_variant.item_code, code)
		self.assertIn("40", context.chosen_variant.price["formatted_price"])
		self.assertFalse(context.chosen_variant.in_stock)
		in_stock = self.context(MODEL, variant=self.codes[("Graphite", "S")]).chosen_variant
		self.assertTrue(in_stock.in_stock)
		self.assertEqual(in_stock.few_left, 5)
		self.assertIsNone(self.context(MODEL).chosen_variant)
		# a variant the page does not sell (unpublished) is not printed
		self.assertIsNone(self.context(MODEL, variant=self.codes[("Sand", "M")]).chosen_variant)
		# the structured data does not change with the variant chosen (Google, single-page variants)
		self.assertEqual(context.product_jsonld, self.context(MODEL).product_jsonld)

	def test_the_sitemap_lists_the_model_not_its_variants(self):
		from webshop.webshop.seo import sitemaps

		sitemaps.clear_caches()
		routes = dict(frappe.get_all("Website Item", filters={"variant_of": MODEL}, fields=["item_code", "route"], as_list=True))
		locs = [link["loc"] for link in sitemaps.product_links()]
		model_route = frappe.db.get_value("Website Item", self.model_page, "route")
		self.assertTrue(any(loc.endswith(model_route.strip("/")) for loc in locs))
		for code, route in routes.items():
			with self.subTest(variant=code):
				self.assertFalse(any(loc.endswith(route.strip("/")) for loc in locs))
		sitemaps.clear_caches()

	def test_the_feed_sends_a_variant_as_its_model_page_opened_on_it(self):
		from webshop.webshop.seo.feeds import google

		settings = self.settings()
		frappe.set_user("Guest")
		code = self.codes[("Graphite", "S")]
		doc = frappe.get_doc("Website Item", {"item_code": code})
		entry, reason = google.item_entry(doc, settings, set(), google.attribute_map(settings))
		self.assertIsNone(reason)
		model_url = variants.model_view(MODEL, settings).url
		self.assertEqual(entry["link"], variants.variant_link(model_url, code))
		self.assertEqual(entry["canonical_link"], model_url)
		self.assertTrue(entry["price"].startswith("30.00 "))
		self.assertEqual(entry["availability"], "in_stock")
		self.assertEqual(entry["item_group_id"], MODEL)
		self.assertEqual(entry.get("color"), "Graphite")
		# the variant has no picture of its own: the model's page shows the model's
		self.assertTrue(entry["image_link"].endswith(PICTURE))
