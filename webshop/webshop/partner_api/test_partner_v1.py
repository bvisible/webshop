# //// Neoffice — added file (no upstream equivalent).
"""The partner API, version 1, through its door: what a key reads, what it orders, what it can never reach.

Two resellers on two price lists (FIRST costs the first 80 and the second 70; the shop's visitors 100), the
first allowed to place orders, the second to read only. Calls go through the page renderer with a stand-in for
the request, as a program's would arrive. What is proved is what would hurt: the price read is the caller's
own (never the shop's), an order is priced by the server whatever the body says, a replayed order is one order,
an order of somebody else does not exist, and a stock is never told as a quantity.
"""

import json
import os
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from webshop.webshop.catalogue import access as catalogue_access
from webshop.webshop.catalogue import fixtures as shop
from webshop.webshop.partner_api import access, v1
from webshop.webshop.partner_api.renderer import PartnerApiRenderer
from webshop.webshop.seo import availability as stock
from webshop.webshop.tests.utils import restore_webshop_settings, snapshot_webshop_settings
from webshop.webshop.utils import throttle

DOCTYPE = access.DOCTYPE
OTHER_LIST = f"{shop.PREFIX} Cat Second List"
NO_PRICE = f"{shop.PREFIX} Cat No Price"
CUSTOMERS = (shop.CUSTOMER, shop.OTHER_CUSTOMER)
SHOP_PRICES = {100.0, 50.0}  # what the shop's visitors pay for FIRST and SECOND


def wipe_orders():
	for customer in CUSTOMERS:
		for name in frappe.get_all("Partner API Order", filters={"customer": customer}, pluck="name"):
			frappe.delete_doc("Partner API Order", name, force=True, ignore_permissions=True)
		for name in frappe.get_all("Sales Order", filters={"customer": customer}, fields=["name", "docstatus"]):
			order = frappe.get_doc("Sales Order", name.name)
			if order.docstatus == 1:
				order.flags.ignore_permissions = True
				order.cancel()
			frappe.delete_doc("Sales Order", name.name, force=True, ignore_permissions=True)
	frappe.db.commit()


