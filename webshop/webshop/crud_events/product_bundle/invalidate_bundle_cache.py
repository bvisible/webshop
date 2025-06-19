import frappe
from frappe.utils import cint
from webshop.webshop.doctype.website_item.website_item import invalidate_cache_for_web_item


def execute(doc, method=None):
	"""Invalidate cache for website items that are part of this product bundle."""
	if not doc or not hasattr(doc, "new_item_code"):
		return
	
	# Clear cache for the main bundle item
	website_item = frappe.db.get_value(
		"Website Item",
		{"item_code": doc.new_item_code},
		"name"
	)
	
	if website_item:
		web_item_doc = frappe.get_doc("Website Item", website_item)
		invalidate_cache_for_web_item(web_item_doc)
	
	# Also clear cache for all component items in case they show related bundles
	if hasattr(doc, "items") and doc.items:
		for item in doc.items:
			component_website_item = frappe.db.get_value(
				"Website Item",
				{"item_code": item.item_code},
				"name"
			)
			if component_website_item:
				component_doc = frappe.get_doc("Website Item", component_website_item)
				invalidate_cache_for_web_item(component_doc)