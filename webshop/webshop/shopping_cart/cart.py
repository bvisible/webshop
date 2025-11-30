# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt
from locale import currency
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
from webshop.webshop.utils.utils import format_currency_value
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
				import math
				
				loyalty_program_details = get_loyalty_program_details_with_points(
					doc.customer_name, customer_loyalty_program
				)

				# Get raw loyalty points
				raw_loyalty_points = float(loyalty_program_details.get("loyalty_points", 0))
				conversion_factor = loyalty_program_details.get("conversion_factor", 0)
				
				# Round down loyalty points to the nearest 10
				rounded_loyalty_points = math.floor(raw_loyalty_points / 10) * 10
				
				# Update the loyalty program details with rounded points
				loyalty_program_details["loyalty_points"] = rounded_loyalty_points
				
				# Set the available loyalty points to the rounded value
				available_loyalty_points = rounded_loyalty_points
				
				# Calculate loyalty points value based on rounded points
				equivalent_value = rounded_loyalty_points * conversion_factor
				from webshop.webshop.utils.utils import format_currency_value
				loyalty_points_value = format_currency_value(equivalent_value, currency=doc.currency)

	# Get customer information for B2B verification
	customer_info = None
	is_b2b_customer = False
	if doc and doc.customer_name and frappe.session.user != "Guest":
		customer_info = frappe.db.get_value("Customer", doc.customer_name, ["name", "customer_group"], as_dict=1)
		
		# Check if the customer belongs to a B2B group
		cart_settings = frappe.get_cached_doc("Webshop Settings")
		if cart_settings.activate_b2b_checkout and customer_info and cart_settings.b2b_customer_group:
			for group in cart_settings.b2b_customer_group:
				if group.customer_group == customer_info.customer_group:
					is_b2b_customer = True
					break

	# Get loyalty points to earn information
	loyalty_info = {}
	show_loyalty = False
	show_loyalty_for_guests = False
	
	try:
		settings = frappe.get_cached_doc("Webshop Settings")
		show_loyalty = settings.enable_loyalty_points
		show_loyalty_for_guests = settings.show_loyalty_points_for_guests if settings.enable_loyalty_points else False
		
		if settings.enable_loyalty_points and doc:
			from webshop.webshop.utils.loyalty_cart import get_loyalty_points_for_cart
			loyalty_data = get_loyalty_points_for_cart(doc)
			if loyalty_data:
				loyalty_info = loyalty_data
	except Exception as e:
		frappe.log_error("Loyalty Points Error in get_cart_quotation", str(e))

	return {
		"doc": decorate_quotation_doc(doc) if doc else None,
		"shipping_addresses": get_shipping_addresses(party),
		"billing_addresses": get_billing_addresses(party),
		"shipping_rules": get_applicable_shipping_rules(party, doc),
		"cart_settings": frappe.get_cached_doc("Webshop Settings"),
		"available_loyalty_points": available_loyalty_points,
		"loyalty_points_value": loyalty_points_value,
		"loyalty_program_details": loyalty_program_details,
		"customer_info": customer_info,
		"is_b2b_customer": is_b2b_customer,
		"loyalty_info": loyalty_info,
		"show_loyalty": show_loyalty,
		"show_loyalty_for_guests": show_loyalty_for_guests
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
	
	# Save the coupon info for later use
	coupon_data = None
	gift_card_to_split = False
	
	# Check if we have a stored coupon in temp_coupon_code
	if hasattr(quotation, "temp_coupon_code") and quotation.temp_coupon_code:
		coupon_data = {
			"coupon_code": quotation.temp_coupon_code
		}
		
	# Check if this is a gift card that might need to be split
	if hasattr(quotation, "gift_card_coupon") and quotation.gift_card_coupon and \
	   hasattr(quotation, "gift_card_original_amount") and quotation.gift_card_original_amount:
	
		gift_card_amount = flt(quotation.gift_card_original_amount)
		order_total = flt(quotation.grand_total)
		
		# Double-check that discount is applied correctly
		if flt(quotation.discount_amount) == 0 and order_total > 0:
			# Apply discount if not already applied
			if gift_card_amount >= order_total:
				# Limit discount to order total
				quotation.apply_discount_on = "Grand Total"
				quotation.discount_amount = order_total
				quotation.gift_card_to_split = 1  # Mark for split
				quotation.flags.ignore_permissions = True
				quotation.save()
			else:
				# Apply full gift card amount
				quotation.apply_discount_on = "Grand Total"
				quotation.discount_amount = gift_card_amount
				quotation.gift_card_to_split = 0
				quotation.flags.ignore_permissions = True
				quotation.save()
		
		# Get latest values after possible updates
		gift_card_amount = flt(quotation.gift_card_original_amount)
		used_amount = flt(quotation.discount_amount)
		excess_amount = gift_card_amount - used_amount
		
		# Check if we need to split
		if excess_amount > 0:
			gift_card_to_split = True
			
		# Store gift card data for processing after sales order creation
		if not coupon_data:
			coupon_data = {}
			
		coupon_data.update({
			"is_gift_card": True,
			"gift_card_coupon": quotation.gift_card_coupon,
			"gift_card_amount": gift_card_amount,
			"used_amount": used_amount,
			"excess_amount": excess_amount
		})

	quotation.flags.ignore_permissions = True
	quotation.submit()

	if quotation.quotation_to == "Lead" and quotation.party_name:
		# company used to create customer accounts
		frappe.defaults.set_user_default("company", quotation.company)

	if not (quotation.shipping_address_name or quotation.customer_address):
		frappe.throw(_("Set Shipping Address or Billing Address"))

	# Submit quotation if it's still in draft state
	if quotation.docstatus == 0:
		quotation.flags.ignore_permissions = True
		quotation.submit()

	sales_order = frappe.get_doc(
		_make_sales_order(
			quotation.name, ignore_permissions=True
		)
	)
	sales_order.payment_schedule = []
	
	# For gift cards that need to be split, process the split BEFORE creating the sales order
	if coupon_data and coupon_data.get("is_gift_card") and coupon_data.get("gift_card_coupon"):
		# We need to create a new gift card for the used amount before inserting the sales order
		gift_card_amount = flt(coupon_data.get("gift_card_amount"))
		used_amount = flt(quotation.discount_amount)
		excess_amount = 0
		
		# Check if we have an excess amount that needs to be split
		if gift_card_amount > used_amount and used_amount > 0:
			excess_amount = gift_card_amount - used_amount
			gift_card_to_split = True
			
			original_coupon = coupon_data.get("gift_card_coupon")
			
			# Get the original gift card
			original_card = frappe.get_doc("Coupon Code", original_coupon)

			if original_card and original_card.coupon_type == "Gift Card":
				# Create a new gift card for the used amount
				import string
				import random
				
				# Generate a unique code for the new gift card
				def generate_unique_code():
					chars = string.ascii_uppercase + string.digits
					code_parts = [''.join(random.choice(chars) for _ in range(4)) for _ in range(3)]
					new_code = '-'.join(code_parts)
					
					while frappe.db.exists("Coupon Code", {"coupon_code": new_code}):
						code_parts = [''.join(random.choice(chars) for _ in range(4)) for _ in range(3)]
						new_code = '-'.join(code_parts)
						
					return new_code
				
				new_code = generate_unique_code()
				
				# Create a pricing rule for the used amount
				pricing_rule_filters = {
					"apply_on": "Transaction",
					"price_or_product_discount": "Price",
					"is_cumulative": 1,
					"valid_upto": "2999-12-31",
					"selling": 1,
					"buying": 0,
					"coupon_code_based": 1,
					"disable": 0,
					"margin_type": "Amount",
					"rate_or_discount": "Discount Amount",
					"discount_amount": used_amount
				}
				
				pricing_rule = frappe.db.exists("Pricing Rule", pricing_rule_filters)
				
				if not pricing_rule:
					pricing_rule = frappe.get_doc({
						"doctype": "Pricing Rule",
						"title": f"{_('Gift Card')} {format_currency_value(used_amount, currency=frappe.db.get_default('currency'))}",
						**pricing_rule_filters
					})
					
					pricing_rule.insert(ignore_permissions=True)
					pricing_rule_name = pricing_rule.name
				else:
					pricing_rule_name = pricing_rule
				
				# Create the new gift card with the used amount
				new_card_name = f"{_('Gift Card')} {format_currency_value(used_amount, currency=frappe.db.get_default('currency'))} - {original_card.customer or _('Customer')} - {new_code}"
				
				# Create the new gift card
				new_gift_card = frappe.get_doc({
					"doctype": "Coupon Code",
					"coupon_name": new_card_name,
					"coupon_type": "Gift Card",
					"coupon_code": new_code,
					"pricing_rule": pricing_rule_name,
					"valid_from": original_card.valid_from,
					"valid_upto": original_card.valid_upto,
					"maximum_use": 1,
					"used": 0,
					"customer": original_card.customer,
					"gift_card_amount": used_amount,
					"coupon_code_residual": original_card.name,
					"description": f"{_('Created from gift card')}: {original_card.name} ({_('amount used in order from quotation')} {quotation.name})"
				})
				
				# If the customer has a portal user, set as owner
				if original_card.customer:
					try:
						customer = frappe.get_doc("Customer", original_card.customer)
						if hasattr(customer, "portal_users") and customer.portal_users:
							user = customer.portal_users[0].user
							new_gift_card.owner = user
					except Exception as e:
						frappe.log_error( "Gift Card Split Error", f"Error getting customer portal user: {str(e)}")
				
				# Save the new gift card
				try:
					new_gift_card.insert(ignore_permissions=True)
					new_gift_card.save(ignore_permissions=True)
					
					# Update the original card with the remaining amount
					excess_pricing_rule_filters = {
						"apply_on": "Transaction",
						"price_or_product_discount": "Price",
						"is_cumulative": 1,
						"valid_upto": "2999-12-31",
						"selling": 1,
						"buying": 0,
						"coupon_code_based": 1,
						"disable": 0,
						"margin_type": "Amount",
						"rate_or_discount": "Discount Amount",
						"discount_amount": excess_amount
					}
					
					excess_pricing_rule = frappe.db.exists("Pricing Rule", excess_pricing_rule_filters)
					
					if not excess_pricing_rule:
						excess_pricing_rule = frappe.get_doc({
							"doctype": "Pricing Rule",
							"title": f"{_('Gift Card')} {excess_amount:.2f}",
							**excess_pricing_rule_filters
						})
						
						excess_pricing_rule.insert(ignore_permissions=True)
						excess_pricing_rule_name = excess_pricing_rule.name
					else:
						excess_pricing_rule_name = excess_pricing_rule
					
					# Update the original card
					original_card.gift_card_amount = excess_amount
					original_card.pricing_rule = excess_pricing_rule_name
					
					if original_card.description:
						original_card.description += f"\n\n{_('Amount adjusted on')} {frappe.utils.today()}: {format_currency_value(gift_card_amount, currency=frappe.db.get_default('currency'))} → {format_currency_value(excess_amount, currency=frappe.db.get_default('currency'))}. {_('Amount used')} ({format_currency_value(used_amount, currency=frappe.db.get_default('currency'))}) {_('transferred to card')} {new_code} {_('for order from quotation')} {quotation.name}."
					else:
						original_card.description = f"{_('Amount adjusted on')} {frappe.utils.today()}: {format_currency_value(gift_card_amount, currency=frappe.db.get_default('currency'))} → {format_currency_value(excess_amount, currency=frappe.db.get_default('currency'))}. {_('Amount used')} ({format_currency_value(used_amount, currency=frappe.db.get_default('currency'))}) {_('transferred to card')} {new_code} {_('for order from quotation')} {quotation.name}."
					
					original_card.save(ignore_permissions=True)
					
					# Remember the previous value
					old_value = coupon_data.get("gift_card_coupon")
					
					# Update the coupon data to use the new gift card for the sales order
					coupon_data["gift_card_coupon"] = new_gift_card.name

				except Exception as e:
					frappe.log_error(
						"Gift Card Split Error",
						f"Gift card split FAILED: "
						f"Original card {original_coupon}, "
						f"Used amount {used_amount}, "
						f"Excess amount {excess_amount}. "
						f"Error: {str(e)}"
					)
	
	if coupon_data:
		if "coupon_code" in coupon_data:
			# Set coupon code in the sales order
			sales_order.coupon_code = coupon_data["coupon_code"]
			
			# Keep the discount amount from the quotation
			if quotation.discount_amount:
				sales_order.apply_discount_on = "Grand Total"
				sales_order.discount_amount = quotation.discount_amount
				
		elif "gift_card_coupon" in coupon_data:
			# Set gift card coupon in the sales order
			coupon_code = coupon_data["gift_card_coupon"]

			# Check if the coupon code is valid and has a sufficient amount
			coupon_doc = frappe.get_doc("Coupon Code", coupon_code)
			discount_amount = quotation.discount_amount
		
			# Ensure the coupon code is valid and has a sufficient amount
			if coupon_doc.gift_card_amount < discount_amount:
				frappe.throw(_("Gift card amount ({0}) is less than required discount amount ({1})").format(
					coupon_doc.gift_card_amount, discount_amount
				))
			
			# Apply the coupon code to the sales order
			sales_order.coupon_code = coupon_code
			
			# Ensure the discount is correctly applied
			if discount_amount:
				sales_order.apply_discount_on = "Grand Total"
				sales_order.discount_amount = discount_amount

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
	
	# Le split a déjà été fait avant l'insertion du sales order, 
	# donc nous n'avons pas besoin de faire quoi que ce soit ici

	if hasattr(frappe.local, "cookie_manager"):
		frappe.local.cookie_manager.delete_cookie("cart_count")

	return sales_order.name


def process_gift_card_on_submit(doc, method=None):
	"""
	Hook function called when a Sales Order is submitted.
	Checks if the Sales Order was created from a Quotation with a gift card
	that needs to be split, and processes the split if needed.
	"""
	if doc.doctype != "Sales Order" or not doc.docstatus == 1:
		return
	
	# Check if this Sales Order was created from a Quotation
	if not doc.quotation:
		return
	
	# Get the Quotation
	try:
		quotation = frappe.get_doc("Quotation", doc.quotation)
		
		# Check if this Quotation has a gift card that needs to be split
		if hasattr(quotation, "gift_card_coupon") and quotation.gift_card_coupon and \
		   hasattr(quotation, "gift_card_original_amount") and quotation.gift_card_original_amount:
			
			# Check if we need to split the gift card
			gift_card_amount = flt(quotation.gift_card_original_amount)
			used_amount = flt(quotation.discount_amount)
			
			if gift_card_amount > used_amount and used_amount > 0:
				excess_amount = gift_card_amount - used_amount
				
				# Prepare gift card data for processing
				gift_card_data = {
					"coupon_code": quotation.gift_card_coupon,
					"gift_card_amount": gift_card_amount,
					"used_amount": used_amount,
					"excess_amount": excess_amount
				}
				
				# Process the gift card split
				process_gift_card_split(doc, gift_card_data)
	except Exception as e:
		frappe.log_error(f"Gift Card Processing Error: {str(e)}", _("Error processing gift card for Sales Order {0}").format(doc.name))


def process_gift_card_split(sales_order, gift_card_data):
	"""
	Process gift card split after sales order creation.
	If the gift card amount is greater than the amount used:
	1. Create a NEW gift card for the amount USED in the order
	2. Update the ORIGINAL gift card to keep only the REMAINING amount
	3. Update the sales_order to use the NEW gift card instead of the original
	"""
	try:
		# Extract gift card data - try both new and old key names for compatibility
		coupon_name = gift_card_data.get("gift_card_coupon") or gift_card_data.get("coupon_code")
		gift_card_amount = flt(gift_card_data.get("gift_card_amount"))
		used_amount = flt(gift_card_data.get("used_amount"))
		excess_amount = flt(gift_card_data.get("excess_amount"))
		
		# If there's no excess amount, nothing to do
		if not excess_amount or excess_amount <= 0:
			return
		
		# Get the coupon details
		coupon_doc = frappe.get_doc("Coupon Code", coupon_name)
		
		# Generate a new unique code
		try:
			# Try to import from POS module if available
			from erpnext.selling.page.point_of_sale.point_of_sale import generate_gift_card_code
			new_code = generate_gift_card_code()
			# Make sure code is unique
			while frappe.db.exists("Coupon Code", {"coupon_code": new_code}):
				new_code = generate_gift_card_code()
		except ImportError:
			# If not available, generate a simple code
			import random, string
			letters = string.ascii_uppercase + string.digits
			code_parts = [
				''.join(random.choice(letters) for _ in range(4)),
				''.join(random.choice(letters) for _ in range(4)),
				''.join(random.choice(letters) for _ in range(4))
			]
			new_code = '-'.join(code_parts)
			
			# Make sure the code is unique
			while frappe.db.exists("Coupon Code", {"coupon_code": new_code}):
				code_parts = [
					''.join(random.choice(letters) for _ in range(4)),
					''.join(random.choice(letters) for _ in range(4)),
					''.join(random.choice(letters) for _ in range(4))
				]
				new_code = '-'.join(code_parts)
		
		# Get customer info
		customer_name = sales_order.customer
		
		# IMPORTANT: Contrairement à notre implémentation précédente, nous créons
		# une nouvelle carte cadeau pour le montant UTILISÉ (pas pour le montant restant)
		# et nous laissons le montant RESTANT sur la carte d'origine
		
		# Get or create pricing rule for the USED amount (not the excess amount)
		pricing_rule_name = None
		pricing_rule_filters = {
			"apply_on": "Transaction",
			"price_or_product_discount": "Price",
			"is_cumulative": 1,
			"valid_upto": "2999-12-31",
			"selling": 1,
			"buying": 0,
			"coupon_code_based": 1,
			"disable": 0,
			"margin_type": "Amount",
			"rate_or_discount": "Discount Amount",
			"discount_amount": used_amount  # USED amount, not excess
		}
		
		pricing_rule = frappe.db.exists("Pricing Rule", pricing_rule_filters)
		
		if not pricing_rule:
			try:
				pricing_rule = frappe.get_doc({
					"doctype": "Pricing Rule",
					"title": f"{_('Gift Card')} {used_amount:.2f}",
					**pricing_rule_filters
				})
				
				pricing_rule.insert(ignore_permissions=True)
				pricing_rule_name = pricing_rule.name
			except Exception as e:
				frappe.log_error("Gift Card - Error Creating Pricing Rule", f"Error creating Pricing Rule: {str(e)}\nData: {pricing_rule_filters}")
				return
		else:
			pricing_rule_name = pricing_rule
		
		# Create the new gift card with the USED amount (not excess)
		new_coupon_name = _("Gift Card") + f" {format_currency_value(used_amount, currency=sales_order.currency)} - {customer_name or _('Customer')} - {new_code}"
		
		new_gift_card = frappe.get_doc({
			"doctype": "Coupon Code",
			"coupon_name": new_coupon_name,
			"coupon_type": "Gift Card",
			"coupon_code": new_code,
			"pricing_rule": pricing_rule_name,
			"valid_from": coupon_doc.valid_from,
			"valid_upto": coupon_doc.valid_upto,
			"maximum_use": 1,
			"used": 1,  # Marked as used since it's already applied to this order
			"customer": customer_name,
			"gift_card_amount": used_amount,  # USED amount, not excess
			"coupon_code_residual": coupon_doc.name,  # Link to original card
			"description": _("Created from split of {0} in webshop. Used in order {1}. Original amount: {2}, Used: {3}, Remaining on original card: {4}").format(
				coupon_doc.coupon_code,
				sales_order.name,
				format_currency_value(gift_card_amount, currency=sales_order.currency),
				format_currency_value(used_amount, currency=sales_order.currency),
				format_currency_value(excess_amount, currency=sales_order.currency)
			)
		})
		
		new_gift_card.insert(ignore_permissions=True)
		new_gift_card.save(ignore_permissions=True)
		
		# Now update the original gift card to keep only the REMAINING amount
		# Remember the old coupon code for the message
		old_code = coupon_doc.coupon_code
		
		# Add a note about the split
		if coupon_doc.description:
			coupon_doc.description += f"\n\n{_('Amount adjusted on')} {frappe.utils.today()} : {format_currency_value(gift_card_amount, currency=sales_order.currency)} → {format_currency_value(excess_amount, currency=sales_order.currency)}. {_('Amount used')} ({format_currency_value(used_amount, currency=sales_order.currency)}) {_('transferred to new card')} {new_code} {_('for order')} {sales_order.name}."
		else:
			coupon_doc.description = f"{_('Amount adjusted on')} {frappe.utils.today()} : {format_currency_value(gift_card_amount, currency=sales_order.currency)} → {format_currency_value(excess_amount, currency=sales_order.currency)}. {_('Amount used')} ({format_currency_value(used_amount, currency=sales_order.currency)}) {_('transferred to new card')} {new_code} {_('for order')} {sales_order.name}."
		
		# Update gift card amount to REMAINING amount (not used amount)
		coupon_doc.gift_card_amount = excess_amount
		
		# Original card is NOT marked as used since it still has value
		coupon_doc.used = 0
		
		# Save the original gift card
		coupon_doc.save(ignore_permissions=True)
		
		# We need to update the sales_order to use the NEW gift card instead of the original
		# But we can't modify coupon_code after submission, so we'll use a custom field
		# or add a comment to track this information
		try:
			# Try to update a custom field if it exists
			if hasattr(sales_order, "gift_card_used"):
				sales_order.gift_card_used = new_code
				sales_order.db_update()
			elif frappe.get_meta("Sales Order").has_field("gift_card_used"):
				frappe.db.set_value("Sales Order", sales_order.name, "gift_card_used", new_code)
		except Exception as e:
			frappe.log_error(f"Error updating Sales Order with new gift card: {str(e)}", "Gift Card Split")
		
		# Add info to the sales order's comment to record the transaction
		frappe.get_doc({
			"doctype": "Comment",
			"comment_type": "Info",
			"reference_doctype": sales_order.doctype,
			"reference_name": sales_order.name,
			"content": _("Gift card {0} split: amount utilisé {1} transféré à une nouvelle carte cadeau {2}. Montant restant sur la carte originale: {3}.").format(
				old_code,
				format_currency_value(used_amount, currency=sales_order.currency),
				new_code,
				format_currency_value(excess_amount, currency=sales_order.currency)
			)
		}).insert(ignore_permissions=True)
		
		# Show a message to the user about the split
		frappe.msgprint(
			_("Carte cadeau {0} valeur ({1}) excède le total de la commande ({2}). Une nouvelle carte cadeau ({3}) a été créée pour le montant utilisé. Le montant restant ({4}) est disponible sur la carte originale.").format(
				old_code,
				format_currency_value(gift_card_amount, currency=sales_order.currency),
				format_currency_value(used_amount, currency=sales_order.currency),
				new_code,
				format_currency_value(excess_amount, currency=sales_order.currency)
			),
			title=_("Carte Cadeau Divisée")
		)
		
	except Exception as e:
		frappe.log_error(f"Gift Card Split Error: {str(e)}", _(
			"Error while creating new gift card during split. Original: {0}, Amount: {1}").format(
			coupon_name, gift_card_amount
		))


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
		
		# Import guest cart handler
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
	
	# Check if quotation exists
	if not quotation:
		return {"success": False, "message": _("No cart found")}

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
	
	# Set permissions flags before applying cart settings
	quotation.flags.ignore_permissions = True
	quotation.flags.ignore_mandatory = True
	
	apply_cart_settings(quotation=quotation)

	quotation.payment_schedule = []
	if not empty_card:
		quotation.save(ignore_version=True)
	else:
		quotation.delete()
		quotation = None

	set_cart_count(quotation)

	if cint(with_items):
		try:
			context = get_cart_quotation(quotation)
		except frappe.PermissionError:
			# If permission error for guest, try with a simplified context
			if frappe.session.user == "Guest":
				context = {
					"doc": quotation,
					"cart_settings": frappe.get_cached_doc("Webshop Settings"),
					"shipping_addresses": [],
					"billing_addresses": [],
					"shipping_rules": []
				}
			else:
				raise
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
		return {"name": quotation.name if quotation else None}

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

	# Update customer's primary address if this is a primary address
	if address.is_primary_address:
		from frappe.contacts.doctype.address.address import get_address_display

		# Find the linked customer from address links
		for link in address.links:
			if link.link_doctype == "Customer":
				customer = frappe.get_doc("Customer", link.link_name)
				customer.customer_primary_address = address.name
				# Also set the formatted address text for display in lists
				customer.primary_address = get_address_display(address.name)
				customer.save(ignore_permissions=True)
				break

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

@frappe.whitelist(allow_guest=True)
def update_cart_address(address_type, address_name):
	try:
		quotation = _get_cart_quotation()
		if not quotation:
			frappe.throw(_("Cart not found"))
			
		address_doc = frappe.get_doc("Address", address_name).as_dict()
		address_display = get_address_display(address_doc)
	
		if address_type.lower() == "billing":
			quotation.customer_address = address_name
			quotation.address_display = address_display
			quotation.shipping_address_name = (
				quotation.shipping_address_name or address_name
			)
			# For guests, create address info directly
			if frappe.session.user == "Guest":
				address_doc = {
					"name": address_name,
					"title": address_doc.get("address_title"),
					"display": address_display
				}
			else:
				address_doc = next(
					(doc for doc in get_billing_addresses() if doc["name"] == address_name),
					None,
				)
		elif address_type.lower() == "shipping":
			quotation.shipping_address_name = address_name
			quotation.shipping_address = address_display
			quotation.customer_address = quotation.customer_address or address_name
			# For guests, create address info directly
			if frappe.session.user == "Guest":
				address_doc = {
					"name": address_name,
					"title": address_doc.get("address_title"),
					"display": address_display
				}
			else:
				address_doc = next(
					(doc for doc in get_shipping_addresses() if doc["name"] == address_name),
					None,
				)
			
		# Set ignore_permissions flag early to avoid permission errors
		quotation.flags.ignore_permissions = True
		quotation.flags.ignore_mandatory = True
		
		# Ensure quotation has valid totals before applying settings
		if quotation.grand_total is None:
			quotation.grand_total = 0
		if quotation.base_grand_total is None:
			quotation.base_grand_total = 0
		
		# Ensure other required fields are set
		if not quotation.conversion_rate:
			quotation.conversion_rate = 1
		if not quotation.plc_conversion_rate:
			quotation.plc_conversion_rate = 1
		
		# Clear payment schedule before recalculation to avoid errors
		quotation.payment_schedule = []
		
		# For guest quotations, ensure party_name is set
		if frappe.session.user == "Guest":
			if not quotation.party_name or quotation.party_name == "Guest":
				guest_customer = frappe.db.get_single_value("Webshop Settings", "guest_customer")
				if guest_customer:
					quotation.party_name = guest_customer
					quotation.quotation_to = "Customer"
			
		apply_cart_settings(quotation=quotation)

		# Calculate taxes and totals before saving
		quotation.run_method("set_missing_values")
		quotation.run_method("calculate_taxes_and_totals")
		
		# Ensure totals are set after calculation
		if quotation.grand_total is None:
			quotation.grand_total = quotation.total or 0
		if quotation.base_grand_total is None:
			quotation.base_grand_total = quotation.grand_total * (quotation.conversion_rate or 1)
		
		quotation.save(ignore_permissions=True)
		
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
	except Exception as e:
		frappe.log_error(f"Error updating cart address: {str(e)}", "Cart Address Update Error")
		frappe.throw(_("Error updating address. Please try again or contact support."))

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
		variant_item_name = None
		variant_image = None

		# Variant Item
		if not frappe.db.exists("Website Item", {"item_code": item_code}):
			variant_data = frappe.db.get_values(
				"Item",
				filters={"item_code": item_code},
				fieldname=["variant_of", "item_name", "image"],
				as_dict=True,
			)[0]
			item_code = variant_data.variant_of
			variant_item_name = variant_data.item_name
			variant_image = variant_data.image

		# Get website item data (parent/template item data for variants)
		website_item_data = frappe.db.get_value(
			"Website Item", {"item_code": item_code}, fields, as_dict=True
		) or {}
		
		d.update(website_item_data)
		
		# For variants, override with variant-specific data
		if variant_item_name:
			d.web_item_name = variant_item_name
		
		# For images: use variant image if available, otherwise use parent/template image
		if variant_image:
			d.thumbnail = variant_image
			d.website_image = variant_image
		elif not d.get("website_image") and website_item_data.get("website_image"):
			# If variant has no image, ensure parent/template image is used
			d.website_image = website_item_data.get("website_image")
			d.thumbnail = website_item_data.get("thumbnail") or website_item_data.get("website_image")

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
		# Update transaction date if necessary
		from frappe.utils import today
		if qdoc.transaction_date != today():
			qdoc.transaction_date = today()
	else:
		company = frappe.db.get_single_value("Webshop Settings", "company")
		from frappe.utils import today
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
				"transaction_date": today()
			}
		)

		# Get contact that belongs to this customer
		contact_person = None
		if party.name:
			# Try to find a contact linked to this customer with ANY email
			# (not just the session user's email, as the contact might have a different primary email)
			contact_person = frappe.db.sql("""
				SELECT c.name 
				FROM `tabContact` c
				JOIN `tabDynamic Link` dl ON dl.parent = c.name
				WHERE dl.link_doctype = %s 
				AND dl.link_name = %s
				AND dl.parenttype = 'Contact'
				ORDER BY c.is_primary_contact DESC, c.creation ASC
				LIMIT 1
			""", (party.doctype, party.name), as_dict=True)
			
			if contact_person:
				qdoc.contact_person = contact_person[0].name
			else:
				# If no contact exists for this customer, try to create one
				try:
					contact = frappe.new_doc("Contact")
					contact.first_name = frappe.db.get_value("User", frappe.session.user, "first_name") or frappe.session.user.split("@")[0]
					contact.append("links", {
						"link_doctype": party.doctype,
						"link_name": party.name
					})
					contact.append("email_ids", {
						"email_id": frappe.session.user,
						"is_primary": 1
					})
					contact.flags.ignore_permissions = True
					contact.insert()
					qdoc.contact_person = contact.name
				except Exception:
					# If contact creation fails, leave contact_person as None
					qdoc.contact_person = None
		
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
	
	# Make sure default_currency is set
	if not party.get("default_currency"):
		from webshop.webshop.doctype.webshop_settings.webshop_settings import get_shopping_cart_settings
		cart_settings = get_shopping_cart_settings()
		if cart_settings.company:
			party.default_currency = frappe.get_cached_value("Company", cart_settings.company, "default_currency")

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

	# Update transaction date if necessary
	from frappe.utils import today
	if quotation.transaction_date != today():
		quotation.transaction_date = today()

	# Ensure required fields are set to avoid NoneType errors
	if not quotation.conversion_rate:
		quotation.conversion_rate = 1
	if not quotation.plc_conversion_rate:
		quotation.plc_conversion_rate = 1
	
	# Initialize totals if they are None
	if quotation.total is None:
		quotation.total = 0
	if quotation.grand_total is None:
		quotation.grand_total = 0
	if quotation.base_grand_total is None:
		quotation.base_grand_total = 0
	if quotation.rounded_total is None:
		quotation.rounded_total = 0
	if quotation.base_rounded_total is None:
		quotation.base_rounded_total = 0

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
        loyalty_tax_idx = None
        
        for i, tax in enumerate(quotation.taxes):
            if tax.is_loyalty_points_reduction:
                has_loyalty_tax = True
                tax.tax_amount = -quotation.loyalty_amount
                loyalty_tax_idx = i
                break
        
        # If tax line does not exist, add it manually at the end
        if not has_loyalty_tax:
            loyalty_program = frappe.db.get_value("Customer", quotation.party_name, "loyalty_program")
            if loyalty_program:
                loyalty_program_doc = frappe.get_doc("Loyalty Program", loyalty_program)
                
                # Calculate the correct idx value (should be the next available index)
                max_idx = 0
                for tax in quotation.taxes:
                    if tax.idx > max_idx:
                        max_idx = tax.idx
                
                next_idx = max_idx + 1
                
                # Add the loyalty tax with the correct idx value
                quotation.append("taxes", {
                    "idx": next_idx,
                    "charge_type": "Actual",
                    "description": "Loyalty program",
                    "account_head": loyalty_program_doc.expense_account,
                    "cost_center": loyalty_program_doc.cost_center,
                    "tax_amount": -quotation.loyalty_amount,
                    "is_loyalty_points_reduction": 1
                })
        
        # Ensure sequential idx values after modifications
        quotation.taxes.sort(key=lambda x: x.idx)
        for i, tax in enumerate(quotation.taxes):
            tax.idx = i + 1
				
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

	# Check if the user already exists as a Portal User
	# This is the MOST RELIABLE way to find the correct customer
	existing_customers = frappe.db.sql("""
		SELECT parent 
		FROM `tabPortal User` 
		WHERE user = %s 
		AND parenttype = 'Customer'
		ORDER BY creation ASC
		LIMIT 1
	""", user, as_dict=True)
	
	if existing_customers:
		customer_name = existing_customers[0].parent
		# Verify the customer still exists and is not disabled
		if frappe.db.exists("Customer", {"name": customer_name, "disabled": 0}):
			return frappe.get_doc("Customer", customer_name)

	# Try to find via Contact
	contact_name = get_contact_name(user)
	party = None

	if contact_name:
		contact = frappe.get_doc("Contact", contact_name)
		if contact.links:
			party_doctype = contact.links[0].link_doctype
			party = contact.links[0].link_name

	# Try another method: search for customer by email in contact
	if not party:
		# Search for customer with matching email
		customer_via_email = frappe.db.sql("""
			SELECT DISTINCT dl.link_name
			FROM `tabContact` c
			JOIN `tabContact Email` ce ON ce.parent = c.name
			JOIN `tabDynamic Link` dl ON dl.parent = c.name
			WHERE ce.email_id = %s
			AND dl.link_doctype = 'Customer'
			AND dl.parenttype = 'Contact'
			ORDER BY c.creation ASC
			LIMIT 1
		""", user, as_dict=True)
		
		if customer_via_email:
			party_doctype = "Customer"
			party = customer_via_email[0].link_name

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

	# Only create new customer if we really can't find one
	if not frappe.db.exists("Portal User", {"user": user}):
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
		
		# Create contact with user information only if email is valid
		contact = None
		if user and "@" in user:
			try:
				contact = frappe.new_doc("Contact")
				contact.update({
					"first_name": user_doc.first_name or "",
					"last_name": user_doc.last_name or "",
					"full_name": fullname or "",
					"email_id": user,
					"user": user,
					"is_primary_contact": 1,
					"is_billing_contact": 1,
					"email_ids": [{
						"email_id": user,
						"is_primary": 1
					}]
				})
			except Exception as e:
				frappe.log_error("Shopping Cart Contact Preparation Error", f"Error preparing contact for {user}: {str(e)}")
		
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
		
		# Get company default currency
		company_currency = None
		if cart_settings.company:
			company_currency = frappe.get_cached_value("Company", cart_settings.company, "default_currency")

		customer.update(
			{
				"customer_name": f"{user_doc.first_name} {user_doc.last_name}".strip(),
				"customer_type": "Individual",
				"customer_group": get_shopping_cart_settings().default_customer_group,
				"territory": get_root_of("Territory"),
				"default_currency": company_currency
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
		try:
			customer.insert(ignore_permissions=True)

			# Vérifier si l'email est valide avant de créer un contact
			if user and "@" in user:
				contact = frappe.new_doc("Contact")
				contact.update({
					"first_name": user_doc.first_name or "",
					"last_name": user_doc.last_name or "",
					"is_primary_contact": 1,
					"is_billing_contact": 1,
					"email_ids": [{"email_id": user, "is_primary": 1}]
				})
				contact.append("links", dict(link_doctype="Customer", link_name=customer.name))
				contact.flags.ignore_mandatory = True
				try:
					contact.insert(ignore_permissions=True)
					# Update customer with primary contact reference
					customer.customer_primary_contact = contact.name
					customer.save(ignore_permissions=True)
				except Exception as contact_error:
					frappe.log_error("Shopping Cart Contact Creation Error", f"Error inserting contact for {user}: {str(contact_error)}")
		except Exception as e:
			frappe.log_error("Shopping Cart Customer Creation Error", f"Error inserting automatic Customer/Contact for {user}: {str(e)}")
			# In case of failure, try to find an existing client linked to the guest_customer
			if cart_settings.guest_customer:
				return frappe._dict({
					"name": cart_settings.guest_customer,
					"customer_group": frappe.db.get_value("Customer", cart_settings.guest_customer, "customer_group")
				})

		return customer
	else:
		customer = frappe.db.get_value(
			"Portal User", {"user": user}, ["parent"]
		)

		if frappe.db.exists("Customer", customer):
			return frappe.get_doc("Customer", customer)

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

	# Handle guest customers
	if frappe.session.user == "Guest" and isinstance(party, dict):
		# For guests with a dict party, we need to handle it differently
		address_names = frappe.db.get_all(
			"Dynamic Link",
			fields=("parent"),
			filters=dict(
				parenttype="Address", link_doctype="Customer", link_name=party.get("name")
			),
		)
	else:
		# Normal flow for logged in users
		address_names = frappe.db.get_all(
			"Dynamic Link",
			fields=("parent"),
			filters=dict(
				parenttype="Address", link_doctype=party.doctype, link_name=party.name
			),
		)

	out = []

	for a in address_names:
		try:
			# For guests, we need to bypass permission checks
			if frappe.session.user == "Guest":
				address = frappe.get_doc("Address", a.parent)
				# Set flags to bypass permissions for display calculation
				address.flags.ignore_permissions = True
			else:
				address = frappe.get_doc("Address", a.parent)
			address.display = get_address_display(address.as_dict())
			out.append(address)
		except frappe.PermissionError:
			# Skip addresses that the user doesn't have permission to access
			continue

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

	# Don't auto-apply shipping rules on initial load
	# Let the user select them on checkout
	if not quotation.shipping_rule:
		# Just calculate totals without shipping
		quotation.run_method("calculate_taxes_and_totals")
		return

	if quotation.shipping_rule:
		try:
			quotation.run_method("apply_shipping_rule")
			quotation.run_method("calculate_taxes_and_totals")
		except Exception as e:
			# If shipping rule fails (e.g., weight/value out of range), 
			# remove it and continue without shipping charges
			error_message = str(e)
			if "not within the range" in error_message or "Not Applicable" in error_message:
				quotation.shipping_rule = None
				quotation.run_method("calculate_taxes_and_totals")
			else:
				# Re-raise other types of errors
				raise

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
				.where((sr_country.country == country) & (sr.disabled != 1) & (sr.shipping_rule_type == "Selling"))
			)
			result = query.run(as_list=True)
			all_shipping_rules = [x[0] for x in result]
			
			# Filter rules based on applicability
			# Calculate total weight if needed
			total_weight = 0
			if quotation.items:
				for item in quotation.items:
					item_doc = frappe.get_cached_doc("Item", item.item_code)
					if hasattr(item_doc, "weight_per_unit") and item_doc.weight_per_unit:
						total_weight += flt(item_doc.weight_per_unit) * flt(item.qty)
			
			# Check each rule's applicability
			for rule_name in all_shipping_rules:
				try:
					rule = frappe.get_cached_doc("Shipping Rule", rule_name)
					# Simple check if rule might be applicable based on conditions
					# The actual validation will happen when apply_shipping_rule is called
					applicable = True
					
					# Check if rule has weight-based conditions
					if rule.conditions:
						for condition in rule.conditions:
							if condition.from_value and condition.to_value:
								# For now, just add the rule and let apply_shipping_rule handle validation
								pass
					
					if applicable:
						shipping_rules.append(rule_name)
				except Exception:
					# If we can't check the rule, include it and let apply_shipping_rule handle it
					shipping_rules.append(rule_name)

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
		
		# Make sure default_currency is set
		if not customer_doc.get("default_currency"):
			from webshop.webshop.doctype.webshop_settings.webshop_settings import get_shopping_cart_settings
			cart_settings = get_shopping_cart_settings()
			if cart_settings.company:
				customer_doc.default_currency = frappe.get_cached_value("Company", cart_settings.company, "default_currency")
			
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

		# Check if contact exists for user
		contact_found = False
		if quotation.party_name:
			# Check if a contact exists directly for the user
			contact_name = get_contact_name(frappe.session.user)
			if contact_name:
				contact = frappe.get_doc("Contact", contact_name)
				contact_found = True
			else:
				# If no contact is directly linked to the user, check for contacts linked to the customer
				contacts = frappe.get_all("Dynamic Link", 
					fields=["parent"], 
					filters={
						"link_doctype": "Customer", 
						"link_name": quotation.party_name,
						"parenttype": "Contact"
					})
				
				if contacts:
					# Use the first contact linked to the customer
					contact = frappe.get_doc("Contact", contacts[0].parent)
					contact_found = True
					
					# Update the link with the current user
					contact.user = frappe.session.user
					
					# Check and update email if necessary
					if email and not any(e.email_id == email for e in contact.email_ids):
						for e in contact.email_ids:
							e.is_primary = 0
						contact.append("email_ids", {"email_id": email, "is_primary": 1})
		
		# If no contact was found, create a new one
		if not contact_found:
			contact = frappe.new_doc("Contact")
			contact.user = frappe.session.user
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
		
		# Update or add phone (as mobile number)
		if phone:
			contact.phone = phone  # Set the main phone field
			contact.mobile_no = phone  # Also set mobile_no field
			if not contact.phone_nos:
				contact.append("phone_nos", {
					"phone": phone,
					"is_primary_mobile_no": 1
				})
			else:
				contact.phone_nos[0].phone = phone
				contact.phone_nos[0].is_primary_mobile_no = 1
				contact.phone_nos[0].is_primary_phone = 0

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
    
    # Get the coupon document to check usage limits
    coupon_doc = frappe.get_doc("Coupon Code", coupon_name)
    
    # Check coupon validity based on type
    if coupon_doc.coupon_type == "Promotional":
        # For promotional coupons, check maximum usage limit
        if coupon_doc.maximum_use and coupon_doc.used >= coupon_doc.maximum_use:
            frappe.throw(_("This coupon code has reached its maximum usage limit"))
    elif coupon_doc.coupon_type == "Gift Card":
        # For gift cards, we also need to check maximum usage limit
        # Gift cards should only be used up to their maximum_use value
        if coupon_doc.maximum_use and coupon_doc.used >= coupon_doc.maximum_use:
            frappe.throw(_("This gift card has already been used and cannot be applied again"))
    
    # Check date validity
    from datetime import datetime
    from frappe.utils import getdate
    today = datetime.now().date()
    
    if coupon_doc.valid_from and getdate(coupon_doc.valid_from) > today:
        frappe.throw(_("This coupon code is not yet valid"))
        
    if coupon_doc.valid_upto and getdate(coupon_doc.valid_upto) < today:
        frappe.throw(_("This coupon code has expired"))

    # Import validate_coupon_code but we've already done our custom validations
    from erpnext.accounts.doctype.pricing_rule.utils import validate_coupon_code
    validate_coupon_code(coupon_name)
    quotation = _get_cart_quotation()
    
    # Check if this is a gift card
    is_gift_card = coupon_doc.coupon_type == "Gift Card" and hasattr(coupon_doc, "gift_card_amount")
    
    # Store coupon information in custom fields but NOT in the coupon_code field
    # This avoids standard processing of the coupon
    quotation.temp_coupon_code = coupon_name
    
    # For gift cards, we need to store the original amount for later processing
    if is_gift_card:
        gift_card_amount = flt(coupon_doc.gift_card_amount)
        
        # Set the gift card coupon reference and amount
        quotation.gift_card_coupon = coupon_name
        quotation.gift_card_original_amount = gift_card_amount
        
        # Calculate the order total before any discount
        order_total = flt(quotation.grand_total) if quotation.grand_total else flt(quotation.rounded_total)
        
        # If gift card amount exceeds total, limit the discount
        if gift_card_amount > order_total and order_total > 0:
            # Calculate the limited discount amount (just enough to make total = 0)
            max_discount = order_total
            
            # Flag for gift card split during order placement
            quotation.gift_card_to_split = 1
        else:
            # Use the full amount
            max_discount = gift_card_amount
            quotation.gift_card_to_split = 0
            
        # Set the discount amount (will be automatically applied)
        quotation.apply_discount_on = "Grand Total"
        quotation.discount_amount = max_discount
        if hasattr(quotation, "base_discount_amount"):
            quotation.base_discount_amount = max_discount
        
        # Add a comment to inform the user if there's excess
        if gift_card_amount > order_total and order_total > 0:
            frappe.get_doc({
                "doctype": "Comment",
                "comment_type": "Info",
                "reference_doctype": "Quotation",
                "reference_name": quotation.name,
                "content": _("Gift card amount ({0}) exceeds order total ({1}). The excess amount ({2}) will be converted to a new gift card upon order submission.").format(
                    frappe.format(gift_card_amount, dict(fieldtype="Currency")),
                    frappe.format(order_total, dict(fieldtype="Currency")),
                    frappe.format(gift_card_amount - order_total, dict(fieldtype="Currency"))
                )
            }).insert(ignore_permissions=True)
    else:
        # For regular coupons, we need to calculate and apply the discount ourselves
        # so that we can control exactly how it's applied
        quotation.coupon_code = coupon_name
        
    # Save without setting coupon_code
    quotation.flags.ignore_permissions = True
    quotation.save()
    
    # For regular coupons (not gift cards), check that discount does not exceed total amount
    if quotation.discount_amount > quotation.rounded_total and not is_gift_card:
        # Remove if discount is too high and it's not a gift card
        quotation.temp_coupon_code = ""
        quotation.discount_amount = 0
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
	# Clear our temporary coupon code
	quotation.temp_coupon_code = ""
	# Clear coupon code
	quotation.coupon_code = ""
	# Clear any gift card information
	if hasattr(quotation, "gift_card_coupon"):
		quotation.gift_card_coupon = ""
	if hasattr(quotation, "gift_card_original_amount"):
		quotation.gift_card_original_amount = 0
	# Clear discount
	quotation.discount_amount = 0
	if hasattr(quotation, "base_discount_amount"):
		quotation.base_discount_amount = 0
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

    # Round loyalty points to nearest 10
    import math
    raw_loyalty_points = float(loyalty_points_details.get("loyalty_points", 0))
    rounded_loyalty_points = math.floor(raw_loyalty_points / 10) * 10
    
    # Update the loyalty_points_details with rounded points
    loyalty_points_details["loyalty_points"] = rounded_loyalty_points
    
    # Calculate equivalent value based on rounded points
    conversion_factor = loyalty_points_details.get("conversion_factor", 0)
    equivalent_value = rounded_loyalty_points * conversion_factor
    
    context = {
        "doc": quotation,
        "cart_settings": cart_settings,
        "available_loyalty_points": rounded_loyalty_points,
        "conversion_factor": conversion_factor,
        "loyalty_points_value": format_currency_value(equivalent_value, currency=quotation.currency),
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
		apply_loyalty_points_tax(quotation)
	
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
	try:
		website_item = frappe.get_cached_doc("Website Item", {"item_code": item_code})
		return website_item.is_gift_card if website_item else False
	except frappe.DoesNotExistError:
		# If Website Item doesn't exist, it's not a gift card
		return False

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

# Check if gift cards exist
@frappe.whitelist(allow_guest=True)
def check_gift_cards(code):
	"""Check if gift cards exist"""
	
	coupon_code = frappe.db.exists("Coupon Code", {"coupon_code": code})
	return bool(coupon_code)

def create_gift_cards_from_invoice(doc, method=None):
	"""Create gift cards for gift card items in a paid invoice"""
	try:
		sales_invoice = doc
		if not sales_invoice.docstatus == 1 or sales_invoice.outstanding_amount > 0 or sales_invoice.is_pos == 1:
			return

		# Check if any gift card item
		for item in sales_invoice.items:
			if not is_gift_card_item(item.item_code):
				continue
				
			gift_card_data = json.loads(item.gift_card_data) if item.gift_card_data else None
			if gift_card_data and gift_card_data.get("code"):
				# Check if gift card code already exists
				if frappe.db.exists("Coupon Code", {"coupon_code": gift_card_data.get("code")}):
					return

		# Check validity settings in Webshop Settings
		settings = frappe.get_single("Webshop Settings")
		validity_months = cint(settings.get("number_of_valid_months", 0))
		valid_from = frappe.utils.today()
		valid_upto = frappe.utils.add_months(valid_from, validity_months) if validity_months > 0 else None

		for item in sales_invoice.items:
			if not is_gift_card_item(item.item_code):
				continue

			# Find or create a Pricing Rule
			pricing_rule_filters = {
				"apply_on": "Transaction",
				"price_or_product_discount": "Price",
				"is_cumulative": 1,
				"valid_upto": "2999-12-31",
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
						"title": f"{_('Gift Card')} {item.rate:.2f}",
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
					coupon_name = _("Gift card {0} - {1} - {2}").format(
						format_currency_value(item.rate, currency=sales_invoice.currency),
						sales_invoice.customer,
						coupon_code
					)

					customer = frappe.get_doc("Customer", sales_invoice.customer)

					gift_card = frappe.get_doc({
						"doctype": "Coupon Code",
						"coupon_name": coupon_name,
						"coupon_type": "Gift Card",
						"coupon_code": coupon_code,
						"pricing_rule": pricing_rule_name,
						"valid_from": valid_from,
						"valid_upto": valid_upto,
						"maximum_use": 9999,
						"used": 0,
						"customer": sales_invoice.customer,
						"sales_invoice": sales_invoice.name,
						"gift_card_amount": item.rate,
						"owner":  customer.portal_users[0].user
					})

					gift_card.ignore_permissions = True
					gift_card.insert(ignore_permissions=True)
					gift_card.save(ignore_permissions=True)
					
					# Update owner
					user_email = None
					if customer.portal_users:
						user = customer.portal_users[0].user
						user_email = user
						frappe.db.sql("""
							UPDATE `tabCoupon Code`
							SET `owner` = %s, `modified_by` = %s
							WHERE name = %s
						""", (user, user, gift_card.name))
						frappe.db.commit()
					
					# Send notification if configured
					webshop_settings = frappe.get_doc("Webshop Settings")
					if webshop_settings.gift_card_notification and user_email:
						try:
							notification = frappe.get_doc("Notification", webshop_settings.gift_card_notification)
							if notification:
								# Send notification
								from frappe.core.doctype.communication.email import _make
								_make(
									doctype=gift_card.doctype,
									name=gift_card.name,
									subject=notification.subject,
									content=frappe.render_template(notification.message, {"doc": gift_card}),
									recipients=[user_email],
									send_email=True,
									communication_medium="Email",
									sender=notification.sender_email,
									sender_full_name=notification.sender
								)

						except Exception as e:
							frappe.log_error("Gift Card - Notification Error", f"Error sending notification: {str(e)}")
					
				except Exception as e:
					frappe.log_error("Gift Card - Error creation",f"Error creating Gift Card: {str(e)}\nData: {gift_card.as_dict() if 'gift_card' in locals() else 'Not created'}")
					raise

	except Exception as e:
		frappe.log_error("Gift Card - General error",f"General error creating Gift Card: {str(e)}")
		raise

def check_gift_cards_from_payment(doc, method=None):
	"""Checks payment-related invoices and creates gift cards if necessary"""
	try:
		payment_entry = doc
		
		# Check only validated payments	
		if not payment_entry.docstatus == 1:
			return
			
		# Loop through payment references
		for ref in payment_entry.references:
			if ref.reference_doctype == "Sales Invoice" and ref.outstanding_amount == 0:
				sales_invoice = frappe.get_doc("Sales Invoice", ref.reference_name)
				
				# Check invoice is validated and has no outstanding amount
				if sales_invoice.docstatus == 1 and sales_invoice.outstanding_amount == 0:
					# Create gift cards from invoice
					create_gift_cards_from_invoice(sales_invoice)
					
	except Exception as e:
		frappe.log_error("Gift Card - Payment Check Error", f"Error checking payment for gift cards: {str(e)}")
		raise


def process_gift_card_split(sales_order, coupon_data):
	"""
	Process the splitting of a gift card when its amount exceeds the order total.
	
	Args:
		sales_order: Sales Order document
		coupon_data: Dictionary containing gift card information
		
	Returns:
		dict: Status and information about the split gift card
	"""
	try:
		# Check if it's a gift card that needs splitting
		if not coupon_data or not coupon_data.get("is_gift_card") or not coupon_data.get("gift_card_coupon"):
			return {"status": "error", "message": "Invalid gift card data"}
			
		gift_card_coupon = coupon_data.get("gift_card_coupon")
		used_amount = flt(coupon_data.get("used_amount"))
		excess_amount = flt(coupon_data.get("excess_amount"))
		
		# Verify amounts are valid
		if used_amount <= 0 or excess_amount <= 0:
			return {"status": "error", "message": "Invalid gift card amounts"}
			
		# Get the original gift card
		original_card = frappe.get_doc("Coupon Code", gift_card_coupon)
		if not original_card or original_card.coupon_type != "Gift Card":
			return {"status": "error", "message": "Gift card not found or invalid type"}
			
		# Generate a unique code for the new gift card
		import string
		import random
		
		def generate_unique_gift_card_code():
			"""Generate a unique code for a gift card"""
			def generate_segment():
				"""Generate a segment of 4 alphanumeric characters"""
				chars = string.ascii_uppercase + string.digits
				return ''.join(random.choice(chars) for _ in range(4))
			
			# Generate initial code
			code = f"{generate_segment()}-{generate_segment()}-{generate_segment()}"
			
			# Check if the code already exists
			while frappe.db.exists("Coupon Code", {"coupon_code": code}):
				code = f"{generate_segment()}-{generate_segment()}-{generate_segment()}"
			
			return code
			
		new_code = generate_unique_gift_card_code()
		
		# Get validity parameters from the original card
		valid_from = original_card.valid_from
		valid_upto = original_card.valid_upto
		
		# Create pricing rule for the new excess amount
		pricing_rule_filters = {
			"apply_on": "Transaction",
			"price_or_product_discount": "Price",
			"is_cumulative": 1,
			"valid_upto": "2999-12-31",
			"selling": 1,
			"buying": 0,
			"coupon_code_based": 1,
			"disable": 0,
			"margin_type": "Amount",
			"rate_or_discount": "Discount Amount",
			"discount_amount": excess_amount
		}
		
		pricing_rule = frappe.db.exists("Pricing Rule", pricing_rule_filters)
		
		if not pricing_rule:
			try:
				pricing_rule = frappe.get_doc({
					"doctype": "Pricing Rule",
					"title": f"{_('Gift Card')} {excess_amount:.2f}",
					**pricing_rule_filters
				})
				
				pricing_rule.insert(ignore_permissions=True)
				pricing_rule_name = pricing_rule.name
			except Exception as e:
				frappe.log_error("Gift Card - Error Creating Pricing Rule", f"Error creating Pricing Rule: {str(e)}")
				return {"status": "error", "message": "Error creating pricing rule"}
		else:
			pricing_rule_name = pricing_rule
		
		# Create the new gift card with the excess amount
		new_card_name = _("Gift Card {0} - {1} - {2}").format(
			format_currency_value(excess_amount, currency=sales_order.currency),
			original_card.customer,
			new_code
		)
		
		# Get the customer info
		customer = frappe.get_doc("Customer", original_card.customer)
		user_email = None
		if hasattr(customer, "portal_users") and customer.portal_users:
			user = customer.portal_users[0].user
			user_email = user
		
		# Create the new gift card
		new_gift_card = frappe.get_doc({
			"doctype": "Coupon Code",
			"coupon_name": new_card_name,
			"coupon_type": "Gift Card",
			"coupon_code": new_code,
			"pricing_rule": pricing_rule_name,
			"valid_from": valid_from,
			"valid_upto": valid_upto,
			"maximum_use": 9999,
			"used": 0,
			"customer": original_card.customer,
			"gift_card_amount": excess_amount,
			"description": _("Created from gift card: {0} (remaining amount after order {1})").format(
				original_card.name, sales_order.name
			)
		})
		
		if user_email:
			new_gift_card.owner = user_email
		
		new_gift_card.insert(ignore_permissions=True)
		new_gift_card.save(ignore_permissions=True)
		
		# Update the original gift card
		original_card.gift_card_amount = used_amount  # Update to the used amount
		original_card.used = 1  # Mark as used
		
		# Add a note to the description
		original_amount = used_amount + excess_amount
		if original_card.description:
			original_card.description += f"\n\n{_('Amount adjusted on')} {today()} for order {sales_order.name}: {format_currency_value(original_amount, currency=sales_order.currency)} → {format_currency_value(used_amount, currency=sales_order.currency)}. {_('Remaining amount')} ({format_currency_value(excess_amount, currency=sales_order.currency)}) {_('transferred to card')} {new_code}."
		else:
			original_card.description = f"{_('Amount adjusted on')} {today()} for order {sales_order.name}: {format_currency_value(original_amount, currency=sales_order.currency)} → {format_currency_value(used_amount, currency=sales_order.currency)}. {_('Remaining amount')} ({format_currency_value(excess_amount, currency=sales_order.currency)}) {_('transferred to card')} {new_code}."
		
		original_card.save(ignore_permissions=True)
		
		# Send notification if configured
		webshop_settings = frappe.get_cached_doc("Webshop Settings")
		if webshop_settings.gift_card_notification and user_email:
			try:
				notification = frappe.get_doc("Notification", webshop_settings.gift_card_notification)
				if notification:
					# Send notification
					from frappe.core.doctype.communication.email import _make
					_make(
						doctype=new_gift_card.doctype,
						name=new_gift_card.name,
						subject=notification.subject,
						content=frappe.render_template(notification.message, {"doc": new_gift_card}),
						recipients=[user_email],
						send_email=True,
						communication_medium="Email",
						sender=notification.sender_email,
						sender_full_name=notification.sender
					)
			except Exception as e:
				frappe.log_error("Gift Card - Notification Error", f"Error sending notification: {str(e)}")
		
		# Ensure the changes are saved
		frappe.db.commit()
		
		# Display a message to the user
		frappe.msgprint(
			_("A new gift card has been created with the remaining amount of {0}. Card code: {1}").format(
				format_currency_value(excess_amount, currency=sales_order.currency),
				new_code
			),
			title=_("Gift Card Split")
		)
		
		return {
			"status": "success",
			"message": _("Gift card split successfully"),
			"new_gift_card": new_code,
			"original_gift_card": original_card.name,
			"used_amount": used_amount,
			"excess_amount": excess_amount
		}
		
	except Exception as e:
		frappe.log_error("Gift Card - Error Splitting", f"Error splitting gift card: {str(e)}")
		return {"status": "error", "message": f"Error: {str(e)}"}
