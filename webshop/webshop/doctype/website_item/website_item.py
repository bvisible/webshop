# -*- coding: utf-8 -*-
# Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from erpnext.stock.doctype.item.item import Item

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, random_string
from frappe.website.doctype.website_slideshow.website_slideshow import get_slideshow
from frappe.website.website_generator import WebsiteGenerator

from webshop.webshop.doctype.item_review.item_review import get_item_reviews
from webshop.webshop.redisearch_utils import (
    delete_item_from_index,
    insert_item_to_index,
    update_index_for_item,
)
from webshop.webshop.shopping_cart.cart import _set_price_list
from webshop.webshop.doctype.override_doctype.item_group import (
    get_parent_item_groups,
    invalidate_cache_for,
)
from erpnext.stock.doctype.item.item import Item
from erpnext.utilities.product import get_price
from webshop.webshop.shopping_cart.cart import get_party
from webshop.webshop.variant_selector.item_variants_cache import (
    ItemVariantsCacheManager,
)


class WebsiteItem(WebsiteGenerator):
	website = frappe._dict(
		page_title_field="web_item_name",
		condition_field="published",
		template="templates/generators/item/item.html",
		no_cache=1,
	)

	def autoname(self):
		# use naming series to accomodate items with same name (different item code)
		from frappe.model.naming import get_default_naming_series, make_autoname

		naming_series = get_default_naming_series("Website Item")
		if not self.name and naming_series:
			self.name = make_autoname(naming_series, doc=self)

	def onload(self):
		super(WebsiteItem, self).onload()

	def validate(self):
		super(WebsiteItem, self).validate()

		if not self.item_code:
			frappe.throw(_("Item Code is required"), title=_("Mandatory"))

		self.validate_duplicate_website_item()
		self.validate_website_image()
		self.make_thumbnail()
		self.publish_unpublish_desk_item(publish=True)

		if not self.get("__islocal"):
			wig = frappe.qb.DocType("Website Item Group")
			query = (
				frappe.qb.from_(wig)
				.select(wig.item_group)
				.where(
					(wig.parentfield == "website_item_groups")
					& (wig.parenttype == "Website Item")
					& (wig.parent == self.name)
				)
			)
			result = query.run(as_list=True)

			self.old_website_item_groups = [x[0] for x in result]

	def on_update(self):
		invalidate_cache_for_web_item(self)
		self.update_template_item()

	def on_trash(self):
		super(WebsiteItem, self).on_trash()
		delete_item_from_index(self)
		self.publish_unpublish_desk_item(publish=False)

	def validate_duplicate_website_item(self):
		existing_web_item = frappe.db.exists(
			"Website Item", {"item_code": self.item_code}
		)
		if existing_web_item and existing_web_item != self.name:
			message = _("Website Item already exists against Item {0}").format(
				frappe.bold(self.item_code)
			)
			frappe.throw(message, title=_("Already Published"))

	def publish_unpublish_desk_item(self, publish=True):
		if (
			frappe.db.get_value("Item", self.item_code, "published_in_website")
			and publish
		):
			return  # if already published don't publish again
		frappe.db.set_value("Item", self.item_code, "published_in_website", publish)

	def make_route(self):
		"""Called from set_route in WebsiteGenerator."""
		if not self.route:
			return (
				cstr(frappe.db.get_value("Item Group", self.item_group, "route"))
				+ "/"
				+ self.scrub(
					(self.item_name if self.item_name else self.item_code)
					+ "-"
					+ random_string(5)
				)
			)

	def update_template_item(self):
		"""Publish Template Item if Variant is published."""
		if self.variant_of:
			if self.published:
				# show template
				template_item = frappe.get_doc("Item", self.variant_of)

				if not template_item.published_in_website:
					template_item.flags.ignore_permissions = True
					make_website_item(template_item)

	def validate_website_image(self):
		if frappe.flags.in_import:
			return

		"""Validate if the website image is a public file"""
		if not self.website_image:
			return

		# find if website image url exists as public
		file_doc = frappe.get_all(
			"File",
			filters={"file_url": self.website_image},
			fields=["name", "is_private"],
			order_by="is_private asc",
			limit_page_length=1,
		)

		if file_doc:
			file_doc = file_doc[0]

		if not file_doc:
			frappe.msgprint(
				_("Website Image {0} attached to Item {1} cannot be found").format(
					self.website_image, self.name
				)
			)

			self.website_image = None

		elif file_doc.is_private:
			frappe.msgprint(_("Website Image should be a public file or website URL"))

			self.website_image = None

	def make_thumbnail(self):
		"""Make a thumbnail of `website_image`"""
		if frappe.flags.in_import or frappe.flags.in_migrate:
			return

		import requests.exceptions

		db_website_image = frappe.db.get_value(self.doctype, self.name, "website_image")
		if not self.is_new() and self.website_image != db_website_image:
			self.thumbnail = None

		if self.website_image and not self.thumbnail:
			file_doc = None
			
			# Check if the file exists
			existing_files = frappe.get_all(
				"File",
				filters={
					"file_url": self.website_image
				},
				fields=["name", "attached_to_doctype", "attached_to_name", "thumbnail_url"],
				limit=1
			)

			# If a file with this URL already exists
			if existing_files:
				try:
					# Use the existing file instead of creating a new one
					file_doc = frappe.get_doc("File", existing_files[0].name)
					
					# Add a reference to the current Website Item
					# Note: This approach maintains the file attached to its original doctype
					# while also using it for this Website Item
					if file_doc.thumbnail_url:
						self.thumbnail = file_doc.thumbnail_url
					else:
						# If the thumbnail doesn't exist, create it
						file_doc.make_thumbnail()
						self.thumbnail = file_doc.thumbnail_url
					return
				except Exception as e:
					frappe.log_error(
						"Image Debug - Error Using Existing File",
						f"Error using existing file: {str(e)}"
					)
			
			# Try to find a file already attached to this Website Item
			try:
				file_doc = frappe.get_doc(
					"File",
					{
						"file_url": self.website_image,
						"attached_to_doctype": "Website Item",
						"attached_to_name": self.name,
					},
				)
			except frappe.DoesNotExistError:
				frappe.log_error(
					"Image Debug - File Not Attached Yet",
					f"No file with URL {self.website_image} attached to {self.doctype} {self.name}"
				)
				pass
				# cleanup
				if frappe.local.message_log:
					frappe.local.message_log.pop()
			except (requests.exceptions.HTTPError, requests.exceptions.SSLError) as e:
				if isinstance(e, requests.exceptions.HTTPError):
					frappe.msgprint(
						_("Warning: Invalid attachment {0}").format(self.website_image)
					)
				elif isinstance(e, requests.exceptions.SSLError):
					frappe.msgprint(
						_("Warning: Invalid SSL certificate on attachment {0}").format(
							self.website_image
						)
					)
				self.website_image = None

			# If no file is found or an error occurred, create a new file
			if self.website_image and not file_doc:
				try:
					file_doc = frappe.get_doc(
						{
							"doctype": "File",
							"file_url": self.website_image,
							"attached_to_doctype": "Website Item",
							"attached_to_name": self.name,
						}
					).save()

				except Exception as e:
					frappe.log_error(
						"Image Debug - Error Creating File",
						f"Error creating file: {str(e)}"
					)
					self.website_image = None

			# If we finally have a file, ensure it has a thumbnail
			if file_doc:
				if not file_doc.thumbnail_url:
					file_doc.make_thumbnail()

				self.thumbnail = file_doc.thumbnail_url

	def get_context(self, context):
		context.show_search = True
		context.search_link = "/search"
		context.body_class = "product-page"

		context.parents = get_parent_item_groups(
			self.item_group, from_item=True
		)  # breadcumbs
		self.attributes = frappe.get_all(
			"Item Variant Attribute",
			fields=["attribute", "attribute_value"],
			filters={"parent": self.item_code},
		)

		if self.slideshow:
			context.update(get_slideshow(self))

		self.set_metatags(context)
		self.set_shopping_cart_data(context)

		settings = context.shopping_cart.cart_settings
		
		# Add loyalty points information
		if settings.enable_loyalty_points:
			from webshop.webshop.utils.loyalty_points import format_loyalty_points_message
			
			product_info = context.shopping_cart.get("product_info", {})
			price_info = product_info.get("price", {})
			
			if price_info and price_info.get("price_list_rate"):
				customer = frappe.session.user if frappe.session.user != "Guest" else None
				if customer or settings.show_loyalty_points_for_guests:
					loyalty_info = format_loyalty_points_message(
						self.item_code, 
						price_info.get("price_list_rate"), 
						1, 
						customer
					)
					if loyalty_info and loyalty_info.get("earned_text"):
						context.loyalty_points_info = loyalty_info

		self.get_product_details_section(context)

		if settings.get("enable_reviews"):
			reviews_data = get_item_reviews(self.name)
			context.update(reviews_data)
			context.reviews = context.reviews[:4]

		context.wished = False
		if frappe.db.exists(
			"Wishlist Item",
			{"item_code": self.item_code, "parent": frappe.session.user},
		):
			context.wished = True

		context.user_is_customer = check_if_user_is_customer()

		context.recommended_items = None
		if settings and settings.enable_recommendations:
			context.recommended_items = self.get_recommended_items(settings)
			
			# If no manual recommendations, get auto recommendations with prices
			if not context.recommended_items:
				auto_items = frappe.get_all("Website Item", 
					filters={
						"published": 1,
						"item_group": self.item_group,
						"name": ["!=", self.name]
					},
					fields=["item_code", "web_item_name as website_item_name", "route", "thumbnail as website_item_thumbnail", "website_image"],
					limit=4,
					order_by="RAND()"
				)
				
				if auto_items and settings.show_price:
					from erpnext.utilities.product import get_price
					selling_price_list = settings.price_list
					
					for item in auto_items:
						if not item.website_item_thumbnail:
							item.website_item_thumbnail = item.website_image
						
						price_obj = get_price(
							item.item_code,
							selling_price_list,
							settings.default_customer_group,
							settings.company
						)
						if price_obj:
							from webshop.webshop.utils.utils import format_currency_value
							price_list_rate = price_obj.get("price_list_rate") or price_obj.get("rate")
							currency = price_obj.get("currency")
							item.price_info = {
								"price_list_rate": price_list_rate,
								"currency": currency,
								"formatted_price": format_currency_value(
									price_list_rate,
									currency=currency
								)
							}
				
				context.recommended_items = auto_items
		
		context.frequently_bought_together = None
		if settings and settings.enable_frequently_bought_together:
			from webshop.webshop.utils.frequently_bought_together import get_frequently_bought_together
			context.frequently_bought_together = get_frequently_bought_together(self.item_code)

		from webshop.webshop.shopping_cart.guest_cart import check_and_merge_guest_cart

		# Check and merge guest cart if needed
		check_and_merge_guest_cart()
		
		# Get bundle items if this is a product bundle
		self.set_bundle_items(context)
		
		return context

	def set_bundle_items(self, context):
		"""Fetch and set bundle items with their web URLs if this is a product bundle."""
		context.bundle_items = []
		
		# Check if this item is a product bundle
		if frappe.db.exists("Product Bundle", self.item_code):
			bundle_doc = frappe.get_doc("Product Bundle", self.item_code)
			
			for bundle_item in bundle_doc.items:
				item_info = {
					"item_code": bundle_item.item_code,
					"item_name": bundle_item.description or bundle_item.item_code,
					"qty": bundle_item.qty,
					"uom": bundle_item.uom,
					"web_item_name": None,
					"route": None,
					"website_image": None,
					"is_published": False,
					"in_stock": False,
					"stock_qty": 0,
					"on_backorder": False
				}
				
				# Check if the bundle item has a published Website Item
				website_item = frappe.db.get_value(
					"Website Item",
					{"item_code": bundle_item.item_code, "published": 1},
					["web_item_name", "route", "website_image", "thumbnail"],
					as_dict=True
				)
				
				if website_item:
					item_info.update({
						"web_item_name": website_item.web_item_name,
						"route": website_item.route,
						"website_image": website_item.thumbnail or website_item.website_image,
						"is_published": True
					})
				
				# Get stock information for the bundle item
				from webshop.webshop.doctype.website_item.website_item import get_item_warehouses
				
				# Check if item allows backorders
				item_doc = frappe.get_cached_value("Item", bundle_item.item_code, 
					["stock_uom", "is_stock_item", "allow_alternative_item"], as_dict=True)
				
				if item_doc and item_doc.get("is_stock_item"):
					warehouses_with_stock = get_item_warehouses(bundle_item.item_code)
					if warehouses_with_stock:
						total_stock = sum(w.actual_qty for w in warehouses_with_stock)
						item_info["stock_qty"] = total_stock
						item_info["in_stock"] = total_stock >= bundle_item.qty
					else:
						item_info["in_stock"] = False
					
					# Check for backorder settings
					if not item_info["in_stock"] and context.shopping_cart and context.shopping_cart.cart_settings:
						if context.shopping_cart.cart_settings.allow_items_not_in_stock:
							item_info["on_backorder"] = True
				else:
					# Non-stock items are always available
					item_info["in_stock"] = True
				
				# Get price information for the bundle item
				from erpnext.utilities.product import get_price
				
				selling_price_list = None
				customer_group = None
				company = frappe.defaults.get_user_default("company")
				
				if context.shopping_cart:
					if hasattr(context.shopping_cart, 'price_list') and context.shopping_cart.price_list:
						selling_price_list = context.shopping_cart.price_list.name
					elif hasattr(context.shopping_cart, 'cart_settings') and context.shopping_cart.cart_settings:
						selling_price_list = context.shopping_cart.cart_settings.price_list
						company = context.shopping_cart.cart_settings.company
				
				# Get customer group from the current customer if logged in
				if frappe.session.user != "Guest":
					customer = frappe.db.get_value("Customer", 
						{"email_id": frappe.session.user}, 
						["customer_group", "name"], 
						as_dict=True
					)
					if customer:
						customer_group = customer.customer_group
				
				# Fallback to Guest customer group
				if not customer_group:
					customer_group = frappe.db.get_single_value("Selling Settings", "customer_group") or "All Customer Groups"
				
				if selling_price_list and company:
					price_obj = get_price(
						bundle_item.item_code,
						selling_price_list,
						customer_group,
						company,
						bundle_item.qty or 1
					)
					if price_obj:
						item_info["price"] = price_obj.get("price_list_rate") or price_obj.get("rate")
						item_info["currency"] = price_obj.get("currency")
						item_info["formatted_price"] = frappe.utils.fmt_money(
							item_info["price"], 
							currency=item_info["currency"]
						) if item_info.get("price") else None
				
				context.bundle_items.append(item_info)

	def set_selected_attributes(self, variants, context, attribute_values_available):
		for variant in variants:
			variant.attributes = frappe.get_all(
				"Item Variant Attribute",
				filters={"parent": variant.name},
				fields=["attribute", "attribute_value as value"],
			)

			# make an attribute-value map for easier access in templates
			variant.attribute_map = frappe._dict(
				{attr.attribute: attr.value for attr in variant.attributes}
			)

			for attr in variant.attributes:
				values = attribute_values_available.setdefault(attr.attribute, [])
				if attr.value not in values:
					values.append(attr.value)

				if variant.name == context.variant.name:
					context.selected_attributes[attr.attribute] = attr.value

	def set_attribute_values(self, attributes, context, attribute_values_available):
		for attr in attributes:
			values = context.attribute_values.setdefault(attr.attribute, [])

			if cint(
				frappe.db.get_value("Item Attribute", attr.attribute, "numeric_values")
			):
				for val in sorted(
					attribute_values_available.get(attr.attribute, []), key=flt
				):
					values.append(val)
			else:
				# get list of values defined (for sequence)
				for attr_value in frappe.db.get_all(
					"Item Attribute Value",
					fields=["attribute_value"],
					filters={"parent": attr.attribute},
					order_by="idx asc",
				):

					if attr_value.attribute_value in attribute_values_available.get(
						attr.attribute, []
					):
						values.append(attr_value.attribute_value)

	def set_metatags(self, context):
		context.metatags = frappe._dict({})

		safe_description = frappe.utils.to_markdown(self.description)

		context.metatags.url = frappe.utils.get_url() + "/" + context.route

		if context.website_image:
			if context.website_image.startswith("http"):
				url = context.website_image
			else:
				url = frappe.utils.get_url() + context.website_image
			context.metatags.image = url

		context.metatags.description = safe_description[:300]

		context.metatags.title = self.web_item_name or self.item_name or self.item_code

		context.metatags["og:type"] = "product"
		context.metatags["og:site_name"] = "ERPNext"

	def set_shopping_cart_data(self, context):
		from webshop.webshop.shopping_cart.product_info import (
			get_product_info_for_website,
		)

		context.shopping_cart = get_product_info_for_website(
			self.item_code, skip_quotation_creation=True
		)

	@frappe.whitelist()
	def copy_specification_from_item_group(self):
		self.set("website_specifications", [])
		if self.item_group:
			for label, desc in frappe.db.get_values(
				"Item Website Specification",
				{"parent": self.item_group},
				["label", "description"],
			):
				row = self.append("website_specifications")
				row.label = label
				row.description = desc

	def get_product_details_section(self, context):
		"""Get section with tabs or website specifications."""
		context.show_tabs = self.show_tabbed_section
		if self.show_tabbed_section and (self.tabs or self.website_specifications):
			context.tabs = self.get_tabs()
		else:
			context.website_specifications = self.website_specifications

	def get_tabs(self):
		tab_values = {}
		tab_values["tab_1_title"] = _("Product Details")
		tab_values["tab_1_content"] = frappe.render_template(
			"templates/generators/item/item_specifications.html",
			{
				"website_specifications": self.website_specifications,
				"show_tabs": self.show_tabbed_section,
			},
		)

		for row in self.tabs:
			tab_values[f"tab_{row.idx + 1}_title"] = _(row.label)
			tab_values[f"tab_{row.idx + 1}_content"] = row.content

		return tab_values

	def get_recommended_items(self, settings):
		ri = frappe.qb.DocType("Recommended Items")
		wi = frappe.qb.DocType("Website Item")

		query = (
			frappe.qb.from_(ri)
			.join(wi)
			.on(ri.item_code == wi.item_code)
			.select(
				ri.item_code,
				ri.route,
				ri.website_item_name.as_("web_item_name"),
				ri.website_item_thumbnail.as_("website_image"),
				wi.item_group,
			)
			.where((ri.parent == self.name) & (wi.published == 1))
			.orderby(ri.idx)
		)
		items = query.run(as_dict=True)

		if settings.show_price:
			is_guest = frappe.session.user == "Guest"
			# Show Price if logged in.
			# If not logged in and price is hidden for guest, skip price fetch.
			if is_guest and settings.hide_price_for_guest:
				return items

			selling_price_list = settings.price_list if not settings.enable_guest_cart else _set_price_list(settings, None)
			party = get_party()

			for item in items:
				item.price_info = get_price(
					item.item_code,
					selling_price_list,
					settings.default_customer_group,
					settings.company,
					party=party,
				)
				# Flatten price_info fields for carousel compatibility
				if item.price_info:
					from webshop.webshop.utils.utils import format_currency_value

					# Add formatted_price
					if item.price_info.get("price_list_rate") is not None:
						item.price_info["formatted_price"] = format_currency_value(
							item.price_info.get("price_list_rate"),
							currency=item.price_info.get("currency")
						)
						item["formatted_price"] = item.price_info["formatted_price"]

					# Add price and currency at item level
					item["price"] = item.price_info.get("price_list_rate")
					item["currency"] = item.price_info.get("currency")

					# Add MRP and discount fields
					if item.price_info.get("formatted_mrp"):
						item["formatted_mrp"] = item.price_info.get("formatted_mrp")
						item["mrp"] = item.price_info.get("mrp")

					if item.price_info.get("formatted_discount_percent"):
						item["discount"] = item.price_info.get("formatted_discount_percent")
						item["discount_percent"] = item.price_info.get("discount_percent_number", 0)

		return items


