import frappe
from frappe.tests.utils import FrappeTestCase

from erpnext.controllers.item_variant import create_variant
from webshop.webshop.doctype.webshop_settings.test_webshop_settings import (
	setup_webshop_settings,
)
from webshop.webshop.doctype.website_item.website_item import make_website_item
from webshop.webshop.variant_selector.utils import get_next_attribute_and_values
from webshop.webshop.tests.utils import (
	default_company,
	make_test_item,
	restore_webshop_settings,
	root_customer_group,
	selling_price_list,
	snapshot_webshop_settings,
)

test_dependencies = ["Item"]


def reconstruire_cache_variantes(item_code):
	"""Rebuild the variant cache here and now.

	The document hook only enqueues it on the "long" queue, and a queued job
	does not run inside a test: is_async stays True, so frappe.enqueue hands it
	to a worker that may not even exist on this machine.
	"""
	from webshop.webshop.variant_selector.item_variants_cache import ItemVariantsCacheManager

	cache = ItemVariantsCacheManager(item_code)
	cache.clear_cache()
	cache.build_cache()


def creer_attribut(nom, valeurs):
	"""An Item Attribute and its values, created only if the site lacks them."""
	if frappe.db.exists("Item Attribute", nom):
		return
	frappe.get_doc(
		{
			"doctype": "Item Attribute",
			"attribute_name": nom,
			# Single-letter abbreviations, as ERPNext's own fixtures use: the
			# variant codes below ("Test-Tshirt-Temp-S-R") are built from them.
			"item_attribute_values": [
				{"attribute_value": v, "abbr": v[0].upper()} for v in valeurs
			],
		}
	).insert(ignore_permissions=True)


