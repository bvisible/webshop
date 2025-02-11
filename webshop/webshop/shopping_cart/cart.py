# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt
import os
import json
import re
import random

import frappe
import frappe.defaults
from frappe import _, throw
from frappe.contacts.doctype.address.address import get_address_display
from frappe.contacts.doctype.contact.contact import get_contact_name
from frappe.utils import cint, cstr, flt, get_fullname
from frappe.utils.nestedset import get_root_of

from erpnext.accounts.utils import get_account_name
from erpnext.utilities.product import get_price
from webshop.webshop.doctype.webshop_settings.webshop_settings import (
	get_shopping_cart_settings,
)
from webshop.webshop.utils.product import get_web_item_qty_in_stock
from erpnext.selling.doctype.quotation.quotation import _make_sales_order
from erpnext.accounts.doctype.loyalty_program.loyalty_program import (
	get_loyalty_program_details_with_points,
)

class WebsitePriceListMissingError(frappe.ValidationError):
	pass

def set_cart_count(quotation=None):
	if cint(frappe.db.get_singles_value("Webshop Settings", "enabled")):
		if frappe.session.user == "Guest":
			# For guests, use guest cart
			from webshop.webshop.shopping_cart.guest_cart import create_guest_quotation
			result = create_guest_quotation()
			if result and result.get("success"):
				quotation = frappe.get_doc("Quotation", result.get("quotation_id"))
		else:
			# For logged in users, normal behavior
			if not quotation:
				quotation = _get_cart_quotation()
		
		cart_count = cstr(cint(quotation.get("total_qty") if quotation else 0))
		if hasattr(frappe.local, "cookie_manager"):
			frappe.local.cookie_manager.set_cookie("cart_count", cart_count)


@frappe.whitelist(allow_guest=True)
def get_cart_quotation(doc=None):
	party = get_party()
	if not party and frappe.session.user != "Guest":
		# If no party (guest without active cart)
		return {
			"doc": None,
			"shipping_addresses": [],
			"billing_addresses": [],
			"shipping_rules": [],
			"cart_settings": frappe.get_cached_doc("Webshop Settings")
		}

	if not doc:
		if frappe.session.user == "Guest":
			# For guests, find existing quotation
			guest_session_id = frappe.request.cookies.get('guest_session_id')
			if guest_session_id:
				quotation = frappe.get_all(
					"Quotation",
					fields=["name"],
					filters={
						"guest_session_id": guest_session_id,
						"order_type": "Shopping Cart",
						"docstatus": 0,
						"status": "Draft"
					},
					order_by="modified desc",
					limit=1
				)
				if quotation:
					doc = frappe.get_doc("Quotation", quotation[0].name)
				else:
					# If no quotation found, create a new one
					from webshop.webshop.shopping_cart.guest_cart import create_guest_quotation
					result = create_guest_quotation()
					if result and result.get("success"):
						doc = frappe.get_doc("Quotation", result.get("quotation_id"))
					else:
						return {
							"doc": None,
							"shipping_addresses": [],
							"billing_addresses": [],
							"shipping_rules": [],
							"cart_settings": frappe.get_cached_doc("Webshop Settings")
						}
			else:
				# If no guest_session_id, create a new quotation
				from webshop.webshop.shopping_cart.guest_cart import create_guest_quotation
				result = create_guest_quotation()
				if result and result.get("success"):
					doc = frappe.get_doc("Quotation", result.get("quotation_id"))
				else:
					return {
						"doc": None,
						"shipping_addresses": [],
						"billing_addresses": [],
						"shipping_rules": [],
						"cart_settings": frappe.get_cached_doc("Webshop Settings")
					}
		else:
			# For logged in users, normal behavior
			quotation = _get_cart_quotation(party)
			doc = quotation
		
		if doc:
			set_cart_count(doc)

	addresses = get_address_docs(party=party)
	if doc and not doc.customer_address and addresses:
		update_cart_address("billing", addresses[0].name)

	if doc:		
		# Get loyalty points information
		available_loyalty_points = 0
		loyalty_points_value = 0
		loyalty_program_details = None

		if doc.customer_name and frappe.session.user != "Guest":
			customer_loyalty_program = frappe.db.get_value(
				"Customer", doc.customer_name, "loyalty_program"
			)

			if customer_loyalty_program:
				loyalty_program_details = get_loyalty_program_details_with_points(
					doc.customer_name, customer_loyalty_program
				)

				available_loyalty_points = float(loyalty_program_details.get("loyalty_points", 0))
				loyalty_points_value = frappe.utils.fmt_money(loyalty_program_details.get("loyalty_points", 0) * loyalty_program_details.get("conversion_factor", 0), currency=doc.currency)

	return {
		"doc": decorate_quotation_doc(doc) if doc else None,
		"shipping_addresses": get_shipping_addresses(party),
		"billing_addresses": get_billing_addresses(party),
		"shipping_rules": get_applicable_shipping_rules(party, doc),
		"cart_settings": frappe.get_cached_doc("Webshop Settings"),
		"available_loyalty_points": available_loyalty_points,
		"loyalty_points_value": loyalty_points_value,
		"loyalty_program_details": loyalty_program_details
	}


@frappe.whitelist()
def get_shipping_addresses(party=None):
	if not party:
		party = get_party()
	addresses = get_address_docs(party=party)
	return [
		{
			"name": address.name,
			"title": address.address_title,
			"display": address.display,
		}
		for address in addresses
		if address.address_type == "Shipping"
	]


@frappe.whitelist()
def get_billing_addresses(party=None):
	if not party:
		party = get_party()
	addresses = get_address_docs(party=party)
	return [
		{
			"name": address.name,
			"title": address.address_title,
			"display": address.display,
		}
		for address in addresses
		if address.address_type == "Billing"
	]


