# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
import unittest
from frappe.utils import nowdate, add_days
from webshop.webshop.utils.discount_query import (
	get_discounted_items_query,
	get_discounted_items_count,
	get_items_with_pricing_rule_discount
)


class TestDiscountQuery(unittest.TestCase):
	"""Test cases for discount query functionality"""
	
	@classmethod
	def setUpClass(cls):
		"""Set up test data"""
		cls.price_list = "Standard Selling"
		cls.company = frappe.db.get_single_value("Global Defaults", "default_company")
		cls.customer_group = "All Customer Groups"
		
	def test_get_discounted_items_with_pricing_rule(self):
		"""Test fetching items with pricing rule discounts"""
		# Create a test pricing rule with discount
		pricing_rule = frappe.get_doc({
			"doctype": "Pricing Rule",
			"title": "Test Discount Rule",
			"apply_on": "Item Code",
			"item_code": frappe.db.get_value("Website Item", {"published": 1}, "item_code"),
			"selling": 1,
			"applicable_for": "Customer Group",
			"customer_group": self.customer_group,
			"rate_or_discount": "Discount Percentage",
			"discount_percentage": 10,
			"company": self.company,
			"valid_from": nowdate(),
			"valid_upto": add_days(nowdate(), 30),
			"promotional": 1
		})
		pricing_rule.insert(ignore_permissions=True)
		
		try:
			# Test the query
			results = get_discounted_items_query(
				price_list=self.price_list,
				company=self.company,
				customer_group=self.customer_group,
				limit=10
			)
			
			# Verify results contain the item with discount
			item_codes = [r.item_code for r in results]
			self.assertIn(pricing_rule.item_code, item_codes)
			
			# Check that discount percent is calculated
			for item in results:
				if item.item_code == pricing_rule.item_code:
					self.assertEqual(item.discount_percent, 10)
					self.assertIn("pricing_rule", item.discount_sources)
					
		finally:
			# Clean up
			pricing_rule.delete(ignore_permissions=True)
	
	def test_get_discounted_items_with_price_list_difference(self):
		"""Test fetching items with price list differences"""
		# Get a test item
		test_item = frappe.db.get_value("Website Item", {"published": 1}, "item_code")
		if not test_item:
			self.skipTest("No published website items found")
		
		# Create MRP price list if not exists
		if not frappe.db.exists("Price List", "MRP"):
			mrp_list = frappe.get_doc({
				"doctype": "Price List",
				"price_list_name": "MRP",
				"enabled": 1,
				"selling": 1,
				"show_in_website": 1
			})
			mrp_list.insert(ignore_permissions=True)
		
		# Set up different prices
		# Standard Selling Price
		if not frappe.db.exists("Item Price", {
			"item_code": test_item,
			"price_list": self.price_list
		}):
			frappe.get_doc({
				"doctype": "Item Price",
				"item_code": test_item,
				"price_list": self.price_list,
				"price_list_rate": 100,
				"selling": 1
			}).insert(ignore_permissions=True)
		
		# MRP Price (higher)
		if not frappe.db.exists("Item Price", {
			"item_code": test_item,
			"price_list": "MRP"
		}):
			frappe.get_doc({
				"doctype": "Item Price",
				"item_code": test_item,
				"price_list": "MRP",
				"price_list_rate": 120,
				"selling": 1
			}).insert(ignore_permissions=True)
		
		# Test the query
		results = get_discounted_items_query(
			price_list=self.price_list,
			company=self.company,
			customer_group=self.customer_group,
			limit=10
		)
		
		# Check if we got results with price list differences
		has_price_diff = any("price_list_diff" in (r.discount_sources or "") for r in results)
		if has_price_diff:
			# Verify discount calculation
			for item in results:
				if "price_list_diff" in (item.discount_sources or ""):
					# Discount should be (120-100)/120 * 100 = 16.67%
					self.assertGreater(item.discount_percent, 0)
	
	def test_get_discounted_items_count(self):
		"""Test counting discounted items"""
		count = get_discounted_items_count(
			price_list=self.price_list,
			company=self.company,
			customer_group=self.customer_group
		)
		
		# Count should be a non-negative integer
		self.assertIsInstance(count, int)
		self.assertGreaterEqual(count, 0)
	
	def test_get_items_with_promotional_pricing_rules(self):
		"""Test fetching items with promotional pricing rules"""
		results = get_items_with_pricing_rule_discount(
			price_list=self.price_list,
			company=self.company,
			customer_group=self.customer_group,
			limit=5
		)
		
		# All results should have pricing rule info
		for item in results:
			self.assertIn("effective_discount_percent", item)
			self.assertGreaterEqual(item.effective_discount_percent, 0)
	
	def test_filters_in_discount_query(self):
		"""Test applying filters to discount query"""
		# Get a specific item group
		item_group = frappe.db.get_value("Website Item", {"published": 1}, "item_group")
		
		if item_group:
			# Test with item group filter
			results = get_discounted_items_query(
				price_list=self.price_list,
				company=self.company,
				customer_group=self.customer_group,
				filters={"item_group": item_group},
				limit=10
			)
			
			# All results should be from the specified item group
			for item in results:
				self.assertEqual(item.item_group, item_group)