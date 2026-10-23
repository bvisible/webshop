# //// Neoffice — added file (no upstream equivalent). The page of a product that has no recommendation of its own offers
# //// four items of its group drawn at random. frappe 15.124 refused the `RAND()` that drew them ("Cannot use RAND() in
# //// order/group by": an order_by may only call a short list of functions), so the page of every such product failed.
import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.doctype.webshop_settings.test_webshop_settings import setup_webshop_settings
from webshop.webshop.doctype.website_item.test_website_item import create_regular_web_item

GROUP = "Test Auto Recommendation Group"
CODES = [f"Test Auto Recommendation {n}" for n in range(1, 7)]


class TestAutoRecommendations(FrappeTestCase):
	def setUp(self):
		# a group of their own: the other tests of the site leave published Website Items in the usual ones
		if not frappe.db.exists("Item Group", GROUP):
			frappe.get_doc(
				{"doctype": "Item Group", "item_group_name": GROUP, "parent_item_group": "All Item Groups"}
			).insert()
		self.web_items = [create_regular_web_item(code, item_args={"item_group": GROUP}) for code in CODES]
		for web_item in self.web_items:
			web_item.set("recommended_items", [])
			web_item.published = 1
			web_item.save()
		setup_webshop_settings({"enable_recommendations": 1, "show_price": 0})
		frappe.local.shopping_cart_settings = None
		self.addCleanup(self.clean)

	def clean(self):
		for web_item in self.web_items:
			if frappe.db.exists("Website Item", web_item.name):
				frappe.delete_doc("Website Item", web_item.name, force=True, ignore_permissions=True)
		for code in CODES:
			if frappe.db.exists("Item", code):
				frappe.delete_doc("Item", code, force=True, ignore_permissions=True)
		if frappe.db.exists("Item Group", GROUP):
			frappe.delete_doc("Item Group", GROUP, force=True, ignore_permissions=True)

	def test_a_product_without_its_own_recommendations_is_offered_four_others_of_its_group(self):
		context = frappe._dict(route=self.web_items[0].route or "test-auto-recommendation")
		self.web_items[0].get_context(context)
		offered = [row.item_code for row in (context.recommended_items or [])]
		self.assertEqual(len(offered), 4, offered)
		self.assertNotIn(CODES[0], offered)
		self.assertEqual(len(set(offered)), 4)
		self.assertTrue(set(offered) <= set(CODES[1:]), offered)

	def test_a_group_with_fewer_candidates_gives_what_it_has(self):
		for web_item in self.web_items[3:]:
			web_item.published = 0
			web_item.save()
		context = frappe._dict(route=self.web_items[0].route or "test-auto-recommendation")
		self.web_items[0].get_context(context)
		offered = {row.item_code for row in (context.recommended_items or [])}
		self.assertEqual(offered, set(CODES[1:3]))