def invalidate_item_variants_cache_for_website(doc):
	"""
	Rebuild ItemVariantsCacheManager via Item or Website Item

	Args:
		doc (Item): item of which cache should be cleared
	"""
	item_code = None
	is_web_item = doc.get("published_in_website") or doc.get("published")

	if doc.has_variants and is_web_item:
		item_code = doc.item_code
	elif doc.variant_of and frappe.db.get_value(
		"Item", doc.variant_of, "published_in_website"
	):
		item_code = doc.variant_of

	if not item_code:
		return

	item_cache = ItemVariantsCacheManager(item_code)
	item_cache.rebuild_cache()


def invalidate_cache_for_web_item(doc):
	"""
	Invalidate Website Item Group cache and rebuild ItemVariantsCacheManager
	Args:
		doc (Item): document against which cache should be cleared
	"""
	invalidate_cache_for(doc, doc.item_group)

	website_item_groups = list(
		set(
			(doc.get("old_website_item_groups") or [])
			+ [
				d.item_group
				for d in doc.get({"doctype": "Website Item Group"})
				if d.item_group
			]
		)
	)

	for item_group in website_item_groups:
		invalidate_cache_for(doc, item_group)

	# Update Search Cache
	update_index_for_item(doc)

	invalidate_item_variants_cache_for_website(doc)