@frappe.whitelist()
def place_order():
	quotation = _get_cart_quotation()
	cart_settings = frappe.get_cached_doc("Webshop Settings")
	quotation.company = cart_settings.company

	quotation.flags.ignore_permissions = True
	quotation.submit()

	if quotation.quotation_to == "Lead" and quotation.party_name:
		# company used to create customer accounts
		frappe.defaults.set_user_default("company", quotation.company)

	if not (quotation.shipping_address_name or quotation.customer_address):
		frappe.throw(_("Set Shipping Address or Billing Address"))

	sales_order = frappe.get_doc(
		_make_sales_order(
			quotation.name, ignore_permissions=True
		)
	)
	sales_order.payment_schedule = []

	# Check if all items are gift cards
	if quotation.items and len(quotation.items) == 1:
		first_item = quotation.items[0]
		if is_gift_card_item(first_item.item_code):
			sales_order.skip_delivery_note = 1

	if not cint(cart_settings.allow_items_not_in_stock):
		for item in sales_order.get("items"):
			item.warehouse = frappe.db.get_value(
				"Website Item", {"item_code": item.item_code}, "website_warehouse"
			)
			is_stock_item = frappe.db.get_value("Item", item.item_code, "is_stock_item")

			if is_stock_item:
				item_stock = get_web_item_qty_in_stock(
					item.item_code, "website_warehouse"
				)
				if not cint(item_stock.in_stock):
					throw(_("{0} Not in Stock").format(item.item_code))
				if item.qty > item_stock.stock_qty:
					throw(
						_("Only {0} in Stock for item {1}").format(
							item_stock.stock_qty, item.item_code
						)
					)

	sales_order.flags.ignore_permissions = True
	sales_order.insert()
	sales_order.submit()

	if hasattr(frappe.local, "cookie_manager"):
		frappe.local.cookie_manager.delete_cookie("cart_count")

	return sales_order.name


@frappe.whitelist()
def request_for_quotation():
	quotation = _get_cart_quotation()
	quotation.flags.ignore_permissions = True

	if get_shopping_cart_settings().save_quotations_as_draft:
		quotation.save()
	else:
		quotation.submit()

	return quotation.name


@frappe.whitelist(allow_guest=True)
def update_cart(item_code, qty, additional_notes=None, with_items=False, add_qty=False, price_list_rate=None, gift_card_data=None):
	# Convert gift_card_data from JSON if necessary
	if gift_card_data and isinstance(gift_card_data, str):
		try:
			gift_card_data = frappe.parse_json(gift_card_data)
		except Exception as e:
			frappe.log_error(f"Error parsing JSON", e)
			gift_card_data = None
	
	# Convert qty to integer
	try:
		qty = int(qty)
	except (TypeError, ValueError):
		frappe.throw(_("Quantity must be a valid number"))

	if isinstance(add_qty, str):
		add_qty = add_qty.lower() == 'true'
	
	# Convert price_list_rate to float if provided
	if price_list_rate:
		try:
			price_list_rate = flt(price_list_rate)
		except (TypeError, ValueError):
			price_list_rate = None
	
	# Check if it's a gift card
	is_gift_card = is_gift_card_item(item_code)
	
	# Check that price can only be modified for gift cards
	# Only check if price_list_rate is explicitly passed and not None
	if price_list_rate and not is_gift_card:
		frappe.throw(_("Price can only be modified for gift cards"))
	
	# Check if user is a guest and if guest cart is enabled
	if frappe.session.user == "Guest":
		if not frappe.db.get_single_value("Webshop Settings", "enable_guest_cart"):
			frappe.throw(_("Please log in to add items to cart"))
		
		from webshop.webshop.shopping_cart.guest_cart import create_guest_quotation
		
		# Get existing quotation if it exists
		guest_session_id = frappe.request.cookies.get('guest_session_id')
		existing_quotation = None
		if guest_session_id:
			quotation = frappe.db.get_value(
				'Quotation',
				{
					'guest_session_id': guest_session_id,
					'docstatus': 0,
					'status': 'Draft'
				},
				'name'
			)
			existing_quotation = quotation if quotation is not None else None

		if existing_quotation:
			# If quotation exists, get its items
			quotation = frappe.get_doc('Quotation', existing_quotation)
			existing_items = []
			found_item = False
			for item in quotation.items:
				if item.item_code == item_code:
					found_item = True
					new_qty = item.qty + qty if add_qty else qty
					if new_qty > 0:
						item_dict = {
							"item_code": item.item_code,
							"qty": new_qty
						}
						if is_gift_card and price_list_rate:
							item_dict["rate"] = flt(price_list_rate)
							item_dict["price_list_rate"] = flt(price_list_rate)
						elif is_gift_card:
							# If it's a gift card but no new price, keep the old price
							item_dict["rate"] = item.rate
							item_dict["price_list_rate"] = item.price_list_rate
						if gift_card_data:
							item_dict["gift_card_data"] = gift_card_data
						elif is_gift_card and item.gift_card_data:
							# If it's a gift card but no new data, keep the old data
							item_dict["gift_card_data"] = item.gift_card_data
						existing_items.append(item_dict)
				else:
					item_dict = {
						"item_code": item.item_code,
						"qty": item.qty,
					}
					# Keep existing gift card data
					if is_gift_card_item(item.item_code):
						item_dict["rate"] = item.rate
						item_dict["price_list_rate"] = item.price_list_rate
						if item.gift_card_data:
							item_dict["gift_card_data"] = item.gift_card_data
					existing_items.append(item_dict)
					
			if not found_item and qty > 0:
				item_dict = {
					"item_code": item_code,
					"qty": qty
				}
				if is_gift_card and price_list_rate:
					item_dict["rate"] = flt(price_list_rate)
					item_dict["price_list_rate"] = flt(price_list_rate)
				if gift_card_data:
					item_dict["gift_card_data"] = gift_card_data
				existing_items.append(item_dict)
			items = existing_items
		else:
			# Otherwise, create a new quotation with the item
			item_dict = {"item_code": item_code, "qty": qty}
			if is_gift_card and price_list_rate:
				item_dict["rate"] = flt(price_list_rate)
				item_dict["price_list_rate"] = flt(price_list_rate)
			if gift_card_data:
				item_dict["gift_card_data"] = gift_card_data
			items = [item_dict] if qty > 0 else []
		
		result = create_guest_quotation(items)
		if result and result.get("success"):
			quotation = frappe.get_doc("Quotation", result.get("quotation_id"))

			apply_cart_settings(quotation=quotation)
			
			if cint(with_items):
				context = get_cart_quotation(quotation)
				return {
					"items": frappe.render_template(
						"templates/includes/cart/cart_items.html", context
					),
					"total": frappe.render_template(
						"templates/includes/cart/cart_items_total.html", context
					),
					"taxes_and_totals": frappe.render_template(
						"templates/includes/cart/cart_payment_summary.html", context
					),
				}
			return get_cart_quotation(quotation)
		return None

	quotation = _get_cart_quotation()

	empty_card = False
	if qty == 0:
		quotation_items = quotation.get("items", {"item_code": ["!=", item_code]})
		if quotation_items:
			quotation.set("items", quotation_items)
		else:
			empty_card = True

	else:
		warehouse = frappe.get_cached_value(
			"Website Item", {"item_code": item_code}, "website_warehouse"
		)

		quotation_items = quotation.get("items", {"item_code": item_code})
		if not quotation_items:
			item_dict = {
				"doctype": "Quotation Item",
				"item_code": item_code,
				"qty": qty,
				"additional_notes": additional_notes,
				"warehouse": warehouse,
			}
			if is_gift_card and price_list_rate:
				item_dict["price_list_rate"] = flt(price_list_rate)
				item_dict["rate"] = flt(price_list_rate)
				if gift_card_data:
					item_dict["gift_card_data"] = gift_card_data
			quotation.append("items", item_dict)
		else:
			quotation_items[0].warehouse = warehouse
			quotation_items[0].additional_notes = additional_notes
			new_qty = quotation_items[0].qty + qty if add_qty else qty
			if new_qty > 0:
				quotation_items[0].qty = new_qty
				if is_gift_card and price_list_rate:
					quotation_items[0].price_list_rate = flt(price_list_rate)
					quotation_items[0].rate = flt(price_list_rate)
					if gift_card_data:
						quotation_items[0].gift_card_data = gift_card_data
			else:
				quotation.remove(quotation_items[0])
	
	apply_cart_settings(quotation=quotation)

	quotation.flags.ignore_permissions = True
	quotation.payment_schedule = []
	if not empty_card:
		quotation.save(ignore_version=True)
	else:
		quotation.delete()
		quotation = None

	set_cart_count(quotation)

	if cint(with_items):
		context = get_cart_quotation(quotation)
		return {
			"items": frappe.render_template(
				"templates/includes/cart/cart_items.html", context
			),
			"total": frappe.render_template(
				"templates/includes/cart/cart_items_total.html", context
			),
			"taxes_and_totals": frappe.render_template(
				"templates/includes/cart/cart_payment_summary.html", context
			),
		}
	else:
		return {"name": quotation.name}

