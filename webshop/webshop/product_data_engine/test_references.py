# //// Neoffice — added file (no upstream equivalent): a product found by a reference typed whole, and
# //// its codes printed on its page. neoffice-maintenance#691, plan note 20 (B2, B4), 2026-09-26.
"""A reference typed whole finds its product (product_data_engine/references.py): its barcode, its
manufacturer's part number, and its supplier's reference when the shop allows it; and the product
page prints its EAN and manufacturer's reference in its characteristics (seo/facts.py
shown_identifiers)."""

import random
import string
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.product_data_engine import references
from webshop.webshop.product_data_engine.query import ProductQuery
from webshop.webshop.quick_order.api import resolve
from webshop.webshop.seo import facts
from webshop.webshop.tests.utils import (
	make_test_item,
	restore_webshop_settings,
	snapshot_webshop_settings,
)

SWITCHES = ("show_product_identifiers", "search_supplier_references")


def _with_check_digit(body: str) -> str:
	total = sum(int(digit) * (3 if position % 2 == 0 else 1) for position, digit in enumerate(reversed(body)))
	return body + str((10 - total % 10) % 10)


def _supplier():
	name = f"_Test SEO supplier {frappe.generate_hash(length=6)}"
	frappe.get_doc(
		{
			"doctype": "Supplier",
			"supplier_name": name,
			"supplier_group": frappe.db.get_value("Supplier Group", {}, "name"),
		}
	).insert(ignore_permissions=True)
	return name


class TestAReferenceFindsItsProduct(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.snapshot = snapshot_webshop_settings(SWITCHES)

	@classmethod
	def tearDownClass(cls):
		restore_webshop_settings(cls.snapshot)
		super().tearDownClass()

	def product(self, **references_of):
		code = f"_Test REF {frappe.generate_hash(length=8)}"
		properties = {}
		if references_of.get("barcode"):
			properties["barcodes"] = [{"barcode": references_of["barcode"], "barcode_type": "EAN"}]
		if references_of.get("supplier_ref"):
			properties["supplier_items"] = [{"supplier": _supplier(), "supplier_part_no": references_of["supplier_ref"]}]
		make_test_item(code, **properties)
		if references_of.get("mpn"):
			maker = f"_Test SEO maker {frappe.generate_hash(length=6)}"
			frappe.get_doc({"doctype": "Manufacturer", "short_name": maker}).insert(ignore_permissions=True)
			frappe.get_doc(
				{"doctype": "Item Manufacturer", "item_code": code, "manufacturer": maker, "manufacturer_part_no": references_of["mpn"]}
			).insert(ignore_permissions=True)
		return code

	def test_a_barcode_a_manufacturer_s_and_a_supplier_s_reference(self):
		ean = _with_check_digit("76" + "".join(random.choices(string.digits, k=10)))
		reference = f"SUP-{frappe.generate_hash(length=6)}"
		mpn = f"MPN-{frappe.generate_hash(length=6)}"
		code = self.product(barcode=ean, supplier_ref=reference, mpn=mpn)
		on = frappe._dict(search_supplier_references=1)
		# the EAN as it is printed, in groups
		self.assertEqual(references.items_referenced(f"{ean[0]} {ean[1:7]} {ean[7:]}", on), [code])
		self.assertEqual(references.items_referenced(mpn.lower(), on), [code])
		self.assertEqual(references.items_referenced(reference, on), [code])
		# the supplier's reference only where the shop allows it
		self.assertEqual(references.items_referenced(reference, frappe._dict(search_supplier_references=0)), [])
		# a fragment is not a reference
		self.assertEqual(references.items_referenced("SU", on), [])

	def test_the_catalogue_s_search_and_the_quick_order_find_it(self):
		frappe.db.set_single_value("Webshop Settings", "search_supplier_references", 1)
		frappe.local.shopping_cart_settings = None
		frappe.clear_cache(doctype="Webshop Settings")
		reference = f"SUP-{frappe.generate_hash(length=6)}"
		code = self.product(supplier_ref=reference)
		query = ProductQuery()
		query.build_search_filters(reference)
		self.assertIn(["item_code", "in", [code]], query.filters)
		self.assertEqual(query._search_words, [])
		# a reference two items carry names neither in the quick order
		self.product(supplier_ref=reference)
		self.assertIsNone(resolve(reference))

	def test_the_page_prints_the_codes_when_the_shop_shows_them(self):
		ean = _with_check_digit("76" + "".join(random.choices(string.digits, k=10)))
		code = self.product(barcode=ean, mpn="RR-2026")
		on, off = frappe._dict(show_product_identifiers=1), frappe._dict(show_product_identifiers=0)
		rows = facts.shown_identifiers(code, on)
		self.assertEqual(rows[0], ("EAN", ean))
		self.assertEqual(rows[1][1], "RR-2026")
		self.assertEqual(facts.shown_identifiers(code, off), [])
		self.assertEqual(facts.shown_identifiers(None, on), [])

	def test_the_characteristics_fold_carries_them(self):
		source = (Path(__file__).resolve().parents[2] / "templates" / "generators" / "item" / "item_details.html").read_text()
		start = source.index("{% set _codes_host")
		end = source.index("{% if brand_info %}", start)
		# the fold's markup, closed where the brand's fold would begin
		snippet = source[start:end] + "</div>{% endif %}"
		html = frappe.render_template(
			snippet, {"shown_identifiers": [("EAN", "7612345678900"), ("Manufacturer's reference", "RR<1>")], "doc": frappe._dict(item_code="X")}
		)
		self.assertIn('data-codes-host', html)
		self.assertIn("<th class=\"spec-label\">EAN</th>", html)
		self.assertIn("RR&lt;1&gt;", html)
		self.assertNotIn(" hidden", html)
		# a model's page draws the fold hidden, for the variant selector to fill
		model = frappe.render_template(
			snippet,
			{"shown_identifiers": [], "show_product_identifiers": 1, "group_model": "M", "doc": frappe._dict(item_code="M")},
		)
		self.assertIn(" hidden", model)
		self.assertIn("data-codes-host", model)
		# a shop that does not show them draws nothing
		nothing = frappe.render_template(snippet, {"shown_identifiers": [], "show_product_identifiers": 0, "doc": frappe._dict(item_code="X")})
		self.assertNotIn("wsp-specs", nothing)