class TestVariantSelector(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# Whatever an earlier run committed is still in the database, and
		# create_variant would hit "Duplicate entry 'Test-Tshirt-Temp-L-R'".
		cls._purger()

		# "Test Size" and "Test Colour" are ERPNext test fixtures, absent from a
		# real site: create them here so this suite carries its own data.
		creer_attribut("Test Size", ("Large", "Medium", "Small"))
		creer_attribut("Test Colour", ("Red", "Green"))

		template_item = make_test_item(
			"Test-Tshirt-Temp",
			**{
				# has_variantS. Without the s it is not a field of Item, so the
				# item was never a template and create_variant below produced a
				# variant with no item_code at all ("Item Code is required").
				"has_variants": 1,
				"variant_based_on": "Item Attribute",
				"attributes": [{"attribute": "Test Size"}, {"attribute": "Test Colour"}],
			},
		)

		# create L-R, L-G, M-R, M-G and S-R
		for size in (
			"Large",
			"Medium",
		):
			for colour in (
				"Red",
				"Green",
			):
				variant = create_variant("Test-Tshirt-Temp", {"Test Size": size, "Test Colour": colour})
				variant.save()

		variant = create_variant("Test-Tshirt-Temp", {"Test Size": "Small", "Test Colour": "Red"})
		variant.save()

		make_website_item(template_item)  # publish template not variants

		# Commit, or the rollback FrappeTestCase runs between tests takes these
		# fixtures with it and every test then reports the variants as missing.
		# The suite passed before only because an earlier run had left the same
		# items behind; from a clean database it never did.
		frappe.db.commit()

	@classmethod
	def _purger(cls):
		for nom in frappe.get_all(
			"Website Item", filters={"item_code": ("like", "Test-Tshirt-Temp%")}, pluck="name"
		):
			frappe.delete_doc("Website Item", nom, force=True, ignore_permissions=True)
		for nom in frappe.get_all("Item Price", filters={"item_code": ("like", "Test-Tshirt-Temp%")}, pluck="name"):
			frappe.delete_doc("Item Price", nom, force=True, ignore_permissions=True)
		# Variants before their template: the template cannot go while they link to it.
		for nom in frappe.get_all(
			"Item",
			filters={"item_code": ("like", "Test-Tshirt-Temp-%")},
			pluck="name",
		):
			frappe.delete_doc("Item", nom, force=True, ignore_permissions=True)
		if frappe.db.exists("Item", "Test-Tshirt-Temp"):
			frappe.delete_doc("Item", "Test-Tshirt-Temp", force=True, ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def tearDownClass(cls):
		cls._purger()
		super().tearDownClass()

	def test_item_attributes(self):
		"""
		Test if the right attributes are fetched in the popup.
		(Attributes must only come from active items)

		Attribute selection must not be linked to Website Items.
		"""
		from webshop.webshop.variant_selector.utils import get_attributes_and_values

		attr_data = get_attributes_and_values("Test-Tshirt-Temp")

		self.assertEqual(attr_data[0]["attribute"], "Test Size")
		self.assertEqual(attr_data[1]["attribute"], "Test Colour")
		self.assertEqual(len(attr_data[0]["values"]), 3)  # ['Small', 'Medium', 'Large']
		self.assertEqual(len(attr_data[1]["values"]), 2)  # ['Red', 'Green']

		# disable small red tshirt, now there are no small tshirts.
		# but there are some red tshirts
		small_variant = frappe.get_doc("Item", "Test-Tshirt-Temp-S-R")
		# Re-enable it whatever happens: leaving it disabled makes the NEXT test
		# see no small tshirt at all, and that one then fails for a reason of our
		# own making. It used to be re-enabled after the assertion below — which
		# is to say, never, on the run where the assertion failed.
		self.addCleanup(reconstruire_cache_variantes, "Test-Tshirt-Temp")
		self.addCleanup(self._reactiver, small_variant.name)

		small_variant.disabled = 1
		small_variant.save()
		# save() only enqueues the rebuild, on the "long" queue, and enqueue does
		# not run inline under tests (is_async=True, now=False). Without this the
		# cache still holds the disabled variant and the count below reads 3.
		reconstruire_cache_variantes("Test-Tshirt-Temp")

		attr_data = get_attributes_and_values("Test-Tshirt-Temp")

		# Only L and M attribute values must be fetched since S is disabled
		self.assertEqual(len(attr_data[0]["values"]), 2)  # ['Medium', 'Large']

	def _reactiver(self, nom):
		frappe.db.set_value("Item", nom, "disabled", 0)

	def test_next_item_variant_values(self):
		"""
		Test if on selecting an attribute value, the next possible values
		are filtered accordingly.
		Values that dont apply should not be fetched.
		E.g.
		There is a ** Small-Red ** Tshirt. No other colour in this size.
		On selecting ** Small **, only ** Red ** should be selectable next.
		"""
		next_values = get_next_attribute_and_values(
			"Test-Tshirt-Temp", selected_attributes={"Test Size": "Small"}
		)
		next_colours = next_values["valid_options_for_attributes"]["Test Colour"]
		filtered_items = next_values["filtered_items"]

		self.assertEqual(len(next_colours), 1)
		self.assertEqual(next_colours.pop(), "Red")
		self.assertEqual(len(filtered_items), 1)
		self.assertEqual(filtered_items.pop(), "Test-Tshirt-Temp-S-R")

	def test_exact_match_with_price(self):
		"""
		Test price fetching and matching of variant without Website Item
		"""
		from webshop.webshop.doctype.website_item.test_website_item import make_web_item_price

		frappe.set_user("Administrator")
		# Webshop Settings is a Single: rollback will not undo this once anything
		# commits, so put the shop's own values back when the test ends.
		self.addCleanup(
			restore_webshop_settings,
			snapshot_webshop_settings(
				("company", "enabled", "default_customer_group", "price_list", "show_price")
			),
		)
		# The shop's own company and lists, not ERPNext's Indian test fixtures:
		# those do not exist outside a test site, and the assertion below used to
		# demand a rupee-formatted string that only held for that one currency.
		setup_webshop_settings(
			{
				"company": default_company(),
				"enabled": 1,
				"default_customer_group": root_customer_group(),
				"price_list": selling_price_list(),
				"show_price": 1,
			}
		)

		make_web_item_price(
			item_code="Test-Tshirt-Temp-S-R",
			price_list_rate=100,
			price_list=selling_price_list(),
		)

		frappe.local.shopping_cart_settings = None  # clear cached settings values
		next_values = get_next_attribute_and_values(
			"Test-Tshirt-Temp", selected_attributes={"Test Size": "Small", "Test Colour": "Red"}
		)
		price_info = next_values["product_info"]["price"]

		self.assertEqual(next_values["exact_match"][0], "Test-Tshirt-Temp-S-R")
		self.assertEqual(price_info["price_list_rate"], 100.0)
		# Formatted in the shop's currency, whichever that is.
		self.assertIn("100.00", price_info["formatted_price_sales_uom"])