@frappe.whitelist()
def get_shopping_cart_menu(context=None):
	if not context:
		context = get_cart_quotation()

	return frappe.render_template("templates/includes/cart/cart_dropdown.html", context)

@frappe.whitelist()
def add_new_address(doc):
	doc = frappe.parse_json(doc)
	doc.update({"doctype": "Address"})
	address = frappe.get_doc(doc)
	address.save(ignore_permissions=True)

	return address

@frappe.whitelist(allow_guest=True)
def create_lead_for_item_inquiry(lead, subject, message):
	lead = frappe.parse_json(lead)
	lead_doc = frappe.new_doc("Lead")
	for fieldname in ("lead_name", "company_name", "email_id", "phone"):
		lead_doc.set(fieldname, lead.get(fieldname))

	lead_doc.set("lead_owner", "")

	if not frappe.db.exists("Lead Source", "Product Inquiry"):
		frappe.get_doc(
			{"doctype": "Lead Source", "source_name": "Product Inquiry"}
		).insert(ignore_permissions=True)

	lead_doc.set("source", "Product Inquiry")

	try:
		lead_doc.save(ignore_permissions=True)
	except frappe.exceptions.DuplicateEntryError:
		frappe.clear_messages()
		lead_doc = frappe.get_doc("Lead", {"email_id": lead["email_id"]})

	lead_doc.add_comment(
		"Comment",
		text="""
		<div>
			<h5>{subject}</h5>
			<p>{message}</p>
		</div>
	""".format(
			subject=subject, message=message
		),
	)

	return lead_doc


@frappe.whitelist()
def get_terms_and_conditions(terms_name):
	return frappe.db.get_value("Terms and Conditions", terms_name, "terms")

@frappe.whitelist()
def update_cart_address(address_type, address_name):
	quotation = _get_cart_quotation()
	address_doc = frappe.get_doc("Address", address_name).as_dict()
	address_display = get_address_display(address_doc)
	
	if address_type.lower() == "billing":
		quotation.customer_address = address_name
		quotation.address_display = address_display
		quotation.shipping_address_name = (
			quotation.shipping_address_name or address_name
		)
		address_doc = next(
			(doc for doc in get_billing_addresses() if doc["name"] == address_name),
			None,
		)
	elif address_type.lower() == "shipping":
		quotation.shipping_address_name = address_name
		quotation.shipping_address = address_display
		quotation.customer_address = quotation.customer_address or address_name
		address_doc = next(
			(doc for doc in get_shipping_addresses() if doc["name"] == address_name),
			None,
		)
	apply_cart_settings(quotation=quotation)

	quotation.flags.ignore_permissions = True
	quotation.save()
	
	context = get_cart_quotation(quotation)
	context["address"] = address_doc

	return {
		"taxes": frappe.render_template(
			"templates/includes/order/order_taxes.html", context
		),
		"address": frappe.render_template(
			"templates/includes/cart/address_card.html", context
		),
}

def guess_territory():
	territory = None
	geoip_country = frappe.session.get("session_country")
	if geoip_country:
		territory = frappe.db.get_value("Territory", geoip_country)

	return (
		territory
		or get_root_of("Territory")
	)

def decorate_quotation_doc(doc):
	for d in doc.get("items", []):
		item_code = d.item_code
		fields = ["web_item_name", "thumbnail", "website_image", "description", "route"]

		# Variant Item
		if not frappe.db.exists("Website Item", {"item_code": item_code}):
			variant_data = frappe.db.get_values(
				"Item",
				filters={"item_code": item_code},
				fieldname=["variant_of", "item_name", "image"],
				as_dict=True,
			)[0]
			item_code = variant_data.variant_of
			fields = fields[1:]
			d.web_item_name = variant_data.item_name

			if variant_data.image:  # get image from variant or template web item
				d.thumbnail = variant_data.image
				fields = fields[2:]

		d.update(
			frappe.db.get_value(
				"Website Item", {"item_code": item_code}, fields, as_dict=True
			)
		)

		website_warehouse = frappe.get_cached_value(
			"Website Item", {"item_code": item_code}, "website_warehouse"
		)

		d.warehouse = website_warehouse

	return doc

