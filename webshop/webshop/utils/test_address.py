# //// Neoffice — added file (no upstream equivalent).
"""The street and its number are written by one rule, on any site.

The address model is structured (erpnextswiss ADR-002): `address_line1` is the
street ALONE, the number lives in `custom_house_number`. webshop printed the two
back together inline, in two templates, each with its own concatenation. This
locks the single rule, and above all locks what makes it safe on a shop that
does not carry the Swiss setup at all.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.utils.address import compose_street_line, street_line


class TestAddressLine(FrappeTestCase):
	def test_the_number_follows_the_street(self):
		self.assertEqual(compose_street_line("Rue du Test", "1"), "Rue du Test 1")

	def test_a_missing_half_degrades_without_a_stray_space(self):
		"""Half an address is still an address; a trailing space is a defect."""
		self.assertEqual(compose_street_line("Rue du Test", ""), "Rue du Test")
		self.assertEqual(compose_street_line("Rue du Test", None), "Rue du Test")
		self.assertEqual(compose_street_line("", "1"), "1")
		self.assertEqual(compose_street_line(None, None), "")

	def test_it_reads_a_dict_and_a_document(self):
		"""Templates hold either, and both must answer the same."""
		as_dict = {"address_line1": "Rue du Test", "custom_house_number": "1"}
		self.assertEqual(street_line(as_dict), "Rue du Test 1")
		self.assertEqual(street_line(frappe._dict(as_dict)), "Rue du Test 1")
		self.assertEqual(street_line(None), "")

	def test_it_works_without_the_swiss_app(self):
		"""The rule belongs to erpnextswiss, webshop does not depend on it.

		The import sits inside the function on purpose: naming it at module level
		would make this module — and the cart, which imports it — fail to load on
		a plain ERPNext. The CI is exactly such a site, so this test passing here
		IS the proof.
		"""
		import webshop.webshop.utils.address as module

		source = frappe.read_file(module.__file__)
		for line in source.split("\n"):
			if line.startswith(("import ", "from ")):
				self.assertNotIn("erpnextswiss", line, "a top-level import would break a plain ERPNext")

	def test_the_address_book_asks_for_the_field_only_where_it_exists(self):
		"""`custom_house_number` is a custom field: naming it blindly is an SQL error."""
		from webshop.webshop.shopping_cart.cart import _has_house_number

		present = _has_house_number()
		self.assertIsInstance(present, bool)
		self.assertEqual(present, frappe.get_meta("Address").has_field("custom_house_number"))
