# //// Neoffice — added file (no upstream equivalent): tests of utils/variant_image.py.
import unittest
from unittest.mock import patch

import frappe

from webshop.webshop.utils.variant_image import inherit_template_images


def _get_all(doctype, filters=None, fields=None):
	if doctype == "Website Item":
		return [frappe._dict(item_code="HACHE", website_image="/files/west-hache.jpg"), frappe._dict(item_code="BARE", website_image=None)]
	if doctype == "Item":
		return [frappe._dict(name="BARE", image="/files/bare-item.jpg")]
	return []


class TestVariantImage(unittest.TestCase):
	def test_a_variant_without_a_picture_shows_its_template_s(self):
		rows = [
			frappe._dict(item_code="WEST1101", variant_of="HACHE", website_image=None),
			frappe._dict(item_code="WEST1102", variant_of="HACHE", website_image="/files/own.jpg"),
			frappe._dict(item_code="BARE-1", variant_of="BARE", website_image=None),
			frappe._dict(item_code="HACHE", variant_of=None, website_image=None),
		]
		with patch("webshop.webshop.utils.variant_image.frappe.get_all", side_effect=_get_all):
			inherit_template_images(rows)
		# the template's Website Item picture, then the Item's when the Website Item has none
		self.assertEqual(rows[0].website_image, "/files/west-hache.jpg")
		self.assertEqual(rows[2].website_image, "/files/bare-item.jpg")
		# a variant with its own picture keeps it, a template without one gets nothing
		self.assertEqual(rows[1].website_image, "/files/own.jpg")
		self.assertIsNone(rows[3].website_image)

	def test_nothing_to_inherit_costs_no_query(self):
		rows = [frappe._dict(item_code="HACHE", variant_of=None, website_image=None)]
		with patch("webshop.webshop.utils.variant_image.frappe.get_all") as get_all:
			inherit_template_images(rows)
		get_all.assert_not_called()