def _get_cart_quotation(party=None):
	"""Return the open Quotation of type "Shopping Cart" or make a new one"""
	if not party:
		party = get_party()
		if not party:
			# For guests, find the last quotation
			if frappe.session.user == "Guest":
				guest_session_id = frappe.request.cookies.get('guest_session_id')
				if guest_session_id:
					quotation = frappe.get_all(
						"Quotation",
						fields=["name"],
						filters={
							"guest_session_id": guest_session_id,
							"order_type": "Shopping Cart",
							"docstatus": 0,
							"status": "Draft"
						},
						order_by="modified desc",
						limit=1
					)
					if quotation:
						return frappe.get_doc("Quotation", quotation[0].name)

				# If no quotation found, create a new one
				from webshop.webshop.shopping_cart.guest_cart import create_guest_quotation
				result = create_guest_quotation()
				if result and result.get("success"):
					return frappe.get_doc("Quotation", result.get("quotation_id"))
				return None
			return None

	quotation = frappe.get_all(
		"Quotation",
		fields=["name"],
		filters={
			"party_name": party.name,
			"contact_email": frappe.session.user,
			"order_type": "Shopping Cart",
			"docstatus": 0,
		},
		order_by="modified desc",
		limit_page_length=1,
	)

	if quotation:
		qdoc = frappe.get_doc("Quotation", quotation[0].name)
	else:
		company = frappe.db.get_single_value("Webshop Settings", "company")
		qdoc = frappe.get_doc(
			{
				"doctype": "Quotation",
				"naming_series": get_shopping_cart_settings().quotation_series
				or "QTN-CART-",
				"quotation_to": party.doctype,
				"company": company,
				"order_type": "Shopping Cart",
				"status": "Draft",
				"docstatus": 0,
				"__islocal": 1,
				"party_name": party.name,
			}
		)

		qdoc.contact_person = frappe.db.get_value(
			"Contact", {"email_id": frappe.session.user}
		)
		qdoc.contact_email = frappe.session.user

		qdoc.flags.ignore_permissions = True
		qdoc.run_method("set_missing_values")
		apply_cart_settings(party, qdoc)

	return qdoc

@frappe.whitelist()
def update_party(fullname, company_name=None, mobile_no=None, phone=None):
	party = get_party()

	party.customer_name = company_name or fullname
	party.customer_type = "Company" if company_name else "Individual"

	contact_name = frappe.db.get_value("Contact", {"email_id": frappe.session.user})
	contact = frappe.get_doc("Contact", contact_name)
	contact.first_name = fullname
	contact.last_name = None
	contact.customer_name = party.customer_name
	contact.mobile_no = mobile_no
	contact.phone = phone
	contact.flags.ignore_permissions = True
	contact.save()

	party_doc = frappe.get_doc(party.as_dict())
	party_doc.flags.ignore_permissions = True
	party_doc.save()

	qdoc = _get_cart_quotation(party)
	if not qdoc.get("__islocal"):
		qdoc.customer_name = company_name or fullname
		qdoc.run_method("set_missing_lead_customer_details")
		qdoc.flags.ignore_permissions = True
		qdoc.save()

def apply_cart_settings(party=None, quotation=None):
	if not party:
		party = get_party()
	if not quotation:
		quotation = _get_cart_quotation(party)

	cart_settings = frappe.get_cached_doc("Webshop Settings")

	set_price_list_and_rate(quotation, cart_settings)

	quotation.run_method("calculate_taxes_and_totals")

	set_taxes(quotation, cart_settings)
	
	apply_loyalty_points_tax(quotation)

	# Set terms and conditions from Webshop Settings if it's a new quotation
	if cart_settings.quotation_terms:
		quotation_terms = cart_settings.quotation_terms
		quotation.tc_name = quotation_terms
		quotation.terms = frappe.db.get_value("Terms and Conditions", quotation_terms, "terms")

	_apply_shipping_rule(party, quotation, cart_settings)

def set_price_list_and_rate(quotation, cart_settings):
	"""set price list based on billing territory"""

	_set_price_list(cart_settings, quotation)

	# Reset values
	quotation.price_list_currency = (
		quotation.currency
	) = quotation.plc_conversion_rate = quotation.conversion_rate = None
	for item in quotation.get("items"):
		is_gift_card = is_gift_card_item(item.item_code)
		# Skip price update for gift cards
		if is_gift_card:
			if item.gift_card_data:
				# Convert gift_card_data from JSON if necessary
				if isinstance(item.gift_card_data, str):
					try:
						item.gift_card_data = frappe.parse_json(item.gift_card_data)
					except Exception as e:
						frappe.log_error(f"Error parsing JSON:", e)
						continue
				# Restore prices from gift_card_data
				if isinstance(item.gift_card_data, dict):
					item.price_list_rate = item.gift_card_data.get("price_list_rate")
					item.rate = item.gift_card_data.get("rate")
			continue

		item.price_list_rate = item.discount_percentage = item.rate = item.amount = None

	# Refetch values
	quotation.run_method("set_price_list_and_item_details")

	if hasattr(frappe.local, "cookie_manager"):
		# Set it in cookies for using in product page
		frappe.local.cookie_manager.set_cookie(
			"selling_price_list", quotation.selling_price_list
		)

def _set_price_list(cart_settings, quotation=None):
	"""Set price list based on customer or shopping cart default"""
	from erpnext.accounts.party import get_default_price_list

	party_name = quotation.get("party_name") if quotation else get_party().get("name")
	selling_price_list = None

	# Check if default customer price list exists
	if party_name and frappe.db.exists("Customer", party_name):
		selling_price_list = get_default_price_list(
			frappe.get_doc("Customer", party_name)
		)

	# Check default price list in shopping cart
	if not selling_price_list:
		selling_price_list = cart_settings.price_list

	if quotation:
		quotation.selling_price_list = selling_price_list

	return selling_price_list

def set_taxes(quotation, cart_settings):
	"""set taxes based on billing territory"""
	from erpnext.accounts.party import set_taxes

	customer_group = frappe.db.get_value(
		"Customer", quotation.party_name, "customer_group"
	)

	quotation.taxes_and_charges = set_taxes(
		quotation.party_name,
		"Customer",
		quotation.transaction_date,
		quotation.company,
		customer_group=customer_group,
		supplier_group=None,
		tax_category=quotation.tax_category,
		billing_address=quotation.customer_address,
		shipping_address=quotation.shipping_address_name,
		use_for_shopping_cart=1,
	)
	#
	# 	# clear table
	quotation.set("taxes", [])
	#
	# 	# append taxes
	quotation.append_taxes_from_master()
	quotation.append_taxes_from_item_tax_template()
	