def on_doctype_update():
	# since route is a Text column, it needs a length for indexing
	frappe.db.add_index("Website Item", ["route(500)"])


def check_if_user_is_customer(user=None):
	from frappe.contacts.doctype.contact.contact import get_contact_name

	if not user:
		user = frappe.session.user

	contact_name = get_contact_name(user)
	customer = None

	if contact_name:
		contact = frappe.get_doc("Contact", contact_name)
		for link in contact.links:
			if link.link_doctype == "Customer":
				customer = link.link_name
				break

	return True if customer else False

@frappe.whitelist()
def get_item_warehouses(item_code):
	"""
	Get warehouses where the item has available stock
	"""
	bin_data = frappe.get_all("Bin", 
		filters={"item_code": item_code, "actual_qty": [">", 0]}, 
		fields=["warehouse", "actual_qty"],
		order_by="actual_qty desc"
	)
	return bin_data

@frappe.whitelist()
def make_website_item(doc, save=True):
	"""
	Make Website Item from Item. Used via Form UI or patch.
	"""
	if not doc:
		return

	if isinstance(doc, str):
		doc = json.loads(doc)

	if frappe.db.exists("Website Item", {"item_code": doc.get("item_code")}):
		message = _("Website Item already exists against {0}").format(
			frappe.bold(doc.get("item_code"))
		)
		frappe.throw(message, title=_("Already Published"))

	website_item = frappe.new_doc("Website Item")
	website_item.web_item_name = doc.get("item_name")

	# Define default warehouse (one with the most stock)
	warehouses_with_stock = get_item_warehouses(doc.get("item_code"))
	if warehouses_with_stock:
		website_item.website_warehouse = warehouses_with_stock[0].warehouse

	fields_to_map = [
		"item_code",
		"item_name",
		"item_group",
		"stock_uom",
		"brand",
		"has_variants",
		"variant_of",
		"description",
	]
	for field in fields_to_map:
		website_item.update({field: doc.get(field)})

	# Needed for publishing/mapping via Form UI only
	if not frappe.flags.in_migrate and (
		doc.get("image") and not website_item.website_image
	):
		website_item.website_image = doc.get("image")

	# Check if there are multiple images attached to the Item
	item_images = []
	
	# Add the main image first if it exists
	if doc.get("image"):
		item_images.append(doc.get("image"))
	
	# Get attached files
	try:
		# Check if there are files attached to the Item doctype directly
		attached_files = frappe.get_all(
			"File",
			filters={
				"attached_to_doctype": "Item",
				"attached_to_name": doc.get("item_code"),
				"is_private": 0
			},
			fields=["file_url"]
		)
		
		# Add attached file URLs that look like images and aren't already in our list
		for file_doc in attached_files:
			file_url = file_doc.file_url
			# Check if it's an image by extension
			if file_url and file_url not in item_images and (
				file_url.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'))
			):
				item_images.append(file_url)
				
	except Exception as e:
		frappe.log_error(f"Error fetching item images: {str(e)}")
	
	# Create a slideshow if we have more than one image
	if len(item_images) > 1:
		try:
			# Create a unique slideshow name
			slideshow_name = f"item-{doc.get('item_code')}-slideshow"
			
			# Check if slideshow already exists
			existing_slideshow = frappe.db.exists("Website Slideshow", slideshow_name)
			
			if existing_slideshow:
				# Retrieve and update existing slideshow
				slideshow = frappe.get_doc("Website Slideshow", slideshow_name)
				
				
				# Remove existing slideshow items
				slideshow.set("slideshow_items", [])
				
				# Re-add all current images to the slideshow
				for idx, image_url in enumerate(item_images):
					slideshow.append("slideshow_items", {
						"image": image_url,
						"heading": doc.get("item_name") if idx == 0 else "",
						"description": doc.get("description") if idx == 0 else "",
						"url": f"/webshop/{doc.get('item_group','').lower().replace(' ', '-')}/{doc.get('item_name','').lower().replace(' ', '-') or doc.get('item_code','').lower()}"
					})
				
				slideshow.save()
				
				# Set the slideshow in the website item
				website_item.slideshow = slideshow.name
				
			else:
				# Create new slideshow
				slideshow = frappe.new_doc("Website Slideshow")
				slideshow.slideshow_name = slideshow_name
				
				# Add all images to the slideshow
				for idx, image_url in enumerate(item_images):
					slideshow.append("slideshow_items", {
						"image": image_url,
						"heading": doc.get("item_name") if idx == 0 else "",
						"description": doc.get("description") if idx == 0 else "",
						"url": f"/webshop/{doc.get('item_group','').lower().replace(' ', '-')}/{doc.get('item_name','').lower().replace(' ', '-') or doc.get('item_code','').lower()}"
					})
				
				slideshow.save()
				
				# Set the slideshow in the website item
				website_item.slideshow = slideshow.name
		except Exception as e:
			frappe.log_error(f"Error creating slideshow: {str(e)}")

	if not save:
		return website_item

	website_item.save()

	# Add to search cache
	insert_item_to_index(website_item)

	return [website_item.name, website_item.web_item_name]

@frappe.whitelist()
def has_website_permission_for_website_item(doc, ptype, user, verbose=False):
	# Check item group permissions for website

	if user == "Administrator":
		return True

	if frappe.has_permission("Website Item", ptype=ptype, doc=doc, user=user):
		return True

	if not frappe.db.get_single_value("Webshop Settings", "login_required_to_view_products"):
		return True

	return False

@frappe.whitelist()
def has_website_permission_for_item_group(doc, ptype, user, verbose=False):
	# Check item group permissions for website
	if user == "Administrator":
		return True

	if frappe.has_permission("Item Group", ptype=ptype, doc=doc, user=user):
		return True

	if not frappe.db.get_single_value("Webshop Settings", "login_required_to_view_products"):
		return True

	return False