class TestPartnerV1(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		shop.make()
		# a second price list for the second reseller, and a published product that has no price anywhere
		currency = frappe.db.get_value("Price List", shop.RESELLER_LIST, "currency")
		frappe.get_doc({"doctype": "Price List", "price_list_name": OTHER_LIST, "currency": currency, "selling": 1, "enabled": 1}).insert(ignore_permissions=True)
		for code, rate in ((shop.FIRST, 70), (shop.SECOND, 35), (shop.THIRD, 30)):
			frappe.get_doc({"doctype": "Item Price", "item_code": code, "price_list": OTHER_LIST, "price_list_rate": rate}).insert(ignore_permissions=True)
		frappe.db.set_value("Customer", shop.OTHER_CUSTOMER, "default_price_list", OTHER_LIST)
		item = shop.make_test_item(NO_PRICE, item_name="Cat no price", item_group=shop.CHILD_GROUP, brand=shop.BRAND_A, is_stock_item=0)
		shop._publish(item, web_item_name="Cat no price")
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cls.wipe()
		shop.purge()
		for name in frappe.get_all("Website Item", filters={"item_code": NO_PRICE}, pluck="name"):
			frappe.delete_doc("Website Item", name, force=True, ignore_permissions=True)
		if frappe.db.exists("Item", NO_PRICE):
			frappe.delete_doc("Item", NO_PRICE, force=True, ignore_permissions=True)
		frappe.db.delete("Item Price", {"price_list": OTHER_LIST})
		if frappe.db.exists("Price List", OTHER_LIST):
			frappe.delete_doc("Price List", OTHER_LIST, force=True, ignore_permissions=True)
		frappe.db.commit()
		super().tearDownClass()

	@classmethod
	def wipe(cls):
		wipe_orders()
		for customer in CUSTOMERS:
			if frappe.db.exists(DOCTYPE, customer):
				frappe.delete_doc(DOCTYPE, customer, force=True, ignore_permissions=True)
			for counter in ("partner-request", "partner-key", "partner-api"):
				throttle.reset(counter, customer)
		throttle.reset("partner-miss", "unknown")
		frappe.db.commit()

	def setUp(self):
		self.settings = frappe.get_doc("Webshop Settings")
		self.settings.enable_reseller_catalogue = 1
		self.settings.reseller_catalogue_groups = [frappe._dict(allowed_customer_group=shop.RESELLER_GROUP)]
		patcher = mock.patch.object(catalogue_access, "shop_settings", return_value=self.settings)
		patcher.start()
		self.addCleanup(patcher.stop)
		self.addCleanup(frappe.set_user, "Administrator")
		self.wipe()
		self.keys = {}
		for customer, user, orders in ((shop.CUSTOMER, shop.USER, 1), (shop.OTHER_CUSTOMER, shop.OTHER_USER, 0)):
			self.assertIsNone(access.request(customer, user, "Sync", bool(orders), ""))
			access.approve(customer, scope_orders=orders, calls_per_minute=300)
			self.keys[customer] = access.new_key(customer)[0]
		frappe.db.commit()  # a refused or dry-run order rolls back: the accesses must already be written

	def tearDown(self):
		wipe_orders()

	# --- the door -----------------------------------------------------------------------------------

	def call(self, method, path, key="A", args=None, body=None, length=None):
		"""One call through the renderer, as a real request. `key`: "A", "B", None (none sent) or the text to
		send; `body` None on a POST sends text that is not JSON; `length` sends a body of that many bytes."""
		sent = {"A": self.keys[shop.CUSTOMER], "B": self.keys[shop.OTHER_CUSTOMER]}.get(key, key)
		options = {"path": f"/partner/v1/{path}", "method": method, "query_string": args or {}, "base_url": "https://shop.example"}
		if sent is not None:
			options["headers"] = {"X-API-Key": sent}
		if method == "POST":
			if length is not None:
				options.update(data=b"{" + b" " * length + b"}", content_type="application/json")
			elif body is None:
				options.update(data=b"not json", content_type="text/plain")
			else:
				options["json"] = body
		request = Request(EnvironBuilder(**options).get_environ())
		with mock.patch.object(frappe.local, "request", request, create=True):
			response = PartnerApiRenderer(path=f"partner/v1/{path}".rstrip("/")).render()
		raw = response.get_data(as_text=True)
		parsed = json.loads(raw) if response.mimetype == "application/json" else raw
		return response.status_code, parsed, response

	def get(self, path, **kwargs):
		return self.call("GET", path, **kwargs)

	def lines(self, *pairs):
		return [{"item_code": code, "qty": qty} for code, qty in pairs]

	def order(self, key="order-1", pairs=((shop.FIRST, 2),), **extra):
		# ERPNext refuses a second order of a customer with the same purchase order reference: one a key
		body = {"idempotency_key": key, "reference": f"PO-{key}", "lines": self.lines(*pairs), **extra}
		return self.call("POST", "orders", body=body)

	# --- who may knock ---------------------------------------------------------------------------------

	def test_a_call_without_a_good_key_is_a_401_with_one_shape(self):
		for key in (None, "", "nonsense", "wsk_" + "0" * 12 + "." + "x" * 40):
			with self.subTest(key=str(key)[:10]):
				status, body, response = self.get("products", key=key)
				self.assertEqual(status, 401)
				self.assertEqual(body["error"]["code"], "invalid_key")
				self.assertEqual(response.headers["Cache-Control"], "no-store")

	def test_a_suspended_access_is_a_401_at_once_and_resuming_brings_it_back(self):
		self.assertEqual(self.get("products", args={"page_size": 1})[0], 200)
		access.suspend(shop.CUSTOMER)
		status, body, _response = self.get("products")
		self.assertEqual((status, body["error"]["code"]), (401, "access_suspended"))
		self.assertEqual(self.get("products", key="B", args={"page_size": 1})[0], 200, "another reseller is not cut")
		access.resume(shop.CUSTOMER)
		self.assertEqual(self.get("products", args={"page_size": 1})[0], 200)

	def test_the_index_and_the_contract_need_no_key(self):
		status, body, _response = self.get("", key=None)
		self.assertEqual((status, body["version"]), (200, "v1"))
		status, text, response = self.get("openapi.yaml", key=None)
		self.assertEqual(status, 200)
		self.assertIn("yaml", response.content_type)
		self.assertIn("/products/{code}", text)
		self.assertTrue(os.path.exists(os.path.join(os.path.dirname(v1.__file__), "openapi.yaml")))

	def test_the_contract_is_valid_yaml_and_names_every_address_the_door_serves(self):
		try:
			import yaml
		except ImportError:
			self.skipTest("PyYAML is not installed on this bench")
		spec = yaml.safe_load(self.get("openapi.yaml", key=None)[1])
		self.assertEqual(spec["info"]["version"], "v1")
		self.assertEqual(set(spec["paths"]), {"/products", "/products/{code}", "/orders", "/orders/{id}"})
		self.assertEqual(set(spec["paths"]["/orders"]), {"get", "post"})
		self.assertEqual(spec["components"]["securitySchemes"]["ApiKey"]["name"], "X-API-Key")

	def test_an_unknown_address_and_a_wrong_method_are_told_so(self):
		self.assertEqual(self.get("nothing")[0], 404)
		status, body, response = self.call("DELETE", "orders")
		self.assertEqual((status, body["error"]["code"], response.headers["Allow"]), (405, "method_not_allowed", "GET, POST"))
		self.assertEqual(self.call("POST", "products", body={})[0], 405)

	def test_the_allowance_is_a_429_with_a_retry_after(self):
		frappe.db.set_value(DOCTYPE, shop.CUSTOMER, "calls_per_minute", 2)
		self.assertEqual(self.get("products", args={"page_size": 1})[0], 200)
		self.assertEqual(self.get("products", args={"page_size": 1})[0], 200)
		status, body, response = self.get("products", args={"page_size": 1})
		self.assertEqual((status, body["error"]["code"], response.headers["Retry-After"]), (429, "rate_limited", "60"))

	def test_an_unexpected_failure_is_a_500_that_says_nothing_of_the_inside(self):
		with mock.patch.object(v1, "list_products", side_effect=RuntimeError("secret detail")), mock.patch("frappe.log_error") as logged:
			status, body, _response = self.get("products")
		self.assertEqual((status, body["error"]["code"]), (500, "internal_error"))
		self.assertNotIn("secret detail", json.dumps(body))
		self.assertTrue(logged.called)

	# --- reading the catalogue ---------------------------------------------------------------------------

	def codes(self, body):
		return [product["code"] for product in body["products"]]

	def ours(self, **args):
		"""The listing narrowed to the tests' own products (their codes carry the tests' prefix): a real site holds hundreds."""
		return self.get("products", args={"search": shop.PREFIX, "page_size": 100, **args})

	def test_the_list_holds_what_the_shop_shows_with_its_variants_and_never_a_model_or_a_hidden_product(self):
		status, body, _response = self.ours()
		self.assertEqual(status, 200)
		codes = self.codes(body)
		self.assertTrue({shop.FIRST, shop.SECOND, shop.THIRD, *shop.variants()} <= set(codes))
		self.assertFalse({shop.MODEL, shop.HIDDEN, shop.SOLD} & set(codes))
		self.assertEqual(body["total"], len(codes))

	def test_a_variant_the_shop_hides_from_its_listings_is_still_listed_and_orderable(self):
		snapshot = snapshot_webshop_settings(["hide_variants"])
		self.addCleanup(restore_webshop_settings, snapshot)
		frappe.db.set_single_value("Webshop Settings", "hide_variants", 1)
		frappe.db.commit()
		variant = shop.variants()[0]
		self.assertIn(variant, self.codes(self.ours()[1]))
		self.assertEqual(self.get(f"products/{variant}")[0], 200)

	def test_the_list_carries_no_price_and_no_quantity_of_stock(self):
		body = self.ours()[1]
		first = next(product for product in body["products"] if product["code"] == shop.FIRST)
		self.assertFalse({"price", "currency", "stock", "qty", "stock_qty", "purchase_price"} & set(first))
		self.assertIn(first["availability"], ("in_stock", "out_of_stock", "backorder"))
		self.assertEqual(first["name"], f"{shop.FIRST} name")
		self.assertEqual(first["brand"], shop.BRAND_A)
		self.assertRegex(first["modified"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$")

	def test_a_page_has_its_size_and_the_next_page_the_next_products(self):
		first = self.ours(page_size=2, page=1)[1]
		second = self.ours(page_size=2, page=2)[1]
		self.assertEqual((len(first["products"]), first["page"], first["page_size"]), (2, 1, 2))
		self.assertGreater(first["total"], 2)
		self.assertFalse(set(self.codes(first)) & set(self.codes(second)))

	def test_a_catalogue_can_be_walked_by_modified_since_without_missing_a_product(self):
		everything = self.ours()[1]
		self.assertEqual(self.ours(modified_since="2999-01-01T00:00:00Z")[1]["products"], [])
		self.assertEqual(self.ours(modified_since="2000-01-01")[1]["total"], everything["total"])
		moments = [product["modified"] for product in everything["products"]]
		self.assertEqual(moments, sorted(moments), "sorted by modified, so that a sync can walk it")

	def test_the_filters_narrow_the_list(self):
		by_brand = self.ours(brand=shop.BRAND_B)[1]
		self.assertTrue(all(product["brand"] == shop.BRAND_B for product in by_brand["products"]))
		self.assertIn(shop.THIRD, self.codes(by_brand))
		by_model = self.get("products", args={"model": shop.MODEL})[1]
		self.assertEqual(sorted(self.codes(by_model)), sorted(shop.variants()))
		self.assertTrue(all(product["model"] == shop.MODEL for product in by_model["products"]))
		by_search = self.get("products", args={"search": shop.FIRST})[1]
		self.assertEqual(self.codes(by_search), [shop.FIRST])
		by_group = self.ours(item_group=shop.PARENT_GROUP)[1]
		self.assertIn(shop.FIRST, self.codes(by_group), "a category brings its sub-categories")
		self.assertNotIn(shop.THIRD, self.codes(by_group))
		self.assertEqual(self.get("products", args={"item_group": "no such group"})[1]["products"], [])

	def test_a_parameter_that_is_not_one_is_a_422_naming_it(self):
		for args in ({"page_size": 0}, {"page_size": 101}, {"page": 0}, {"page": "x"}, {"modified_since": "yesterday"}, {"search": "x" * 141}):
			with self.subTest(args=args):
				status, body, _response = self.get("products", args=args)
				self.assertEqual((status, body["error"]["code"]), (422, "invalid_parameter"))

	def test_the_price_of_one_product_is_the_callers_own_and_two_customers_read_two_prices(self):
		_status, first, _response = self.get(f"products/{shop.FIRST}")
		_status, second, _response = self.get(f"products/{shop.FIRST}", key="B")
		self.assertEqual(first["price"], 80.0, "on the first reseller's list")
		self.assertEqual(second["price"], 70.0, "on the second's: not the same figure, not the shop's 100")
		self.assertEqual(first["currency"], second["currency"])
		self.assertEqual(self.get(f"products/{shop.SECOND}")[1]["price"], 40.0)
		self.assertEqual(self.get(f"products/{shop.SECOND}", key="B")[1]["price"], 35.0)

	def test_a_product_without_a_price_says_null_and_a_variant_has_its_own_price(self):
		self.assertIsNone(self.get(f"products/{NO_PRICE}")[1]["price"])
		prices = sorted(self.get(f"products/{code}")[1]["price"] for code in shop.variants())
		self.assertEqual(prices, [48.0, 72.0])

	def test_the_detail_tells_what_the_product_is(self):
		_status, product, _response = self.get(f"products/{shop.FIRST}")
		self.assertEqual(product["description"], "A short text.")
		self.assertRegex(product["image"], r"^https?://[^/]+/files/")
		self.assertEqual(product["images"], [product["image"]])
		self.assertEqual(product["model"], None)
		self.assertEqual(self.get(f"products/{shop.variants()[0]}")[1]["model"], shop.MODEL)

	def test_a_product_the_shop_does_not_offer_or_a_model_does_not_exist_for_a_key(self):
		for code in (shop.HIDDEN, shop.SOLD, shop.MODEL, "no such product", "x" * 300):
			with self.subTest(code=code[:20]):
				status, body, _response = self.get(f"products/{code}")
				self.assertEqual((status, body["error"]["code"]), (404, "not_found"))

	def test_the_shops_own_price_is_in_no_answer(self):
		figures = set()

		def walk(value):
			if isinstance(value, dict):
				for item in value.values():
					walk(item)
			elif isinstance(value, list):
				for item in value:
					walk(item)
			elif isinstance(value, (int, float)) and not isinstance(value, bool):
				figures.add(float(value))

		walk(self.ours()[1]["products"])
		for code in (shop.FIRST, shop.SECOND):
			walk(self.get(f"products/{code}")[1])
		walk(self.order(key="figures")[1])
		self.assertIn(80.0, figures, "the test reads real figures")
		self.assertFalse(SHOP_PRICES & figures)

	def test_the_availability_is_the_shops_own_rule_and_never_a_quantity(self):
		listed = self.ours()[1]["products"]
		expected = stock.bulk_availability([product["code"] for product in listed])
		names = {stock.IN_STOCK: "in_stock", stock.OUT_OF_STOCK: "out_of_stock", stock.BACK_ORDER: "backorder"}
		for product in listed:
			with self.subTest(code=product["code"]):
				self.assertEqual(product["availability"], names[expected[product["code"]].availability])

	# --- ordering ----------------------------------------------------------------------------------------

	def test_an_order_is_made_as_a_draft_at_the_callers_price_for_the_caller(self):
		status, order, _response = self.order(pairs=((shop.FIRST, 2), (shop.SECOND, 1)))
		self.assertEqual(status, 201)
		self.assertEqual((order["submitted"], order["reference"], order["status"]), (False, "PO-order-1", "Draft"))
		self.assertEqual({line["item_code"]: line["price"] for line in order["lines"]}, {shop.FIRST: 80.0, shop.SECOND: 40.0})
		self.assertEqual(order["net_total"], 200.0)
		record = frappe.get_doc("Sales Order", order["id"])
		self.assertEqual((record.customer, record.docstatus, record.po_no, record.owner), (shop.CUSTOMER, 0, "PO-order-1", shop.USER))

	def test_the_price_never_comes_from_the_caller(self):
		for body in (
			{"idempotency_key": "k1", "lines": [{"item_code": shop.FIRST, "qty": 1, "rate": 1}]},
			{"idempotency_key": "k2", "lines": [{"item_code": shop.FIRST, "qty": 1, "price": 1}]},
			{"idempotency_key": "k3", "lines": self.lines((shop.FIRST, 1)), "total": 1},
			{"idempotency_key": "k4", "lines": self.lines((shop.FIRST, 1)), "currency": "EUR"},
		):
			with self.subTest(body=list(body)):
				status, answer, _response = self.call("POST", "orders", body=body)
				self.assertIn(status, (422,))
				self.assertIn(answer["error"]["code"], ("invalid_parameter", "invalid_body"))
		self.assertFalse(frappe.get_all("Sales Order", filters={"customer": shop.CUSTOMER}))

	def test_a_body_that_is_not_an_order_is_refused_before_anything_is_made(self):
		good = self.lines((shop.FIRST, 1))
		for body, code in (
			([], "invalid_body"),
			({"lines": good}, "invalid_idempotency_key"),
			({"idempotency_key": "has space", "lines": good}, "invalid_idempotency_key"),
			({"idempotency_key": "k", "lines": []}, "invalid_parameter"),
			({"idempotency_key": "k", "lines": good * 101}, "invalid_parameter"),
			({"idempotency_key": "k", "lines": self.lines((shop.FIRST, 0))}, "invalid_parameter"),
			({"idempotency_key": "k", "lines": self.lines((shop.FIRST, -1))}, "invalid_parameter"),
			({"idempotency_key": "k", "lines": self.lines((shop.FIRST, True))}, "invalid_parameter"),
			({"idempotency_key": "k", "lines": self.lines((shop.FIRST, "2"))}, "invalid_parameter"),
			({"idempotency_key": "k", "lines": self.lines((shop.FIRST, 1), (shop.FIRST, 2))}, "invalid_parameter"),
			({"idempotency_key": "k", "lines": good, "reference": "a<b"}, "invalid_parameter"),
			({"idempotency_key": "k", "lines": good, "requested_delivery_date": "2001-01-01"}, "invalid_parameter"),
			({"idempotency_key": "k", "lines": good, "requested_delivery_date": "tomorrow"}, "invalid_parameter"),
		):
			with self.subTest(code=code, body=str(body)[:40]):
				status, answer, _response = self.call("POST", "orders", body=body)
				self.assertEqual((status, answer["error"]["code"]), (422, code))
		self.assertFalse(frappe.get_all("Sales Order", filters={"customer": shop.CUSTOMER}))

	def test_a_body_that_is_not_json_or_too_large_is_refused(self):
		status, answer, _response = self.call("POST", "orders", body=None)
		self.assertEqual((status, answer["error"]["code"]), (400, "invalid_json"))
		status, answer, _response = self.call("POST", "orders", body={"idempotency_key": "k"}, length=300 * 1024)
		self.assertEqual((status, answer["error"]["code"]), (413, "body_too_large"))

	def test_lines_the_shop_cannot_serve_stop_the_whole_order_and_each_is_named(self):
		status, answer, _response = self.order(key="bad", pairs=((shop.FIRST, 1), (shop.HIDDEN, 1), (shop.MODEL, 1), (NO_PRICE, 1), ("no such", 1)))
		self.assertEqual((status, answer["error"]["code"]), (422, "invalid_lines"))
		found = {line["item_code"]: line["code"] for line in answer["error"]["details"]["lines"]}
		self.assertEqual(found, {shop.HIDDEN: "not_available", shop.MODEL: "not_available", NO_PRICE: "no_price", "no such": "not_available"})
		self.assertFalse(frappe.get_all("Sales Order", filters={"customer": shop.CUSTOMER}), "nothing was ordered")

	def test_the_stock_stops_a_line_and_says_so_without_a_quantity(self):
		def available(availability, qty):
			return mock.patch.object(v1.stock, "bulk_availability", return_value={shop.FIRST: frappe._dict(availability=availability, qty=qty)})

		with available(stock.OUT_OF_STOCK, 0):
			status, answer, _response = self.order(key="s1")
		self.assertEqual((status, answer["error"]["details"]["lines"][0]["code"]), (422, "out_of_stock"))
		with available(stock.IN_STOCK, 1):
			status, answer, _response = self.order(key="s2", pairs=((shop.FIRST, 2),))
			self.assertEqual((status, answer["error"]["details"]["lines"][0]["code"]), (422, "insufficient_stock"))
			self.assertEqual(set(answer["error"]["details"]["lines"][0]), {"item_code", "code", "message"}, "no quantity of stock is told")
			self.assertEqual(self.order(key="s3", pairs=((shop.FIRST, 1),))[0], 201)
		with available(stock.BACK_ORDER, 0):
			self.assertEqual(self.order(key="s4", pairs=((shop.FIRST, 5),))[0], 201, "the shop takes orders beyond its stock")

	def test_a_replayed_call_returns_the_order_it_made_and_makes_no_second(self):
		_status, made, _response = self.order(key="same")
		status, again, response = self.order(key="same")
		self.assertEqual((status, again["id"]), (200, made["id"]))
		self.assertEqual(response.headers["Idempotent-Replayed"], "true")
		self.assertEqual(frappe.db.count("Sales Order", {"customer": shop.CUSTOMER}), 1)

	def test_the_same_key_with_other_lines_is_refused_and_another_key_is_another_order(self):
		self.order(key="same")
		status, answer, _response = self.order(key="same", pairs=((shop.SECOND, 1),))
		self.assertEqual((status, answer["error"]["code"]), (422, "idempotency_conflict"))
		self.assertEqual(self.order(key="other")[0], 201)
		self.assertEqual(frappe.db.count("Sales Order", {"customer": shop.CUSTOMER}), 2)

	def test_two_resellers_may_use_the_same_key(self):
		self.assertEqual(self.order(key="shared")[0], 201)
		frappe.db.set_value(DOCTYPE, shop.OTHER_CUSTOMER, "scope_orders", 1)
		self.assertEqual(self.call("POST", "orders", key="B", body={"idempotency_key": "shared", "lines": self.lines((shop.FIRST, 1))})[0], 201)

	def test_a_dry_run_prices_and_checks_without_making_anything(self):
		status, order, _response = self.order(key="dry", dry_run=True)
		self.assertEqual((status, order["dry_run"], order["id"]), (200, True, None))
		self.assertEqual(order["net_total"], 160.0)
		self.assertFalse(frappe.get_all("Sales Order", filters={"customer": shop.CUSTOMER}))
		self.assertFalse(frappe.get_all("Partner API Order", filters={"customer": shop.CUSTOMER}))
		self.assertEqual(self.order(key="dry")[0], 201, "the key of a dry run is still free")

	def test_a_key_that_may_not_order_cannot_and_cannot_read_orders_either(self):
		self.order(key="mine")
		status, answer, _response = self.call("POST", "orders", key="B", body={"idempotency_key": "x", "lines": self.lines((shop.FIRST, 1))})
		self.assertEqual((status, answer["error"]["code"]), (403, "scope_missing"))
		self.assertEqual(self.get("orders", key="B")[0], 403)
		self.assertEqual(self.get("orders/anything", key="B")[0], 403)

	def test_an_access_allowed_to_submit_submits(self):
		frappe.db.set_value(DOCTYPE, shop.CUSTOMER, "submit_orders", 1)
		status, order, _response = self.order(key="submit")
		self.assertEqual((status, order["submitted"]), (201, True))
		self.assertEqual(frappe.db.get_value("Sales Order", order["id"], "docstatus"), 1)

	# --- reading orders ------------------------------------------------------------------------------------

	def test_a_reseller_reads_their_orders_and_one_order_with_its_lines(self):
		_status, made, _response = self.order(key="one")
		status, listed, _response = self.get("orders")
		self.assertEqual(status, 200)
		self.assertEqual([order["id"] for order in listed["orders"]], [made["id"]])
		self.assertEqual(listed["total"], 1)
		_status, one, _response = self.get(f"orders/{made['id']}")
		self.assertEqual(one["lines"][0]["item_code"], shop.FIRST)
		self.assertEqual(one["grand_total"], made["grand_total"])
		self.assertIn("confirmed_delivery_date", one)
		self.assertEqual(self.get("orders", args={"reference": "PO-one"})[1]["total"], 1)
		self.assertEqual(self.get("orders", args={"reference": "PO-two"})[1]["total"], 0)
		self.assertEqual(self.get("orders", args={"modified_since": "2999-01-01T00:00:00Z"})[1]["orders"], [])

	def test_an_order_of_somebody_else_does_not_exist_for_a_key(self):
		frappe.db.set_value(DOCTYPE, shop.OTHER_CUSTOMER, "scope_orders", 1)
		_status, mine, _response = self.order(key="mine")
		status, body, _response = self.get(f"orders/{mine['id']}", key="B")
		self.assertEqual((status, body["error"]["code"]), (404, "not_found"))
		self.assertEqual(self.get("orders", key="B")[1]["orders"], [])
		other = self.call("POST", "orders", key="B", body={"idempotency_key": "b1", "lines": self.lines((shop.FIRST, 1))})[1]
		self.assertEqual(other["lines"][0]["price"], 70.0, "an order is priced on the caller's own list")
		self.assertEqual(self.get(f"orders/{other['id']}")[0], 404, "and the first reseller cannot read it")

	def test_an_order_made_through_the_key_is_the_customers_in_their_portal_too(self):
		_status, made, _response = self.order(key="portal")
		self.assertTrue(frappe.has_website_permission(frappe.get_doc("Sales Order", made["id"]), user=shop.USER))