def apply_loyalty_points_tax(quotation):
	"""Add tax line for loyalty points if necessary"""
	if quotation.loyalty_points and quotation.loyalty_amount:
		# Check if loyalty points tax line exists
		has_loyalty_tax = False
		for tax in quotation.taxes:
			if tax.is_loyalty_points_reduction:
				has_loyalty_tax = True
				break
		
		# If tax line does not exist, add it manually
		if not has_loyalty_tax:
			loyalty_program = frappe.db.get_value("Customer", quotation.party_name, "loyalty_program")
			if loyalty_program:
				loyalty_program_doc = frappe.get_doc("Loyalty Program", loyalty_program)
				quotation.append("taxes", {
					"charge_type": "Actual",
					"description": "Loyalty program",
					"account_head": loyalty_program_doc.expense_account,
					"cost_center": loyalty_program_doc.cost_center,
					"tax_amount": -quotation.loyalty_amount,
					"is_loyalty_points_reduction": 1
				})
				
def get_party(user=None):
	"""Return the customer (Customer) for the current user"""
	if not user:
		user = frappe.session.user

	if user == "Guest":
		# Check if guest cart is enabled
		if frappe.db.get_single_value("Webshop Settings", "enable_guest_cart"):
			guest_customer = frappe.db.get_single_value("Webshop Settings", "guest_customer")
			if guest_customer:
				# Create a compatible object with the rest of the code
				return frappe._dict({
					"name": guest_customer,
					"customer_group": frappe.db.get_value("Customer", guest_customer, "customer_group")
				})
		return None

	contact_name = get_contact_name(user)
	party = None

	if contact_name:
		contact = frappe.get_doc("Contact", contact_name)
		if contact.links:
			party_doctype = contact.links[0].link_doctype
			party = contact.links[0].link_name

	cart_settings = frappe.get_cached_doc("Webshop Settings")

	debtors_account = ""

	if cart_settings.enable_checkout:
		debtors_account = get_debtors_account(cart_settings)

	if party:
		doc = frappe.get_doc(party_doctype, party)
		if doc.doctype in ["Customer", "Supplier"]:
			if not frappe.db.exists("Portal User", {"parent": doc.name, "user": user}):
				doc.append("portal_users", {"user": user})
				doc.flags.ignore_permissions = True
				doc.flags.ignore_mandatory = True
				doc.save()

			# Update address ownership if needed
			addresses = frappe.get_all("Dynamic Link", 
				filters={
					"link_doctype": "Customer",
					"link_name": doc.name,
					"parenttype": "Address"
				},
				fields=["parent"]
			)
			
			addresses_updated = []
			for addr in addresses:
				current_owner = frappe.db.get_value('Address', addr.parent, 'owner')
				if current_owner != user:
					frappe.db.sql("""
						UPDATE `tabAddress` 
						SET `owner` = %s, `modified_by` = %s 
						WHERE name = %s
					""", (user, user, addr.parent))
					addresses_updated.append(addr.parent)

			if addresses_updated:
				frappe.db.commit()

		return doc

	else:
		if not cart_settings.enabled:
			frappe.local.flags.redirect_location = "/contact"
			raise frappe.Redirect
		customer = frappe.new_doc("Customer")
		user_doc = frappe.get_doc("User", user)
		fullname = get_fullname(user)
		# If user has no last_name, try to deduce it
		if not user_doc.last_name:
			fullname_parts = fullname.split(' ', 1)  # Split into two parts at the first space
			user_doc.first_name = fullname_parts[0]
			user_doc.last_name = fullname_parts[1] if len(fullname_parts) > 1 else ""
			user_doc.save()
		
		# Create contact with user information
		contact = frappe.new_doc("Contact")
		contact.update({
			"first_name": user_doc.first_name,
			"last_name": user_doc.last_name,
			"full_name": fullname,
			"email_id": user,
			"user": user,
			"is_primary_contact": 1,
			"is_billing_contact": 1,
			"email_ids": [{
				"email_id": user,
				"is_primary": 1
			}]
		})
		
		# Add Customer role directly to the roles table
		if not any(r.role == "Customer" for r in user_doc.roles):
			try:
				user_doc.append('roles', {
					'doctype': 'Has Role',
					'role': 'Customer',
					'parenttype': 'User',
					'parent': user,
					'parentfield': 'roles'
				})
				user_doc.save(ignore_permissions=True)
			except frappe.TimestampMismatchError:
				user_doc.reload()
				if not any(r.role == "Customer" for r in user_doc.roles):
					user_doc.append('roles', {
						'doctype': 'Has Role',
						'role': 'Customer',
						'parenttype': 'User',
						'parent': user,
						'parentfield': 'roles'
					})
					user_doc.save(ignore_permissions=True)
		
		customer.update(
			{
				"customer_name": f"{user_doc.first_name} {user_doc.last_name}".strip(),
				"customer_type": "Individual",
				"customer_group": get_shopping_cart_settings().default_customer_group,
				"territory": get_root_of("Territory"),
			}
		)

		customer.append("portal_users", {"user": user})

		if debtors_account:
			customer.update(
				{
					"accounts": [
						{"company": cart_settings.company, "account": debtors_account}
					]
				}
			)

		customer.flags.ignore_mandatory = True
		customer.insert(ignore_permissions=True)

		contact = frappe.new_doc("Contact")
		contact.update(
			{"first_name": user_doc.first_name, "last_name": user_doc.last_name, "email_ids": [{"email_id": user, "is_primary": 1}]}
		)
		contact.append("links", dict(link_doctype="Customer", link_name=customer.name))
		contact.flags.ignore_mandatory = True
		contact.insert(ignore_permissions=True)

		return customer

def get_debtors_account(cart_settings):
	if not cart_settings.payment_gateway_account:
		frappe.throw(_("Payment Gateway Account not set"), _("Mandatory"))

	payment_gateway_account_currency = frappe.get_doc(
		"Payment Gateway Account", cart_settings.payment_gateway_account
	).currency

	account_name = _("Debtors ({0})").format(payment_gateway_account_currency)

	debtors_account_name = get_account_name(
		"Receivable",
		"Asset",
		is_group=0,
		account_currency=payment_gateway_account_currency,
		company=cart_settings.company,
	)

	if not debtors_account_name:
		debtors_account = frappe.get_doc(
			{
				"doctype": "Account",
				"account_type": "Receivable",
				"root_type": "Asset",
				"is_group": 0,
				"parent_account": get_account_name(
					root_type="Asset", is_group=1, company=cart_settings.company
				),
				"account_name": account_name,
				"currency": payment_gateway_account_currency,
			}
		).insert(ignore_permissions=True)

		return debtors_account.name

	else:
		return debtors_account_name

def get_address_docs(
	doctype=None,
	txt=None,
	filters=None,
	limit_start=0,
	limit_page_length=20,
	party=None,
):
	if not party:
		party = get_party()

	if not party:
		return []

	address_names = frappe.db.get_all(
		"Dynamic Link",
		fields=("parent"),
		filters=dict(
			parenttype="Address", link_doctype=party.doctype, link_name=party.name
		),
	)

	out = []

	for a in address_names:
		address = frappe.get_doc("Address", a.parent)
		address.display = get_address_display(address.as_dict())
		out.append(address)

	return out


@frappe.whitelist()
def apply_shipping_rule(shipping_rule):
	quotation = _get_cart_quotation()
	quotation.shipping_rule = shipping_rule

	apply_cart_settings(quotation=quotation)

	quotation.flags.ignore_permissions = True
	quotation.save()

	return get_cart_quotation(quotation)

def _apply_shipping_rule(party=None, quotation=None, cart_settings=None):
	# Check if all items are gift cards
	all_items_are_gift_cards = True
	for item in quotation.items:
		if not is_gift_card_item(item.item_code):
			all_items_are_gift_cards = False
			break
	
	# If all items are gift cards, remove shipping rule
	if all_items_are_gift_cards:
		quotation.shipping_rule = None
		quotation.run_method("calculate_taxes_and_totals")
		return

	if not quotation.shipping_rule:
		shipping_rules = get_shipping_rules(quotation, cart_settings)

		if not shipping_rules:
			return

		elif quotation.shipping_rule not in shipping_rules:
			quotation.shipping_rule = shipping_rules[0]

	if quotation.shipping_rule:
		quotation.run_method("apply_shipping_rule")
		quotation.run_method("calculate_taxes_and_totals")

def get_applicable_shipping_rules(party=None, quotation=None):
	shipping_rules = get_shipping_rules(quotation)

	if shipping_rules:
		rule_label_map = frappe.db.get_values("Shipping Rule", shipping_rules, "label")
		# we need this in sorted order as per the position of the rule in the settings page
		return [[rule, rule] for rule in shipping_rules]

def get_shipping_rules(quotation=None, cart_settings=None):
	if not quotation:
		quotation = _get_cart_quotation()

	shipping_rules = []
	if quotation.shipping_address_name:
		country = frappe.db.get_value(
			"Address", quotation.shipping_address_name, "country"
		)
		if country:
			sr_country = frappe.qb.DocType("Shipping Rule Country")
			sr = frappe.qb.DocType("Shipping Rule")
			query = (
				frappe.qb.from_(sr_country)
				.join(sr)
				.on(sr.name == sr_country.parent)
				.select(sr.name)
				.distinct()
				.where((sr_country.country == country) & (sr.disabled != 1))
			)
			result = query.run(as_list=True)
			shipping_rules = [x[0] for x in result]

	return shipping_rules

def get_address_territory(address_name):
	"""Tries to match city, state and country of address to existing territory"""
	territory = None

	if address_name:
		address_fields = frappe.db.get_value(
			"Address", address_name, ["city", "state", "country"]
		)
		for value in address_fields:
			territory = frappe.db.get_value("Territory", value)
			if territory:
				break

	return territory

def show_terms(doc):
	return doc.tc_name

@frappe.whitelist(allow_guest=True)
def get_customer_info():
	"""Get customer information including customer type and name from the current quotation"""
	try:
		quotation = get_cart_quotation().get('doc')
		if not quotation or not quotation.party_name:
			return None
			
		customer_doc = frappe.get_doc("Customer", quotation.party_name)
		return {
			"customer_type": customer_doc.customer_type,
			"customer_name": customer_doc.customer_name
		}
	except Exception as e:
		frappe.log_error(f"Error in get_customer_info", e)
		return None


@frappe.whitelist()
def update_customer_info(customer_name=None, customer_type=None):
	"""Update customer information and related addresses"""
	try:
		quotation = get_cart_quotation().get('doc')
		if not quotation or not quotation.party_name:
			return {"success": False, "message": "No quotation or customer found"}
			
		customer_doc = frappe.get_doc("Customer", quotation.party_name)
		
		# Update customer fields if provided
		if customer_name:
			customer_doc.customer_name = customer_name
		if customer_type:
			customer_doc.customer_type = customer_type
			
		customer_doc.save(ignore_permissions=True)
		
		# Update address titles if customer name changed
		if customer_name:
			# Import the correct rename_doc function
			from frappe.model.rename_doc import rename_doc
			
			# Rename customer document
			if quotation.party_name != customer_name:
				rename_doc("Customer", quotation.party_name, customer_name, force=True, ignore_permissions=True)
				
				# Update addresses
				addresses = [quotation.customer_address, quotation.shipping_address_name]
				for address_name in addresses:
					if address_name:
						address = frappe.get_doc("Address", address_name)
						address.address_title = f"{customer_name} - {address.address_type}"
						address.save(ignore_permissions=True)
		
		frappe.db.commit()
		return {
			"success": True,
			"message": "Customer information updated successfully"
		}
	except Exception as e:
		frappe.db.rollback()
		frappe.log_error(f"Error in update_customer_info", e)
		return {
			"success": False,
			"message": str(e)
		}

@frappe.whitelist()
def update_contact_info(first_name, last_name, email=None, phone=None, company_name=None):
	"""Update contact information from checkout page"""
	if not frappe.session.user:
		return {
			"success": False,
			"message": "User not logged in"
		}

	try:
		# Get current quotation
		quotation = get_cart_quotation().get('doc')
		if not quotation:
			return {
				"success": False,
				"message": "No active quotation found"
			}

		# Get or create contact
		contact_name = get_contact_name(frappe.session.user)
		if contact_name:
			contact = frappe.get_doc("Contact", contact_name)
		else:
			contact = frappe.new_doc("Contact")
			contact.append("links", {
				"link_doctype": "Customer",
				"link_name": quotation.party_name
			})

		# Update contact information
		contact.first_name = first_name
		contact.last_name = last_name
		contact.full_name = f"{first_name} {last_name}"
		contact.is_primary_contact = 1  # Set as primary contact
		contact.is_billing_contact = 1  # Set as billing contact
		
		# Update company name if provided
		if company_name:
			contact.company_name = company_name
		
		# Update or add email
		if email:
			if not contact.email_ids:
				contact.append("email_ids", {
					"email_id": email,
					"is_primary": 1
				})
			else:
				contact.email_ids[0].email_id = email
		
		# Update or add phone
		if phone:
			contact.phone = phone  # Set the main phone field
			if not contact.phone_nos:
				contact.append("phone_nos", {
					"phone": phone,
					"is_primary_phone": 1
				})
			else:
				contact.phone_nos[0].phone = phone

		# Set billing address
		if quotation.customer_address:
			contact.address = quotation.customer_address

		contact.flags.ignore_mandatory = True
		contact.save(ignore_permissions=True)

		# Update quotation's contact_person
		quotation.contact_person = contact.name
		quotation.save(ignore_permissions=True)

		return {
			"success": True,
			"message": "Contact information updated successfully"
		}

	except Exception as e:
		return {
			"success": False,
			"message": str(e)
		}

@frappe.whitelist(allow_guest=True)
def apply_coupon_code(applied_code, applied_referral_sales_partner):
	quotation = True

	if not applied_code:
		frappe.throw(_("Please enter a coupon code"))

	coupon_list = frappe.get_all("Coupon Code", filters={"coupon_code": applied_code})
	if not coupon_list:
		frappe.throw(_("Please enter a valid coupon code"))

	coupon_name = coupon_list[0].name

	from erpnext.accounts.doctype.pricing_rule.utils import validate_coupon_code

	validate_coupon_code(coupon_name)
	quotation = _get_cart_quotation()
	
	# Save coupon and recalculate totals
	quotation.coupon_code = coupon_name
	quotation.flags.ignore_permissions = True
	quotation.save()
	
	# Check that discount does not exceed total amount
	if quotation.discount_amount > quotation.rounded_total:
		# Remove coupon if discount is too high
		quotation.coupon_code = ""
		quotation.flags.ignore_permissions = True
		quotation.save()
		frappe.throw(_("Discount value cannot exceed total amount"))

	if applied_referral_sales_partner:
		sales_partner_list = frappe.get_all(
			"Sales Partner", filters={"referral_code": applied_referral_sales_partner}
		)
		if sales_partner_list:
			sales_partner_name = sales_partner_list[0].name
			quotation.referral_sales_partner = sales_partner_name
			quotation.flags.ignore_permissions = True
			quotation.save()

	return quotation

@frappe.whitelist(allow_guest=True)
def remove_coupon_code():
	quotation = _get_cart_quotation()
	quotation.coupon_code = ""
	quotation.flags.ignore_permissions = True
	quotation.save()
	return True
	
@frappe.whitelist(allow_guest=True)
def get_coupon_html():
	quotation = _get_cart_quotation()
	cart_settings = frappe.get_cached_doc("Webshop Settings")
	context = {
		"doc": quotation,
		"cart_settings": cart_settings,
		"show_coupon_code": 1
	}
	return frappe.render_template("templates/includes/coupon_form.html", context)

@frappe.whitelist(allow_guest=True)
def get_loyalty_points_html():
	quotation = _get_cart_quotation()
	cart_settings = frappe.get_cached_doc("Webshop Settings")
	
	# Check if user is logged in and get loyalty points
	customer_info = get_party()
	customer = customer_info.name if customer_info else None
	
	# Get available loyalty points
	loyalty_points_details = {}
	if customer:
		try:
			# Get customer's loyalty program first
			loyalty_program = frappe.db.get_value("Customer", customer, "loyalty_program")
			if loyalty_program:
				loyalty_points_details = get_loyalty_program_details_with_points(
					customer,
					loyalty_program,
					company=quotation.company,
					silent=True
				)
		except Exception as e:
			frappe.log_error(f"Error getting loyalty points", e)
			loyalty_points_details = frappe._dict({"loyalty_points": 0})
	else:
		loyalty_points_details = frappe._dict({"loyalty_points": 0})

	
	context = {
		"doc": quotation,
		"cart_settings": cart_settings,
		"available_loyalty_points": loyalty_points_details.get("loyalty_points", 0),
		"conversion_factor": loyalty_points_details.get("conversion_factor", 0),
		"loyalty_points_value": frappe.utils.fmt_money(loyalty_points_details.get("loyalty_points", 0) * loyalty_points_details.get("conversion_factor", 0), currency=quotation.currency),
	}
	
	return frappe.render_template("templates/includes/loyalty_points_form.html", context)

@frappe.whitelist(allow_guest=True)
def apply_loyalty_points(points):
	quotation = _get_cart_quotation()
	points = float(points)
	
	# Get customer
	customer_info = get_party()
	customer = customer_info.name if customer_info else None
	if not customer:
		frappe.throw(_("Please log in to use your loyalty points"))
	
	# Get customer's loyalty program
	loyalty_program = frappe.db.get_value("Customer", customer, "loyalty_program")
	if not loyalty_program:
		frappe.throw(_("You do not have an active loyalty program"))
	
	# Check if customer has enough points
	loyalty_points_details = get_loyalty_program_details_with_points(
		customer,
		loyalty_program,
		company=quotation.company,
		silent=True
	)
	
	available_points = loyalty_points_details.get("loyalty_points", 0)
	if points > available_points:
		frappe.throw(_("You do not have enough loyalty points ({0} points available)").format(available_points))
	
	# Calculate discount amount
	float_precision = cint(frappe.db.get_default("float_precision")) or 2
	conversion_factor = loyalty_points_details.get("conversion_factor", 0)
	loyalty_amount = flt(points * conversion_factor, float_precision)

	# Limit loyalty_amount to 2 decimal places
	if loyalty_amount > quotation.rounded_total:
		frappe.throw(_("Loyalty points value cannot exceed total amount"))
	
	# Get loyalty program details
	loyalty_program_doc = frappe.get_doc("Loyalty Program", loyalty_program)
	
	# Apply points and discount
	quotation.loyalty_points = points
	quotation.loyalty_amount = loyalty_amount
	quotation.loyalty_program = loyalty_program
	
	# Add or update loyalty points tax line
	existing_loyalty_charge = None
	for tax in quotation.taxes:
		if tax.is_loyalty_points_reduction:
			existing_loyalty_charge = tax
			break
	
	if existing_loyalty_charge:
		existing_loyalty_charge.tax_amount = -loyalty_amount
	else:
		quotation.append("taxes", {
			"charge_type": "Actual",
			"description": "Loyalty program",
			"account_head": loyalty_program_doc.expense_account,
			"cost_center": loyalty_program_doc.cost_center,
			"tax_amount": -loyalty_amount,
			"is_loyalty_points_reduction": 1
		})
	
	# Create loyalty point entry
	loyalty_point_entry = frappe.get_doc({
		"doctype": "Loyalty Point Entry",
		"loyalty_program": loyalty_program,
		"loyalty_program_tier": frappe.db.get_value("Customer", customer, "loyalty_program_tier"),
		"customer": customer,
		"invoice_type": "Quotation",
		"invoice": quotation.name,
		"loyalty_points": -points,  # Negative because it's a points usage
		"purchase_amount": quotation.grand_total,
		"expiry_date": frappe.utils.today(),
		"posting_date": frappe.utils.today(),
		"company": quotation.company
	})
	loyalty_point_entry.insert(ignore_permissions=True)
	
	# Save loyalty point entry ID in quotation for later deletion
	quotation.loyalty_point_entry = loyalty_point_entry.name
	
	# Recalculate taxes and totals
	quotation.calculate_taxes_and_totals()
	
	quotation.flags.ignore_permissions = True
	quotation.save()
	
	return True

@frappe.whitelist(allow_guest=True)
def remove_loyalty_points():
	quotation = _get_cart_quotation()
	
	# Delete loyalty point entry if it exists
	if quotation.loyalty_point_entry:
		frappe.db.sql("""DELETE FROM `tabLoyalty Point Entry` WHERE name = %s""", quotation.loyalty_point_entry)
		frappe.db.commit()
		quotation.loyalty_point_entry = None
	
	# Reset loyalty points and discount
	quotation.loyalty_points = 0
	quotation.loyalty_amount = 0
	quotation.loyalty_program = None
	
	# Remove loyalty points tax line
	taxes_to_keep = []
	for tax in quotation.taxes:
		if not tax.is_loyalty_points_reduction:
			taxes_to_keep.append(tax)
	quotation.taxes = taxes_to_keep
	
	quotation.flags.ignore_permissions = True
	quotation.save()
	
	return True

@frappe.whitelist(allow_guest=True)
def is_gift_card_item(item_code):
	"""Check if an item is a gift card"""
	website_item = frappe.get_cached_doc("Website Item", {"item_code": item_code})
	return website_item.is_gift_card if website_item else False

def remove_quotation_loyalty_points(doc, method=None):
	"""Remove loyalty points related to a specific quotation"""
	
	if isinstance(doc, str):
		quotation_name = doc
	else:
		quotation_name = doc.name

	# Check if quotation exists
	if not frappe.db.exists("Quotation", quotation_name):
		return False

	# Find loyalty point entries related to this quotation
	loyalty_entries = frappe.get_all(
		"Loyalty Point Entry",
		filters={
			"invoice_type": "Quotation",
			"invoice": quotation_name
		},
		fields=["name"]
	)

	if loyalty_entries:
		# First, update entries to remove link to quotation
		for entry in loyalty_entries:
			frappe.db.sql(
				"""DELETE FROM `tabLoyalty Point Entry` WHERE name = %s""",
				entry.name
			)
		frappe.db.commit()
		
		return True
	
	return False

def create_gift_cards_from_invoice(doc, method=None):
	"""Create gift cards for gift card items in a paid invoice"""
	try:
		sales_invoice = doc
		if not sales_invoice.docstatus == 1 or sales_invoice.outstanding_amount > 0:
			return

		# Check validity settings in Webshop Settings
		settings = frappe.get_single("Webshop Settings")
		validity_months = cint(settings.get("number_of_valid_months", 0))
		valid_from = frappe.utils.today()
		valid_upto = frappe.utils.add_months(valid_from, validity_months) if validity_months > 0 else None

		# Get customer's email
		customer = frappe.get_doc("Customer", sales_invoice.customer)
		owner_email = None
		if customer.portal_users:
			owner_email = customer.portal_users[0].user

		for item in sales_invoice.items:
			if not is_gift_card_item(item.item_code):
				continue

			# Find or create a Pricing Rule
			pricing_rule_filters = {
				"apply_on": "Transaction",
				"price_or_product_discount": "Price",
				"selling": 1,
				"buying": 0,
				"coupon_code_based": 1,
				"disable": 0,
				"margin_type": "Amount",
				"rate_or_discount": "Discount Amount",
				"discount_amount": item.rate
			}
						
			pricing_rule = frappe.db.exists("Pricing Rule", pricing_rule_filters)
			pricing_rule_name = pricing_rule if pricing_rule else None
			
			if not pricing_rule:
				try:
					pricing_rule = frappe.get_doc({
						"doctype": "Pricing Rule",
						"title": f"Gift card {item.rate:.2f}",
						**pricing_rule_filters
					})

					pricing_rule.ignore_permissions = True
					pricing_rule.insert(ignore_permissions=True)
					pricing_rule_name = pricing_rule.name
					
				except Exception as e:
					frappe.log_error("Gift Card - Error Pricing Rule",f"Error creating Pricing Rule: {str(e)}\nData: {pricing_rule.as_dict()}")
					raise

			# Create a gift card for each quantity
			for i in range(cint(item.qty)):
				try:
					# Get coupon_code in gift_card_data field 
					gift_card_data = json.loads(item.gift_card_data) if item.gift_card_data else None
					coupon_code = gift_card_data.get("code") if gift_card_data else None
					
					gift_card = frappe.get_doc({
						"doctype": "Coupon Code",
						"coupon_name": coupon_code,
						"coupon_type": "Gift Card",
						"coupon_code": coupon_code,
						"pricing_rule": pricing_rule_name,
						"valid_from": valid_from,
						"valid_upto": valid_upto,
						"maximum_use": 9999,
						"used": 0,
						"customer": sales_invoice.customer,
						"sales_invoice": sales_invoice.name
					})
					
					if owner_email:
						gift_card.owner = owner_email
					
					gift_card.ignore_permissions = True
					gift_card.insert(ignore_permissions=True)
					gift_card.save( ignore_permissions=True )
					
					# Send an email to the customer with the gift card code
					# frappe.sendmail(
					# 	recipients=[owner_email] if owner_email else [sales_invoice.contact_email],
					# 	subject=f"Your gift card of {item.rate:.2f}",
					# 	message=f"""Hello,
					# 		Here is your gift card of {item.rate:.2f}.
					# 		Code: {coupon_code}
					# 		Valid from {valid_from} to {valid_upto if valid_upto else 'no limit'}.
					# 
					# 		Best regards,
					# 		The team""",
					# 	delayed=False
					# )
				except Exception as e:
					frappe.log_error("Gift Card - Error creation",f"Error creating Gift Card: {str(e)}\nData: {gift_card.as_dict() if 'gift_card' in locals() else 'Not created'}")
					raise

	except Exception as e:
		frappe.log_error("Gift Card - General error",f"General error creating Gift Card: {str(e)}")
		raise
