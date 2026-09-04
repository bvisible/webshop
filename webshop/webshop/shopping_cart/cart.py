# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt
#//// Neoffice — added imports. `random`/`re` mint and validate gift-card codes,
#//// `json` reads the gift_card_data blob carried on the quotation items, `os`
#//// resolves the per-gateway checkout templates (3bc2d836f1, 2025-02-11 "Add gift
#//// cards and improve shopping cart"). TO REVIEW: `from locale import currency` is
#//// dead — nothing in this file uses it, and it shadows nothing; a leftover.
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
#//// Neoffice — added imports, and the block below is re-indented from four spaces
#//// to tabs by our editor config (no behaviour change; take OUR side on the
#//// whitespace at the merge). get_price applies Pricing Rules to a cart line — our
#//// gift cards and multi-site price lists need the resolved price, not the raw
#//// Item Price. format_currency_value honours the shop's "hide currency symbol"
#//// setting (0134ef756e, 2025-07-03). get_loyalty_program_details_with_points is
#//// the ERPNext entry point for the loyalty balance the cart spends (3bc2d836f1,
#//// 2025-02-11).
from erpnext.utilities.product import get_price
from webshop.webshop.doctype.webshop_settings.webshop_settings import (
	get_shopping_cart_settings,
)
from webshop.webshop.utils.product import get_web_item_qty_in_stock
#//// Neoffice — added: every amount the shop prints goes through it, so the
#//// "hide currency symbol" setting is honoured everywhere (0134ef756e, 2025-07-03).
from webshop.webshop.utils.utils import format_currency_value

try:
	from erpnext.selling.doctype.quotation.quotation import _make_sales_order
except ImportError:
	from erpnext.selling.doctype.quotation.mapper import _make_sales_order

#//// Neoffice — added: the ERPNext entry point for the loyalty balance the cart
#//// spends (3bc2d836f1, 2025-02-11 "Add gift cards and improve shopping cart").
from erpnext.accounts.doctype.loyalty_program.loyalty_program import (
	get_loyalty_program_details_with_points,
)

#//// Neoffice — body re-indented to tabs only.
class WebsitePriceListMissingError(frappe.ValidationError):
	pass

def set_cart_count(quotation=None):
	#//// Neoffice — upstream reads the cart of the signed-in user only, so an anonymous
	#//// visitor's badge always showed 0. Our shops let a visitor fill a cart before
	#//// signing in (Webshop Settings.enable_guest_cart), so the guest branch resolves —
	#//// or creates — the quotation keyed on the guest_session_id cookie. The count is
	#//// read defensively (`if quotation else 0`) because create_guest_quotation can
	#//// legitimately return nothing (3bc2d836f1, 2025-02-11).
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


#//// Neoffice — upstream: @frappe.whitelist(). Opened to guests because the cart
#//// drawer and the /cart page are rendered for anonymous visitors on our shops.
#//// The function itself never trusts the caller: every path resolves the party
#//// from the session, or from the guest_session_id cookie, never from an argument
#//// (3bc2d836f1, 2025-02-11).
@frappe.whitelist(allow_guest=True)
def get_cart_quotation(doc=None):
	party = get_party()
	#//// Neoffice — added. Upstream assumes get_party() always answers; a signed-in user
	#//// with no Customer yet (a fresh account, or a staff member browsing the shop)
	#//// raised an AttributeError on the next line. Returns an empty but well-shaped
	#//// context instead, so the page renders with an empty cart.
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
		#//// Neoffice — added guest branch (3bc2d836f1, 2025-02-11). Upstream builds the
		#//// cart from _get_cart_quotation(party), which needs a Customer. Here the
		#//// quotation is found by the guest_session_id cookie, and created if there is
		#//// none; every failure path returns the same empty-context shape rather than
		#//// throwing, because this runs on a page an anonymous visitor is entitled to see.
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
	#//// Neoffice — upstream: `if not doc.customer_address and addresses:`. doc can now
	#//// legitimately be None (guest with no cart yet), and this ran before any check.
	if doc and not doc.customer_address and addresses:
		update_cart_address("billing", addresses[0].name)

	#//// Neoffice — do the same for the shipping address.
	#////
	#//// The B2C tunnel survives without one: its shipping step falls back to the
	#//// billing address unless "ship to different" is ticked. The B2B page does
	#//// not — templates/includes/cart/cart_address.html renders an address ONLY
	#//// when it is already the one on the quotation, so with no shipping address
	#//// it showed nothing at all: no picker, no way to choose, the shipping
	#//// methods stuck on "select an address first", and "Place Order" disabled
	#//// forever. A B2B customer simply could not order, with nothing on screen
	#//// saying why.
	#////
	#//// Same address as billing, so taxes and shipping rules are unchanged.
	if doc and not doc.get("shipping_address_name") and addresses:
		update_cart_address("shipping", addresses[0].name)
		#//// update_cart_address writes to the database through its OWN copy of
		#//// the quotation; the `doc` we are about to return was loaded before
		#//// that and still shows the old value, which reads like the assignment
		#//// failed and sends whoever is debugging in the wrong direction.
		#////
		#//// Mirrored in memory rather than reloaded: doc.reload() re-reads the
		#//// document WITH permission checks, and a Website User may not read a
		#//// Quotation directly — it turned every cart read into a 403
		#//// "Pas d'autorisation pour Devis". The value is the one just written.
		doc.shipping_address_name = addresses[0].name

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
	#//// Neoffice — was get_value("Customer", doc.customer_name, …). customer_name
	#//// is the LABEL (fetched from party_name.customer_name), while Frappe
	#//// resolves a link by its ID. They match only while customers are named
	#//// after themselves. This site names them by series, and 5 of its 202
	#//// customers already differ ("Acme Corp - 2" vs "Acme Corp"): for those,
	#//// the lookup returned None, so is_b2b_customer stayed False and a genuine
	#//// B2B customer was silently sent to the B2C checkout — with no error to
	#//// explain it. party_name is the actual link field.
	party_id = (doc.get("party_name") or doc.get("customer_name")) if doc else None
	if party_id and frappe.session.user != "Guest":
		customer_info = frappe.db.get_value("Customer", party_id, ["name", "customer_group"], as_dict=1)
		
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
		#//// Neoffice — same reason: doc may be None for a guest with no cart.
		"doc": decorate_quotation_doc(doc) if doc else None,
		"shipping_addresses": get_shipping_addresses(party),
		"billing_addresses": get_billing_addresses(party),
		#//// Neoffice — upstream passes only the party. The rules depend on the cart too
		#//// (weight, contents, and "no shipping when every line is a gift card"), so the
		#//// quotation is passed down (6d4eca593f, 2025-12-12).
		"shipping_rules": get_applicable_shipping_rules(party, doc),
		"cart_settings": frappe.get_cached_doc("Webshop Settings"),
		#//// Neoffice — added to the context. Everything the checkout renders in one call:
		#//// the loyalty balance and its cash value (3bc2d836f1, 2025-02-11), whether the
		#//// customer goes through the B2B tunnel (48e2708353, 2025-03-13), and whether the
		#//// loyalty block is shown to guests. Added here rather than in a second endpoint
		#//// because the checkout was making four round-trips per step (70745ad0c3,
		#//// 2026-08-26 "supprimer les allers-retours inutiles").
		"available_loyalty_points": available_loyalty_points,
		"loyalty_points_value": loyalty_points_value,
		"loyalty_program_details": loyalty_program_details,
		"customer_info": customer_info,
		"is_b2b_customer": is_b2b_customer,
		"loyalty_info": loyalty_info,
		"show_loyalty": show_loyalty,
		"show_loyalty_for_guests": show_loyalty_for_guests
	}


#//// Neoffice — was `if address.address_type == "Shipping"`.
#////
#//// address_type is a LABEL in Frappe, not a permission: any address of the
#//// party may be shipped to. A customer whose only address is typed "Billing" —
#//// the default when the shop creates one, and the common case for a company
#//// with a single site — got an empty list here. On the B2B page that is fatal:
#//// cart_address.html iterates this list, so nothing was rendered, the shipping
#//// methods stayed on "select an address first", and "Place Order" could never
#//// be enabled. The customer saw a dead page with no explanation.
#////
#//// Addresses genuinely marked for shipping still come first, so nothing
#//// changes for a shop that does type them.
@frappe.whitelist()
def get_shipping_addresses(party=None):
	if not party:
		party = get_party()
	addresses = get_address_docs(party=party)

	#//// Neoffice — upstream filters `if address.address_type == "Shipping"`, which hid
	#//// every other address from the shipping picker. An address type is a LABEL, not a
	#//// permission: a customer whose only address is typed "Billing" could not check out
	#//// at all (c36f7a3411, 2026-08-27 "le type d'adresse est une etiquette, pas une
	#//// permission"). We now sort instead of filtering — typed Shipping first, then the
	#//// flagged one, then the rest.
	def rang(address):
		if address.address_type == "Shipping":
			return 0
		return 1 if cint(address.get("is_shipping_address")) else 2

	return [
		{
			"name": address.name,
			"title": address.address_title,
			"display": address.display,
		}
		#//// Neoffice — sorted, not filtered (see rang above).
		for address in sorted(addresses, key=rang)
	]


@frappe.whitelist()
#//// Neoffice — same fix as get_shipping_addresses, for the mirror case: a
#//// customer whose only address is typed "Shipping" or "Office" could not be
#//// billed. Addresses actually typed "Billing" still come first.
def get_billing_addresses(party=None):
	if not party:
		party = get_party()
	addresses = get_address_docs(party=party)

	#//// Neoffice — same as the shipping list above: upstream filtered on the address
	#//// type and left a customer with only a "Shipping" address unable to be billed
	#//// (c36f7a3411, 2026-08-27). Sorted, not filtered.
	def rang(address):
		if address.address_type == "Billing":
			return 0
		return 1 if cint(address.get("is_primary_address")) else 2

	return [
		{
			"name": address.name,
			"title": address.address_title,
			"display": address.display,
		}
		#//// Neoffice — sorted, not filtered (see rang above).
		for address in sorted(addresses, key=rang)
	]


#//// Neoffice — added endpoint. get_billing_addresses / get_shipping_addresses
#//// filter strictly on address_type, so an address a customer created as
#//// "Office" or "Personal" — perfectly ordinary in Frappe — belonged to
#//// neither list and was simply invisible at checkout. Frappe itself puts no
#//// such restriction: any address of the party can be used for billing or
#//// shipping, address_type being a label, not a permission.
#////
#//// This returns every address linked to the customer, with the fields the
#//// checkout form needs to prefill itself, so picking one costs no extra
#//// round trip. `preferred` marks the one Frappe would pick by default.
@frappe.whitelist()
def get_customer_addresses():
	party = get_party()
	if not party:
		return []

	names = frappe.get_all(
		"Dynamic Link",
		filters={
			"link_doctype": party.doctype,
			"link_name": party.name,
			"parenttype": "Address",
		},
		pluck="parent",
	)
	if not names:
		return []

	rows = frappe.get_all(
		"Address",
		filters={"name": ["in", names], "disabled": 0},
		fields=[
			"name", "address_title", "address_type",
			"address_line1", "address_line2", "city", "state", "pincode", "country",
			"phone", "email_id", "is_primary_address", "is_shipping_address",
		],
		order_by="is_primary_address desc, is_shipping_address desc, address_title asc",
	)

	out = []
	for row in rows:
		out.append(
			{
				"name": row.name,
				"title": row.address_title or row.name,
				"address_type": row.address_type,
				"display": get_address_display(frappe.get_doc("Address", row.name).as_dict()),
				"address_line1": row.address_line1,
				"address_line2": row.address_line2,
				"city": row.city,
				"state": row.state,
				"pincode": row.pincode,
				"country": row.country,
				"phone": row.phone,
				"email_id": row.email_id,
				"is_primary_address": cint(row.is_primary_address),
				"is_shipping_address": cint(row.is_shipping_address),
			}
		)
	return out


@frappe.whitelist()
def place_order():
	quotation = _get_cart_quotation()
	cart_settings = frappe.get_cached_doc("Webshop Settings")
	quotation.company = cart_settings.company
	
	# Save the coupon info for later use
	#//// Neoffice — added block (618eedfdb8, 2025-03-24 "Feat gift card split";
	#//// f114dc4b5d, 2025-12-12). Upstream knows coupons, not gift cards: a coupon is
	#//// spent whole or not at all. A gift card worth more than the order has to keep
	#//// its balance, so before the order is made we cap the discount at the order total
	#//// and record what was used and what is left; the split itself happens after the
	#//// Sales Order exists (process_gift_card_split below). temp_coupon_code is read
	#//// here because the code is entered on the cart, before the quotation is submitted.
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

	#//// Neoffice — added. Upstream leaves the quotation in draft and lets
	#//// _make_sales_order submit it. Our checkout can reach this point from a PSP
	#//// callback where the quotation was already saved but not submitted, and
	#//// _make_sales_order then refused it (eb8089afc5, 2025-12-11 "Submit quotation
	#//// before creating Sales Order in payment handler").
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

	#//// Neoffice — multi-warehouse: the line's warehouse is the source the
	#//// shopper chose — never overwrite it here (the historical overwrite is
	#//// what killed per-line sources at order time). Validate each line
	#//// against ITS source (own basis: Bin or Item field). Feature off: the
	#//// historical overwrite + single-warehouse validation are kept as is.
	from webshop.webshop.multi_warehouse import sources as mw_sources

	multi_enabled = mw_sources.is_enabled(cart_settings)

	if not cint(cart_settings.allow_items_not_in_stock):
		for item in sales_order.get("items"):
			#//// Neoffice — multi-warehouse (5bf2e88a1b, 2026-08-25). Upstream forces every line
			#//// onto the Website Item's single website_warehouse. When the shop sells from
			#//// several sources, the line already carries the warehouse the buyer chose and
			#//// overwriting it would move the order to the wrong stock.
			if not multi_enabled:
				item.warehouse = frappe.db.get_value(
					"Website Item", {"item_code": item.item_code}, "website_warehouse"
				)
			is_stock_item = frappe.db.get_value("Item", item.item_code, "is_stock_item")

			if is_stock_item:
				#//// Neoffice — the stock check follows the same rule: ask the CHOSEN source for its
				#//// quantity (a supplier source answers on its lead time, not on stock), fall back
				#//// to the line's warehouse, and only then to upstream's website_warehouse
				#//// (5bf2e88a1b, 2026-08-25).
				source_row = (
					mw_sources.get_source_for_warehouse(item.warehouse, cart_settings)
					if multi_enabled
					else None
				)
				#//// Neoffice — see the source_row block above (multi-warehouse stock check).
				if source_row:
					source_qty = mw_sources.get_source_qty(item.item_code, source_row)
					item_stock = frappe._dict(
						{"in_stock": 1 if source_qty > 0 else 0, "stock_qty": source_qty}
					)
				elif multi_enabled and item.warehouse:
					item_stock = get_web_item_qty_in_stock(
						item.item_code, "website_warehouse", warehouse=item.warehouse
					)
				else:
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

	#//// Neoffice — multi-warehouse: promise a delivery date per line from its
	#//// source's lead time (order_type "Shopping Cart" skips ERPNext's own
	#//// delivery_date computation), header = latest line.
	if multi_enabled:
		_set_delivery_dates_from_sources(sales_order, cart_settings)

	sales_order.flags.ignore_permissions = True
	sales_order.insert()
	sales_order.submit()
	
	# Le split a déjà été fait avant l'insertion du sales order, 
	# donc nous n'avons pas besoin de faire quoi que ce soit ici

	if hasattr(frappe.local, "cookie_manager"):
		frappe.local.cookie_manager.delete_cookie("cart_count")

	return sales_order.name


#//// Neoffice — added block, down to request_for_quotation below. ▼▼▼
#//// Upstream has no gift cards; ERPNext's Coupon Code is single-use and carries no
#//// balance. A card worth more than the order must not be burnt: on submit of the
#//// Sales Order we create a NEW card for the amount actually USED (marked used) and
#//// leave the REMAINDER on the original card, then record both on the order
#//// (618eedfdb8, 2025-03-24 "Feat gift card split"). Doing it after submit rather
#//// than in place_order is deliberate — the split must not happen if the order
#//// creation itself fails.
#//// TO REVIEW: the user-facing strings in this block are hardcoded French instead
#//// of _() msgids (RULE #00), and two comments are French. ▲▲▲
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


#//// Neoffice — added helper (multi-warehouse). Warehouse of the first cart
#//// line already holding this item, guest or logged-in, so an implicit add
#//// (grid button, +1 spinner) keeps feeding the source the shopper already
#//// chose instead of silently moving the line.
def _find_existing_line_warehouse(item_code):
	quotation_name = None
	if frappe.session.user == "Guest":
		guest_session_id = (
			frappe.request.cookies.get("guest_session_id") if frappe.request else None
		)
		if guest_session_id:
			quotation_name = frappe.db.get_value(
				"Quotation",
				{"guest_session_id": guest_session_id, "docstatus": 0, "status": "Draft"},
				"name",
			)
	else:
		party = get_party()
		if party:
			quotation_name = frappe.db.get_value(
				"Quotation",
				{
					"party_name": party.name,
					"contact_email": frappe.session.user,
					"order_type": "Shopping Cart",
					"docstatus": 0,
				},
				"name",
			)

	if not quotation_name:
		return None

	return frappe.db.get_value(
		"Quotation Item",
		{"parent": quotation_name, "item_code": item_code},
		"warehouse",
		order_by="idx asc",
	)


#//// Neoffice — added helper (multi-warehouse). Sets delivery_date per Sales
#//// Order line from its source's lead time and the header to the latest
#//// line. Called by both order paths (place_order and the payment handler);
#//// ERPNext's own delivery_date logic does not run for order_type
#//// "Shopping Cart".
def _set_delivery_dates_from_sources(sales_order, cart_settings=None):
	from webshop.webshop.multi_warehouse import sources as mw_sources
	from webshop.webshop.multi_warehouse.delays import estimate_delivery_date

	cart_settings = cart_settings or frappe.get_cached_doc("Webshop Settings")
	latest = None
	for item in sales_order.get("items") or []:
		source_row = mw_sources.get_source_for_warehouse(item.warehouse, cart_settings)
		if source_row:
			item.delivery_date = estimate_delivery_date(source_row)
			if not latest or item.delivery_date > latest:
				latest = item.delivery_date
	if latest:
		sales_order.delivery_date = latest


#//// Neoffice — added helper (no upstream equivalent).
#////
#//// Cancels the payment requests of a cart that were never honoured, so the
#//// quotation they point at can be deleted. Only Draft and Failed ones: a
#//// request that actually succeeded belongs to a real order and is never
#//// touched here.
#////
#//// Exists because a customer whose card was declined could no longer empty
#//// their cart — see the LinkExistsError branch in update_cart.
def _liberer_demandes_de_paiement_infructueuses(quotation_name):
	demandes = frappe.get_all(
		"Payment Request",
		filters={
			"reference_doctype": "Quotation",
			"reference_name": quotation_name,
			"status": ["in", ("Draft", "Failed", "Initiated", "Requested")],
			"docstatus": ["<", 2],
		},
		fields=["name", "docstatus"],
	)
	for demande in demandes:
		try:
			doc = frappe.get_doc("Payment Request", demande.name)
			doc.flags.ignore_permissions = True
			if doc.docstatus == 1:
				doc.cancel()
			else:
				doc.delete()
		except Exception:
			#//// Une demande qu'on n'arrive pas à libérer ne doit pas faire
			#//// échouer l'opération: la suppression qui suit dira si elle bloque
			#//// encore, et l'erreur remontera alors avec son vrai motif.
			frappe.log_error(
				"Webshop: libération de demande de paiement impossible",
				frappe.get_traceback(),
			)
			frappe.clear_messages()


#//// Neoffice — multi-warehouse: `warehouse` selects the stock source of the
#//// line. None keeps the historical behaviour (single website_warehouse, or
#//// the auto-picked source when the feature is on). Cart lines merge on
#//// (item_code, warehouse) so the same item can sit in the cart once per
#//// source, each line with its own delivery estimate.
@frappe.whitelist(allow_guest=True)
def update_cart(item_code, qty, additional_notes=None, with_items=False, add_qty=False, price_list_rate=None, gift_card_data=None, warehouse=None):
	#//// Neoffice multi-site — sur un site réservé aux professionnels, remplir
	#//// un panier demande un compte. La garde vit ici plutôt que dans le
	#//// gabarit: masquer un bouton n'est pas une permission, et cet endpoint
	#//// est appelable directement.
	from webshop.webshop.multi_site import exiger_connexion_pour_acheter

	exiger_connexion_pour_acheter()

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

	#//// Neoffice — multi-warehouse: resolve the target stock source of this
	#//// cart line before validating. Explicit warehouse wins; otherwise an
	#//// existing line of the item keeps its source (stable, no surprise
	#//// moves), and a first add auto-picks the first source covering the
	#//// quantity. Feature off: warehouse stays None and every path below
	#//// behaves exactly as before.
	from webshop.webshop.multi_warehouse import sources as mw_sources

	cart_settings = frappe.get_cached_doc("Webshop Settings")
	multi_enabled = mw_sources.is_enabled(cart_settings) and not is_gift_card

	if not multi_enabled:
		warehouse = None
	else:
		allowed_warehouses = mw_sources.get_allowed_warehouses(item_code, cart_settings)
		if warehouse and allowed_warehouses and warehouse not in allowed_warehouses:
			frappe.throw(_("Invalid stock source for {0}").format(item_code))
		if not warehouse and qty > 0:
			existing_line_warehouse = _find_existing_line_warehouse(item_code)
			warehouse = existing_line_warehouse or mw_sources.resolve_target_warehouse(
				item_code, qty, cart_settings
			)

	# Validate stock availability before adding to cart
	if qty > 0 and not is_gift_card:
		if not cint(cart_settings.allow_items_not_in_stock):
			# Check if item is a stock item
			is_stock_item = frappe.db.get_value("Item", item_code, "is_stock_item")
			if is_stock_item:
				#//// Neoffice — multi-warehouse: validate against the targeted
				#//// source (its own basis: Bin or Item field), not the global
				#//// website_warehouse.
				if multi_enabled and warehouse:
					source_row = mw_sources.get_source_for_warehouse(warehouse, cart_settings)
					if source_row:
						source_qty = mw_sources.get_source_qty(item_code, source_row)
					else:
						source_qty = get_web_item_qty_in_stock(
							item_code, "website_warehouse", warehouse=warehouse
						).stock_qty
					item_stock = frappe._dict(
						{"in_stock": 1 if source_qty > 0 else 0, "stock_qty": source_qty}
					)
					source_label = mw_sources.get_source_label(warehouse, cart_settings)
				else:
					item_stock = get_web_item_qty_in_stock(item_code, "website_warehouse")
					source_label = None

				if not cint(item_stock.in_stock):
					if source_label:
						frappe.throw(
							_("{0} is not in stock at {1}").format(item_code, source_label)
						)
					frappe.throw(_("{0} is not in stock").format(item_code))

				# Calculate the total quantity (existing + new)
				#//// Neoffice — multi-warehouse: the existing quantity is the
				#//// one already targeting the same source, not the whole item.
				line_filters = {'item_code': item_code}
				if multi_enabled and warehouse:
					line_filters['warehouse'] = warehouse

				existing_qty = 0
				if frappe.session.user == "Guest":
					guest_session_id = frappe.request.cookies.get('guest_session_id') if frappe.request else None
					if guest_session_id:
						existing_quotation = frappe.db.get_value(
							'Quotation',
							{'guest_session_id': guest_session_id, 'docstatus': 0, 'status': 'Draft'},
							'name'
						)
						if existing_quotation:
							existing_qty = frappe.db.get_value(
								'Quotation Item',
								dict(line_filters, parent=existing_quotation),
								'qty'
							) or 0
				else:
					party = get_party()
					if party:
						existing_quotation = frappe.db.get_value(
							'Quotation',
							{'party_name': party.name, 'contact_email': frappe.session.user, 'order_type': 'Shopping Cart', 'docstatus': 0},
							'name'
						)
						if existing_quotation:
							existing_qty = frappe.db.get_value(
								'Quotation Item',
								dict(line_filters, parent=existing_quotation),
								'qty'
							) or 0

				# Calculate total quantity based on add_qty flag
				if isinstance(add_qty, str):
					add_qty_bool = add_qty.lower() == 'true'
				else:
					add_qty_bool = add_qty

				total_qty = (existing_qty + qty) if add_qty_bool else qty

				if total_qty > item_stock.stock_qty:
					if source_label:
						frappe.throw(
							_("Only {0} units available at {1} for {2}. You cannot add {3} units from this source.").format(
								int(item_stock.stock_qty), source_label, item_code, int(total_qty)
							)
						)
					frappe.throw(
						_("Only {0} units available in stock for {1}. You cannot add {2} units to your cart.").format(
							int(item_stock.stock_qty), item_code, int(total_qty)
						)
					)

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
				#//// Neoffice — multi-warehouse: a line only matches when it
				#//// targets the same source; same-item lines on another
				#//// source are kept untouched. Feature off: item_code alone,
				#//// as before.
				same_line = item.item_code == item_code and (
					not multi_enabled or (item.warehouse or None) == (warehouse or None)
				)
				if same_line:
					found_item = True
					new_qty = item.qty + qty if add_qty else qty
					if new_qty > 0:
						item_dict = {
							"item_code": item.item_code,
							"qty": new_qty,
							"warehouse": item.warehouse or warehouse,
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
						#//// Neoffice — multi-warehouse: preserve the source of
						#//// untouched lines across the guest-cart rebuild.
						"warehouse": item.warehouse,
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
					"qty": qty,
					"warehouse": warehouse,
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
			item_dict = {"item_code": item_code, "qty": qty, "warehouse": warehouse}
			if is_gift_card and price_list_rate:
				item_dict["rate"] = flt(price_list_rate)
				item_dict["price_list_rate"] = flt(price_list_rate)
			if gift_card_data:
				item_dict["gift_card_data"] = gift_card_data
			items = [item_dict] if qty > 0 else []
		
		result = create_guest_quotation(items)
		# Le panier du visiteur vient d'être supprimé parce qu'il ne restait
		# rien : on rend quand même la page vide, sinon la ligne retirée reste
		# affichée jusqu'au prochain rechargement.
		if result is None and isinstance(items, list) and not items:
			set_cart_count(None)
			if cint(with_items):
				# Le devis vient d'être supprimé : il n'y a plus rien à lire.
				# `get_cart_quotation(None)` rend un contexte dont `doc` est nul,
				# et le gabarit du total demande `doc.total` — 500 en pleine
				# figure du visiteur, pour un panier qu'il a simplement vidé.
				# Un devis neuf en mémoire, jamais enregistré, dit « zéro » sans
				# rien inventer.
				vide = frappe.new_doc("Quotation")
				# La devise du site, pas celle de Webshop Settings : ce doctype
				# n'en porte pas, et le lui demander lève une erreur — donc un
				# 417 à la place du panier vide.
				vide.currency = frappe.defaults.get_global_default("currency")
				context = {
					"doc": vide,
					"cart_settings": frappe.get_cached_doc("Webshop Settings"),
					"shipping_addresses": [],
					"billing_addresses": [],
					"shipping_rules": [],
				}
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
			return {"name": None}
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
	
	#//// Neoffice — added guard. _get_cart_quotation() can now return None (guest with
	#//// no cart, or a cart just emptied), where upstream always got a document
	#//// (b38414f95d, 2025-11-14 "Handle None quotation in update_cart return").
	# Check if quotation exists
	if not quotation:
		return {"success": False, "message": _("No cart found")}

	empty_card = False
	if qty == 0:
		#//// Neoffice — multi-warehouse: with an explicit source, only the
		#//// line targeting it is removed; the same item on another source
		#//// stays. Feature off (or no source given): every line of the item
		#//// goes, as before.
		if multi_enabled and warehouse:
			quotation_items = [
				d
				for d in quotation.get("items", [])
				if not (
					d.item_code == item_code
					and (d.warehouse or None) == (warehouse or None)
				)
			]
		else:
			quotation_items = quotation.get("items", {"item_code": ["!=", item_code]})
		# Une réservation se vend d'un bloc : le séjour, sa taxe, ses options.
		# Retirer le séjour doit emporter le reste ICI, avant de décider si le
		# panier est vide — sinon la taxe survit seule, le devis n'est pas
		# supprimé, et le client ne peut plus rien recommencer.
		quotation_items = _drop_booking_companions(quotation, item_code, quotation_items)
		if quotation_items:
			quotation.set("items", quotation_items)
		else:
			empty_card = True

	else:
		#//// Neoffice — multi-warehouse: the target source was resolved at the
		#//// top of update_cart; feature off resolves the single
		#//// website_warehouse exactly as before.
		if not multi_enabled:
			warehouse = frappe.get_cached_value(
				"Website Item", {"item_code": item_code}, "website_warehouse"
			)

		#//// Neoffice — multi-warehouse: merge on (item_code, warehouse) so
		#//// one line per source can coexist for the same item.
		if multi_enabled:
			quotation_items = [
				d
				for d in quotation.get("items", [])
				if d.item_code == item_code
				and (d.warehouse or None) == (warehouse or None)
			]
		else:
			quotation_items = quotation.get("items", {"item_code": item_code})
		if not quotation_items:
			#//// Neoffice — upstream appends the line and lets set_price_list_and_rate price it.
			#//// A gift card has no Item Price: its price IS the face value the buyer chose, so
			#//// the rate is written on the line and the chosen amount/recipient kept in
			#//// gift_card_data — otherwise the next repricing reset it to zero (3bc2d836f1,
			#//// 2025-02-11; qty > 1 f114dc4b5d, 2025-12-12).
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
		#//// Neoffice — an existing line now also carries the chosen warehouse
		#//// (multi-warehouse, 5bf2e88a1b, 2026-08-25).
		else:
			quotation_items[0].warehouse = warehouse
			quotation_items[0].additional_notes = additional_notes
			#//// Neoffice — upstream always REPLACES the quantity, so "add to cart" on a product
			#//// already in the cart reset it to 1 instead of adding. add_qty distinguishes the
			#//// two callers (the product page adds, the cart page sets); a quantity that falls
			#//// to zero removes the line (48e2708353, 2025-03-13).
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
		#//// Neoffice — ignore_version: the cart is saved on every quantity keystroke and
		#//// each save was writing a Version row, which made a busy shop's Version table the
		#//// largest in the database for no readable history.
		quotation.save(ignore_version=True)
	else:
		#//// Neoffice — emptying the cart deletes the quotation, and that delete
		#//// can be REFUSED: once a payment has been attempted, a Payment Request
		#//// links to it and Frappe raises LinkExistsError.
		#////
		#//// The customer then simply cannot empty their cart — removing the last
		#//// line fails with a technical error and the line stays. Reproduced on
		#//// osiris: "Impossible de supprimer ou d'annuler, car Devis … est
		#//// associé à Requête de Paiement ACC-PRQ-…".
		#////
		#//// Saving the quotation empty is not an option either: ERPNext requires
		#//// at least one line, so that save fails too and the whole transaction
		#//// rolls back — the line reappears and the cart is stuck for good.
		#////
		#//// What actually blocks is a payment request that never succeeded
		#//// (Draft, or Failed after a declined card). Those carry no accounting
		#//// value, so they are cancelled — which releases the link — and the
		#//// quotation goes. A request that DID succeed is left untouched: the
		#//// cart was ordered, and that is a different story.
		try:
			quotation.delete()
			quotation = None
		except frappe.LinkExistsError:
			frappe.clear_messages()
			_liberer_demandes_de_paiement_infructueuses(quotation.name)
			quotation.delete()
			quotation = None

	set_cart_count(quotation)

	if cint(with_items):
		#//// Neoffice — added guard. get_cart_quotation reads addresses and shipping rules; a
		#//// guest legitimately has no permission on those, and upstream's version simply
		#//// threw a PermissionError at a visitor who had just added an item. The guest gets
		#//// the reduced context the cart drawer actually needs.
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
			#//// Neoffice — the quotation itself, alongside the rendered HTML.
			#//// The context above already holds it, so this costs nothing here
			#//// and saves the caller a second round trip: the checkout used to
			#//// throw this HTML away and immediately call get_cart_quotation
			#//// to obtain the very document we had in hand.
			"doc": context.get("doc"),
		}
	else:
		#//// Neoffice — quotation may be None when the last line was removed and the cart
		#//// deleted itself (b38414f95d, 2025-11-14).
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
	#//// Neoffice — upstream saved immediately with ignore_permissions=True. We first
	#//// link the address to the caller's own Customer and only then save WITHOUT
	#//// ignore_permissions, so the Address permission rules still apply: an unlinked
	#//// address created with ignore_permissions belonged to nobody and was invisible in
	#//// the customer's address book afterwards (4c9773bf93, 2026-01-03).
	address = frappe.get_doc(doc)

	#//// Neoffice — see above; and when the address is flagged primary, the Customer's
	#//// customer_primary_address AND its displayed primary_address text are updated —
	#//// ERPNext only fills the text when the address is saved from the desk form, so a
	#//// customer created from the checkout showed an empty address in every list
	#//// (5bcccd131a / aeddc82961, 2025-11-25 and 2025-11-30).
	# Add link to current customer if not already provided
	if not address.links:
		party = get_party()
		if party:
			address.append("links", {
				"link_doctype": "Customer",
				"link_name": party.name
			})

	address.save()

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

	#//// Neoffice — returns the saved address (the customer link and the primary-address
	#//// update above happen before this return).
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

#//// Neoffice — upstream: @frappe.whitelist(). Guests reach this while checking out
#//// on a shop with enable_guest_cart. The body below re-reads the quotation from the
#//// session; the caller only names one of its own addresses.
@frappe.whitelist(allow_guest=True)
def update_cart_address(address_type, address_name):
	#//// Neoffice — the whole body is rewritten (upstream: read the address, set it on
	#//// the quotation, save, render). ▼▼▼ What it adds:
	#////   · a guest path — a guest has no read permission on Address, so the display is
	#////     built from the document we just read instead of from get_*_addresses();
	#////   · a null-safe cart (`Cart not found`) instead of an AttributeError;
	#////   · the shipping rule is cleared when the new address is in a country the rule
	#////     does not serve — it used to survive the change and then refuse the order at
	#////     the payment step (6d4eca593f, 2025-12-12);
	#////   · totals/conversion rates are defaulted before calculate_taxes_and_totals,
	#////     which raised on a cart that had never been priced;
	#////   · the errors are logged and turned into one message the buyer can act on.
	#//// The finally block resets frappe.flags.ignore_permissions — it must not leak to
	#//// the rest of the request. ▲▲▲
	try:
		# Temporarily ignore permissions to allow reading addresses
		frappe.flags.ignore_permissions = True

		quotation = _get_cart_quotation()
		if not quotation:
			frappe.throw(_("Cart not found"))

		address_doc = frappe.get_doc("Address", address_name).as_dict()
		address_display = get_address_display(address_doc)
		new_country = address_doc.get("country")

		#//// Neoffice — see the block marker above (guest display, shipping-rule country).
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

			#//// Neoffice — see the block marker above (6d4eca593f, 2025-12-12).
			# Check if current shipping rule is valid for the new country
			# If not, clear it so the user can select a compatible one
			if quotation.shipping_rule and new_country:
				if not _is_shipping_rule_valid_for_country(quotation.shipping_rule, new_country):
					quotation.shipping_rule = None
			
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

		#//// Neoffice — same payload as upstream, but reached from inside our try/except and
		#//// after the recalculation above; the except turns any failure into one readable
		#//// message instead of a traceback in the buyer's face.
		return {
			"taxes": frappe.render_template(
				"templates/includes/order/order_taxes.html", context
			),
			"address": frappe.render_template(
				"templates/includes/cart/address_card.html", context
			),
		}
	except Exception as e:
		frappe.log_error("Cart Address Update Error", f"Error updating cart address: {str(e)}")
		frappe.throw(_("Error updating address. Please try again or contact support."))
	finally:
		# Reset the permissions flag
		frappe.flags.ignore_permissions = False

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
		#//// Neoffice — a cart line for a variant showed the template's name and image;
		#//// the buyer could not tell two lines apart. The variant's own name and image are
		#//// resolved here (8f351c4819, 2025-03-18 "fix bug contact and image website
		#//// item").
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

		#//// Neoffice — multi-warehouse: the line's warehouse is the source the
		#//// shopper chose — rendering the cart must not overwrite it (that
		#//// historical overwrite is what made two-source lines impossible).
		#//// Instead, decorate the line with its shopper-facing label and
		#//// delivery estimate. Feature off: historical overwrite kept as is.
		from webshop.webshop.multi_warehouse import sources as mw_sources

		if mw_sources.is_enabled():
			if not d.get("warehouse"):
				d.warehouse = frappe.get_cached_value(
					"Website Item", {"item_code": item_code}, "website_warehouse"
				)
			mw_sources.decorate_cart_line(d)
		else:
			website_warehouse = frappe.get_cached_value(
				"Website Item", {"item_code": item_code}, "website_warehouse"
			)

			#//// Neoffice — upstream sets d.warehouse unconditionally. It is now inside the
			#//// branch above: a line that already carries the warehouse the buyer chose
			#//// (multi-warehouse) must keep it (5bf2e88a1b, 2026-08-25).
			d.warehouse = website_warehouse

	return doc

def _get_cart_quotation(party=None):
	"""Return the open Quotation of type "Shopping Cart" or make a new one"""
	if not party:
		party = get_party()
		#//// Neoffice — added guest branch: upstream returns nothing without a party, so an
		#//// anonymous visitor had no cart at all. The quotation is keyed on the
		#//// guest_session_id cookie and created on demand (3bc2d836f1, 2025-02-11).
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
		#//// Neoffice — a cart left open overnight kept yesterday's transaction_date, and
		#//// ERPNext then refused the invoice with "Due Date cannot be before Posting Date"
		#//// (f241c2d9c0, 2025-12-12).
		# Update transaction date if necessary
		from frappe.utils import today
		if qdoc.transaction_date != today():
			qdoc.transaction_date = today()
	else:
		company = frappe.db.get_single_value("Webshop Settings", "company")
		#//// Neoffice — same reason for a freshly created cart.
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
				#//// Neoffice — a cart created today must carry today's date, or ERPNext refuses the
				#//// invoice later with "Due Date cannot be before Posting Date" (f241c2d9c0,
				#//// 2025-12-12).
				"transaction_date": today()
			}
		)

		#//// Neoffice — upstream resolves the contact by `email_id == session user`, which
		#//// fails whenever the customer's contact carries a different primary e-mail (a
		#//// company account, an address changed since). We look for ANY contact linked to
		#//// the Customer, preferring the primary one, and create one if there is none —
		#//// without a contact the quotation cannot be turned into an invoice (912b84dbf6,
		#//// 2025-06-25 "Fix bug contact, shipping rules and image mobile").
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

#//// Neoffice — blank-line/whitespace only above; the body below adds the currency
#//// default (see next marker).
@frappe.whitelist()
def update_party(fullname, company_name=None, mobile_no=None, phone=None):
	party = get_party()

	party.customer_name = company_name or fullname
	party.customer_type = "Company" if company_name else "Individual"
	
	#//// Neoffice — added. A Customer created from the shop had no default_currency, and
	#//// ERPNext then priced its cart in the wrong currency on a multi-currency company
	#//// (a0c1c321dc, 2026-08-03 — Webshop Settings carries no currency field, so the
	#//// company's is used).
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

	#//// Neoffice — see _get_cart_quotation: a cart older than a day must be re-dated
	#//// before ERPNext prices it (f241c2d9c0, 2025-12-12).
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

	#//// Neoffice — added. The country can change between two calls (the buyer edits the
	#//// address); leaving a rule that does not serve the new country made
	#//// calculate_taxes_and_totals throw in the middle of the checkout (6d4eca593f,
	#//// 2025-12-12).
	# Validate shipping rule before calculating taxes
	# If the current shipping rule is not valid for the shipping address country, clear it
	if quotation.shipping_rule and quotation.shipping_address_name:
		shipping_country = frappe.db.get_value("Address", quotation.shipping_address_name, "country")
		if shipping_country and not _is_shipping_rule_valid_for_country(quotation.shipping_rule, shipping_country):
			quotation.shipping_rule = None

	quotation.run_method("calculate_taxes_and_totals")

	set_taxes(quotation, cart_settings)
	
	#//// Neoffice — points spent are booked as a negative charge line; it has to be
	#//// (re)applied after set_taxes, which rebuilds the tax table (3bc2d836f1,
	#//// 2025-02-11).
	apply_loyalty_points_tax(quotation)

	#//// Neoffice — added: the shop's terms are attached to every cart so they appear on
	#//// the order and the invoice (71dffb7b45, 2025-06-26 "add cgv terms and conditions
	#//// support").
	# Set terms and conditions from Webshop Settings if it's a new quotation
	if cart_settings.quotation_terms:
		quotation_terms = cart_settings.quotation_terms
		quotation.tc_name = quotation_terms
		quotation.terms = frappe.db.get_value("Terms and Conditions", quotation_terms, "terms")

	#//// Neoffice — moved to the END of apply_cart_settings (upstream calls it before the
	#//// taxes). The rule's charge is itself a tax line, so applying it first had it
	#//// wiped by set_taxes.
	_apply_shipping_rule(party, quotation, cart_settings)

def set_price_list_and_rate(quotation, cart_settings):
	"""set price list based on billing territory"""

	_set_price_list(cart_settings, quotation)

	# Reset values
	quotation.price_list_currency = (
		quotation.currency
	) = quotation.plc_conversion_rate = quotation.conversion_rate = None
	for item in quotation.get("items"):
		#//// Neoffice — upstream blanks every rate and refetches from the price list. A gift
		#//// card has no price list entry — its rate IS the face value chosen by the buyer,
		#//// kept in gift_card_data — so it is skipped here; without this the card fell to
		#//// zero on the next cart save (3bc2d836f1, 2025-02-11; 0b07bf847e, 2025-07-01).
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

#//// Neoffice — upstream picks the price list from the customer, then the shop
#//// default. On a bench serving several shops the site being browsed comes first:
#//// a professional site with its own price list was billing the standard tariff
#//// (705e78792f, 2026-08-28 "le panier facturait le tarif standard sur un site a
#//// tarif propre"). The quotation is passed in so a saved cart keeps the list it
#//// was priced with.
def _set_price_list(cart_settings, quotation=None):
	"""Set price list based on the site being browsed, the customer, or the default"""
	from erpnext.accounts.party import get_default_price_list

	party_name = quotation.get("party_name") if quotation else get_party().get("name")
	selling_price_list = None

	#//// Neoffice multi-site — the price list of the SITE wins.
	#////
	#//// The catalogue and the product page already price against the resolved
	#//// Website Profile (product_data_engine/query.py shadows
	#//// settings.price_list the same way). The cart did not: it went straight to
	#//// the customer default, then Webshop Settings.
	#////
	#//// So on the B2B domain a customer saw 199.00 in the listing, 199.00 on the
	#//// product page — and their cart charged 549.00, the standard rate.
	#//// Measured on osiris with item 6882C006. A shop that shows one price and
	#//// bills another is the one defect a webshop cannot have.
	#////
	#//// Only sites that actually define a price list are affected; everywhere
	#//// else the historical order below is untouched.
	profile = getattr(frappe.local, "website_profile_doc", None)
	if profile and profile.get("price_list"):
		selling_price_list = profile["price_list"]

	# Check if default customer price list exists
	if not selling_price_list and party_name and frappe.db.exists("Customer", party_name):
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
	
#//// Neoffice — added function. ERPNext books loyalty redemption on the invoice only;
#//// the cart has to show the discount before there is an invoice, so the points are
#//// carried as a charge line flagged is_loyalty_points_reduction, re-indexed so
#//// ERPNext's own tax ordering stays valid (3bc2d836f1, 2025-02-11).
#//// Re-indented with tabs: the function came in with four-space indentation while
#//// cart.py — upstream included — is tab-indented, so every diff of it fought the
#//// file. Whitespace only, no behaviour change.
#//// The expense account is checked before the charge row is built: see the marker
#//// inside the function.
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

				#//// Neoffice — guard added. expense_account is optional on Loyalty Program but
				#//// account_head is mandatory on Sales Taxes and Charges, so a programme without
				#//// one produced a charge row with an empty account: the cart then died on
				#//// "Account Head is mandatory", which names neither the loyalty programme nor
				#//// the setting to fix. Stopping here rather than skipping the row is deliberate
				#//// — both callers reach this line with points ALREADY spent (apply_loyalty_points
				#//// has written the Loyalty Point Entry, apply_cart_settings replays the row on an
				#//// existing cart), so dropping it silently would take the discount off the totals
				#//// while the buyer's points stay burnt.
				if not loyalty_program_doc.expense_account:
					frappe.throw(
						_("Loyalty Program {0} has no expense account").format(loyalty_program)
					)

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
					#//// Neoffice — translated: this description is printed on the cart, the
					#//// order and the invoice.
					"description": _("Loyalty program"),
					"account_head": loyalty_program_doc.expense_account,
					"cost_center": loyalty_program_doc.cost_center,
					"tax_amount": -quotation.loyalty_amount,
					"is_loyalty_points_reduction": 1
				})
		
		# Ensure sequential idx values after modifications
		quotation.taxes.sort(key=lambda x: x.idx)
		for i, tax in enumerate(quotation.taxes):
			tax.idx = i + 1
				
def get_party(user=None, ignore_permissions=False):
	"""Return the customer (Customer) for the current user"""
	if not user:
		user = frappe.session.user

	#//// Neoffice — added. Upstream has no notion of a guest party. When
	#//// enable_guest_cart is on, the shop's configured guest_customer stands in, so the
	#//// cart, the taxes and the shipping rules work exactly as for a signed-in buyer
	#//// (3bc2d836f1, 2025-02-11). Returns None — never a real Customer — when the shop
	#//// does not allow guest carts (04fab0f907, 2026-08-28: a professional site refuses
	#//// an anonymous order).
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

	#//// Neoffice — added, and it is the FIRST lookup on purpose. Upstream resolves the
	#//// party through the Contact, which picks the wrong Customer whenever a person is
	#//// a contact of several (a company and their own account): the buyer then saw
	#//// someone else's cart. Portal User is the authoritative link (0ef0381e9c,
	#//// 2025-11-25).
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
			if ignore_permissions:
				return frappe.get_cached_doc("Customer", customer_name)
			return frappe.get_doc("Customer", customer_name)

	# Try to find via Contact
	contact_name = get_contact_name(user)
	party = None

	if contact_name:
		#//// Neoffice — ignore_permissions is a caller-supplied flag (added with the
		#//// multi-warehouse and follow-up jobs, which run without a session). The cached
		#//// read is only taken on that path; a web request still goes through get_doc and
		#//// its permission check.
		contact = frappe.get_cached_doc("Contact", contact_name) if ignore_permissions else frappe.get_doc("Contact", contact_name)
		if contact.links:
			party_doctype = contact.links[0].link_doctype
			party = contact.links[0].link_name

	#//// Neoffice — third fallback: a Contact whose e-mail matches but which is not
	#//// linked to the session user. Without it, a customer whose portal user was
	#//// created after their contact had no party at all and could not check out
	#//// (0ef0381e9c, 2025-11-25).
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
		#//// Neoffice — same caller-supplied flag as above; the web path is unchanged.
		doc = frappe.get_cached_doc(party_doctype, party) if ignore_permissions else frappe.get_doc(party_doctype, party)
		if doc.doctype in ["Customer", "Supplier"]:
			if not frappe.db.exists("Portal User", {"parent": doc.name, "user": user}):
				doc.append("portal_users", {"user": user})
				doc.flags.ignore_permissions = True
				doc.flags.ignore_mandatory = True
				doc.save()

			#//// Neoffice — added. Frappe's Address permissions are owner-based for a Website
			#//// User: an address created by the shop under another owner was invisible to the
			#//// customer it belongs to, and the checkout showed an empty address book
			#//// (4c9773bf93, 2026-01-03).
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

	#//// Neoffice — upstream: `elif not frappe.db.exists("Portal User", ...)`, chained to
	#//// the contact lookup. Made a separate `if` so that the three lookups above all get
	#//// a chance before a SECOND customer is created for the same person — the
	#//// duplicate-customer bug (0ef0381e9c, 2025-11-25).
	# Only create new customer if we really can't find one
	if not frappe.db.exists("Portal User", {"user": user}):
		if not cart_settings.enabled:
			frappe.local.flags.redirect_location = "/contact"
			raise frappe.Redirect
		customer = frappe.new_doc("Customer")
		#//// Neoffice — added block, down to customer.update below. ▼▼▼ Upstream creates the
		#//// Customer from get_fullname() alone. We also: split a one-word full name into
		#//// first/last (ERPNext refuses a customer with an empty last name on some
		#//// settings), prepare the primary contact, grant the Customer role — without it the
		#//// buyer cannot read their own orders in the portal — and read the company's
		#//// default currency. The TimestampMismatchError retry is real: the same request can
		#//// save the User twice (0ef0381e9c / 74403819fc, 2025-11). ▲▲▲
		user_doc = frappe.get_doc("User", user)
		fullname = get_fullname(user)
		# If user has no last_name, try to deduce it
		if not user_doc.last_name:
			fullname_parts = fullname.split(' ', 1)  # Split into two parts at the first space
			user_doc.first_name = fullname_parts[0]
			user_doc.last_name = fullname_parts[1] if len(fullname_parts) > 1 else ""
			#//// Neoffice — ignore_permissions, like every other write of this block
			#//// (the roles save below, the Customer insert, the Contact insert).
			#//// get_party() runs AS THE SHOPPER, a Website User with no write right on
			#//// User: without it, the first product page opened by a customer whose
			#//// account has no last_name died on PermissionError. Upstream never had
			#//// the problem because it does not touch the User doc here at all.
			user_doc.save(ignore_permissions=True)
		
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
				#//// Neoffice — upstream uses get_fullname(), which returns the e-mail when the User
				#//// has no name, so shops ended up with customers named "jane@example.com".
				"customer_name": f"{user_doc.first_name} {user_doc.last_name}".strip(),
				"customer_type": "Individual",
				"customer_group": get_shopping_cart_settings().default_customer_group,
				"territory": get_root_of("Territory"),
				#//// Neoffice — see above: without it a multi-currency company priced the cart wrong.
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
		#//// Neoffice — upstream inserts the customer and the contact bare. Wrapped because
		#//// the insert can legitimately fail (a mandatory custom field on Customer added by
		#//// another app): the buyer then falls back to the shop's guest_customer and keeps
		#//// shopping instead of meeting a traceback. Errors are logged with the two-argument
		#//// form (title, message).
		#//// TO REVIEW: one comment inside is in French (RULE #00).
		try:
			customer.insert(ignore_permissions=True)

			# Only create a contact when the e-mail is a valid one
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

#//// Neoffice — signature re-indented to tabs; the guest handling below is ours.
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

	#//// Neoffice — added. For a guest the party is a plain dict (see get_party), which
	#//// has no .doctype/.name — upstream's filters raised an AttributeError on the very
	#//// first cart render of an anonymous visitor.
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
		#//// Neoffice — added. get_address_display reads the Address; a Website User has no
		#//// permission on the addresses of the shop's guest customer, and one such address
		#//// made the whole cart page 403. An address the caller may not read is skipped,
		#//// not fatal.
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

#//// Neoffice — added helper (6d4eca593f, 2025-12-12). Upstream never re-checks a
#//// rule against the address: the buyer picked "Swiss Post", then changed the
#//// country, and the order failed at the payment step with ERPNext's own error.
def _is_shipping_rule_valid_for_country(shipping_rule_name, country):
	"""Check if a shipping rule is valid for the given country"""
	if not shipping_rule_name or not country:
		return True

	# Check if the shipping rule has the country in its list
	sr_country = frappe.qb.DocType("Shipping Rule Country")
	query = (
		frappe.qb.from_(sr_country)
		.select(sr_country.country)
		.where(sr_country.parent == shipping_rule_name)
		.where(sr_country.country == country)
	)
	result = query.run()
	return len(result) > 0


#//// Neoffice — rewritten. ▼▼▼ Upstream auto-selects the first applicable rule and
#//// applies it. Three differences:
#////   · a cart made only of gift cards carries no shipping at all — a card is
#////     e-mailed (3bc2d836f1, 2025-02-11);
#////   · nothing is auto-selected: the buyer chooses at the checkout step, otherwise
#////     the cart showed a shipping charge before an address was even known;
#////   · a rule that raises "not within the range" (weight/value outside its bands)
#////     is dropped and the cart keeps working, instead of 500-ing the page. Any
#////     other exception is re-raised. ▲▲▲
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

	#//// Neoffice — see the block above.
	# Don't auto-apply shipping rules on initial load
	# Let the user select them on checkout
	if not quotation.shipping_rule:
		# Just calculate totals without shipping
		#//// Neoffice — nothing is auto-selected: the buyer picks a shipping method at the
		#//// checkout step (see the block marker on _apply_shipping_rule above).
		quotation.run_method("calculate_taxes_and_totals")
		return

	#//// Neoffice — see the block above (a rule out of range must not break the cart).
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

#//// Neoffice — added helpers (no upstream equivalent), used by get_shipping_rules
#//// below to keep an inapplicable rule off the checkout. See the marker there.
def _get_cart_net_weight(quotation):
	"""Total net weight of the cart, in the company's weight unit."""
	total_weight = flt(quotation.get("total_net_weight"))
	if total_weight:
		return total_weight

	#//// total_net_weight is only filled once calculate_taxes_and_totals has run over
	#//// rows that carry a weight; a cart read straight from the database may have
	#//// neither, so the weight is rebuilt from the lines and, failing that, from the Item.
	for item in (quotation.get("items") or []):
		if item.get("total_weight"):
			total_weight += flt(item.total_weight)
			continue
		weight_per_unit = flt(item.get("weight_per_unit"))
		if not weight_per_unit and item.get("item_code"):
			weight_per_unit = flt(frappe.get_cached_value("Item", item.item_code, "weight_per_unit"))
		total_weight += weight_per_unit * flt(item.qty)

	return total_weight


#//// Neoffice — added helper (no upstream equivalent). See the marker in
#//// get_shipping_rules below.
def _shipping_rule_covers_cart(rule_name, quotation):
	"""Whether this cart falls inside one of the rule's condition bands."""
	try:
		rule = frappe.get_cached_doc("Shipping Rule", rule_name)

		#//// A fixed charge has no band: it always applies.
		if rule.calculate_based_on == "Fixed":
			return True

		#//// "Multiple Constraints" is our own ERPNext mode: the amount comes out of a 3D
		#//// packing pass (py3dbp) that is far too expensive to run once per rule while
		#//// merely listing them. The rule is offered and ShippingRule.apply() has the last
		#//// word — the same contract as before this filter existed.
		if rule.calculate_based_on == "Multiple Constraints":
			return True

		if rule.calculate_based_on == "Net Weight":
			value = _get_cart_net_weight(quotation)
		else:
			value = flt(quotation.get("base_net_total"))

		conditions = rule.get("conditions") or []
		if not conditions:
			#//// A Net Total / Net Weight rule with no band cannot price anything: ERPNext
			#//// throws "No conditions defined for the shipping rule" the moment it is applied.
			return False

		#//// Same comparison as ShippingRule.get_shipping_amount_from_rules(): an empty
		#//// to_value means "and above".
		for condition in conditions:
			if not condition.to_value or (flt(condition.from_value) <= flt(value) <= flt(condition.to_value)):
				return True

		return False
	except Exception:
		#//// Fail open, as before: a rule we cannot read is offered and apply() decides.
		frappe.log_error("Cart: could not check a shipping rule", frappe.get_traceback())
		return True


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
			#//// Neoffice — upstream returns every rule whose country list covers the shipping
			#//// address, applicable or not, so the buyer picked one at the checkout and only
			#//// found out at the payment step that it charges nothing / does not cover their
			#//// cart (6d4eca593f, 2025-12-12). ▼▼▼
			#//// The filter that commit meant to write never ran: `applicable` was hardcoded to
			#//// True and the conditions loop was a bare `pass`, so every rule came back and the
			#//// cart weight was computed for nothing. It is implemented for real here — a rule
			#//// is offered only when the cart falls inside one of its Shipping Rule Condition
			#//// bands, read on the axis the rule itself declares (calculate_based_on), with the
			#//// same comparison ShippingRule.get_shipping_amount_from_rules() uses, so what the
			#//// checkout offers is what will actually apply. ▲▲▲
			all_shipping_rules = [x[0] for x in result]
			shipping_rules = [
				rule_name for rule_name in all_shipping_rules
				if _shipping_rule_covers_cart(rule_name, quotation)
			]

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
#//// Neoffice — added endpoint, and it REPLACES upstream's apply_coupon_code /
#//// remove_coupon_code pair at this position (ours live further down, returning the
#//// updated quotation). The checkout needs the customer type and name to decide
#//// between the private and the company form (48e2708353, 2025-03-13).
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


#//// Neoffice — added endpoint: the buyer edits their name / individual-vs-company on
#//// the checkout (48e2708353, 2025-03-13). ▼▼▼
#//// It used to end on rename_doc("Customer", …, force=True, ignore_permissions=True)
#//// with a name the CALLER supplies, guarded only by the quotation being the caller's
#//// own cart. A portal user could therefore rename their Customer record to anything:
#//// force=True drops the doctype's allow_rename check and the permission check, and a
#//// Customer rename cascades through every document that links it — quotations, orders,
#//// invoices, payments, GL entries — plus its Contacts, Addresses and Portal Users.
#//// Renaming is a desk operation, never a checkout one.
#//// What the checkout actually needs is the DISPLAYED name, which is `customer_name`:
#//// ERPNext keeps `name` and `customer_name` apart on purpose (editing a customer in
#//// the desk changes customer_name and leaves the record id alone), the portal reads
#//// doc.customer_name everywhere (order.html, checkout.html), and get_customer_info()
#//// below returns customer_name too. So the field is written, the address titles that
#//// display it are refreshed, the cart quotation's own fetched copy is refreshed — and
#//// no record is renamed. ▲▲▲
@frappe.whitelist()
def update_customer_info(customer_name=None, customer_type=None):
	"""Update customer information and related addresses"""
	try:
		quotation = get_cart_quotation().get('doc')
		if not quotation or not quotation.party_name:
			#//// Neoffice — the checkout shows this message; it has to be translated.
			return {"success": False, "message": _("No quotation or customer found")}

		customer_doc = frappe.get_doc("Customer", quotation.party_name)
		previous_customer_name = customer_doc.customer_name

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

		#//// Neoffice — the displayed name changed: refresh what copies it. The addresses
		#//// carry it in their title, and the cart quotation holds a fetched copy that the
		#//// order page prints — it would otherwise stay stale until the next save. See the
		#//// block marker above: the Customer record itself is NOT renamed.
		if customer_name and customer_name != previous_customer_name:
			for address_name in (quotation.customer_address, quotation.shipping_address_name):
				if address_name:
					address = frappe.get_doc("Address", address_name)
					address.address_title = f"{customer_name} - {address.address_type}"
					address.save(ignore_permissions=True)

			frappe.db.set_value("Quotation", quotation.name, "customer_name", customer_name)

		frappe.db.commit()
		return {
			"success": True,
			#//// Neoffice — translated: the checkout surfaces this string.
			"message": _("Customer information updated successfully")
		}
	except Exception as e:
		frappe.db.rollback()
		#//// Neoffice — the failure is logged with its traceback and the browser gets a
		#//// generic sentence: str(e) hands a raw exception message to the shop's visitors.
		frappe.log_error("Cart: customer update failed", frappe.get_traceback())
		return {
			"success": False,
			"message": _("Could not update the customer details")
		}

#//// Neoffice — added endpoint: the checkout writes the contact (name, phone,
#//// company) back onto the customer's Contact, which upstream only lets the desk do
#//// (48e2708353, 2025-03-13; is_primary_mobile_no rather than is_primary_phone,
#//// 74403819fc, 2025-11-27 — a mobile number written to the phone field never showed
#//// on the portal).
@frappe.whitelist()
def update_contact_info(first_name, last_name, email=None, phone=None, company_name=None):
	"""Update contact information from checkout page"""
	if not frappe.session.user:
		#//// Neoffice — translated: every message of this endpoint is shown by the checkout.
		return {
			"success": False,
			"message": _("User not logged in")
		}

	#//// Neoffice — see update_contact_info above.
	try:
		# Get current quotation
		quotation = get_cart_quotation().get('doc')
		if not quotation:
			#//// Neoffice — translated, see the guard at the top of this endpoint.
			return {
				"success": False,
				"message": _("No active quotation found")
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

		#//// Neoffice — the contact written from the checkout also carries the billing
		#//// address and is saved with ignore_mandatory, because a shop's Contact often
		#//// has mandatory custom fields the buyer is never shown; the quotation is then
		#//// re-pointed at it, otherwise the order kept a contact that no longer matches
		#//// what the buyer typed (48e2708353, 2025-03-13; 74403819fc, 2025-11-27).
		# Set billing address
		if quotation.customer_address:
			contact.address = quotation.customer_address

		#//// Neoffice — ignore_mandatory: a shop's Contact often carries mandatory custom
		#//// fields the buyer is never shown, and the save then failed silently.
		contact.flags.ignore_mandatory = True
		contact.save(ignore_permissions=True)

		#//// Neoffice — the quotation is re-pointed at the contact just written, otherwise
		#//// the order kept a contact that no longer matches what the buyer typed.
		# Update quotation's contact_person
		quotation.contact_person = contact.name
		quotation.save(ignore_permissions=True)

		#//// Neoffice — the checkout reads this shape (success/message) rather than a
		#//// document; see update_contact_info above. The message is translated because the
		#//// checkout prints it.
		return {
			"success": True,
			"message": _("Contact information updated successfully")
		}

	#//// Neoffice — the checkout must not break on a contact it could not save: the
	#//// failure is reported in the same success/message shape and the buyer keeps
	#//// going (48e2708353, 2025-03-13). ▼▼▼
	#//// It used to return str(e) and log nothing: the shop's visitors were shown a raw
	#//// exception message (a mandatory field name, a doctype, a SQL fragment) while the
	#//// only trace of the failure — the traceback — was thrown away, so nobody could tell
	#//// afterwards WHY a checkout had failed. The traceback now goes to Error Log with the
	#//// two-argument form (title ≤ 140 chars, message), and the buyer gets one translated
	#//// sentence. The JSON shape the checkout reads is unchanged. ▲▲▲
	except Exception:
		frappe.log_error("Cart: contact update failed", frappe.get_traceback())
		return {
			"success": False,
			"message": _("Could not update the contact details")
		}

@frappe.whitelist(allow_guest=True)
def apply_coupon_code(applied_code, applied_referral_sales_partner):
    quotation = True

    if not applied_code:
        frappe.throw(_("Please enter a coupon code"))

    coupon_list = frappe.get_all("Coupon Code", filters={"coupon_code": applied_code})
    #//// Neoffice — the checkout re-applies a coupon it had to remove for a
    #//// moment (shipping rule, quantity change), and what the quotation holds
    #//// is the document name, not the code a customer types. Fall back to it.
    if not coupon_list and frappe.db.exists("Coupon Code", applied_code):
        coupon_list = [frappe._dict(name=applied_code)]
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

#//// Neoffice — upstream: @frappe.whitelist(). Opened to guests with the guest cart;
#//// the quotation is resolved from the session, never from an argument. The body
#//// below also clears the gift-card state (see the marker inside).
@frappe.whitelist(allow_guest=True)
def remove_coupon_code():
	quotation = _get_cart_quotation()
	#//// Neoffice — upstream's remove_coupon_code clears coupon_code and
	#//// referral_sales_partner. Ours must also drop the gift-card state (the coupon, its
	#//// original amount and the discount it applied), otherwise removing a gift card
	#//// left the discount on the cart and the buyer paid nothing (618eedfdb8,
	#//// 2025-03-24; 1fe57465ee, 2026-09-03).
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
	#//// Neoffice — upstream returns None. The checkout renders the summary from the
	#//// returned document, so returning nothing left the coupon row on screen after it
	#//// was removed (b370403e2d, 2026-05-20 "loyalty and coupon endpoints return the
	#//// updated quotation").
	# Return the updated quotation doc so the checkout JS can refresh the
	# order summary (drop the coupon row).
	return quotation

#//// Neoffice — added endpoint: re-renders the coupon block after a change, so the
#//// cart does not reload. allow_guest because the cart page is public; it reads only
#//// the caller's own quotation.
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

#//// Neoffice — added endpoint: the loyalty block, with the balance rounded DOWN to a
#//// multiple of ten because a programme redeems in tens and the buyer was offered a
#//// number they could not spend (3bc2d836f1, 2025-02-11).
#//// Re-indented with tabs: it came in with four-space indentation while cart.py —
#//// upstream included — is tab-indented. Whitespace only, no behaviour change.
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

#//// Neoffice — added endpoint (replaces upstream's remove_coupon_code at this
#//// position). Spends points on the cart: checks the balance, caps the value at the
#//// cart total, books the negative charge line and writes the Loyalty Point Entry so
#//// the balance is really held while the order is being paid (3bc2d836f1,
#//// 2025-02-11). It returns the updated quotation for the same reason as
#//// remove_coupon_code above (b370403e2d, 2026-05-20).
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

	#//// Neoffice — see apply_loyalty_points above (b370403e2d, 2026-05-20).
	# Return the updated quotation doc — the checkout JS feeds it to
	# updateOrderSummaryFromDoc() to render the loyalty discount row.
	return quotation

#//// Neoffice — added endpoint: gives the points back, drops the charge line and
#//// forces a full recalculation — symmetric with apply_loyalty_points, which is the
#//// part that was missing when the totals kept the discount after the points were
#//// removed (b370403e2d, 2026-05-20).
@frappe.whitelist(allow_guest=True)
def remove_loyalty_points():
	quotation = _get_cart_quotation()
	
	#//// Neoffice — the Loyalty Point Entry written when the points were spent has to be
	#//// deleted, not just zeroed: it holds the customer's balance down (3bc2d836f1,
	#//// 2025-02-11).
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

	# Force a full recalculation so rounded_total / grand_total drop the
	# loyalty discount — symmetric with apply_loyalty_points above.
	quotation.calculate_taxes_and_totals()

	#//// Neoffice — saved with ignore_permissions because a guest checkout writes its own
	#//// cart, and the updated document is returned so the checkout can redraw the
	#//// summary without a reload (b370403e2d, 2026-05-20).
	quotation.flags.ignore_permissions = True
	quotation.save()

	#//// Neoffice — upstream returns None here too (b370403e2d, 2026-05-20).
	# Return the updated quotation doc so the checkout JS can refresh the
	# order summary (drop the loyalty row).
	return quotation

@frappe.whitelist(allow_guest=True)
def is_gift_card_item(item_code):
	"""Check if an item is a gift card"""
	try:
		website_item = frappe.get_cached_doc("Website Item", {"item_code": item_code})
		return website_item.is_gift_card if website_item else False
	except frappe.DoesNotExistError:
		# If Website Item doesn't exist, it's not a gift card
		return False


#//// Neoffice — added endpoint. The checkout asked "is this a gift card?" one
#//// item at a time, awaiting each round trip before starting the next: a cart
#//// of six items meant six chained requests just to decide which step comes
#//// after the address. One query answers for the whole cart.
@frappe.whitelist(allow_guest=True)
def are_gift_card_items(item_codes):
	"""Map of item_code -> is_gift_card for several items at once."""
	if isinstance(item_codes, str):
		item_codes = frappe.parse_json(item_codes)
	if not item_codes:
		return {}

	# Unique codes, and never trust the browser on the size of the list.
	item_codes = list({c for c in item_codes if c})[:200]
	rows = frappe.get_all(
		"Website Item",
		filters={"item_code": ["in", item_codes]},
		fields=["item_code", "is_gift_card"],
	)
	found = {r.item_code: bool(r.is_gift_card) for r in rows}
	# An item with no Website Item is not a gift card, as above.
	return {code: found.get(code, False) for code in item_codes}

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
					base_coupon_code = gift_card_data.get("code") if gift_card_data else None

					# Generate unique coupon_code for each quantity
					# If qty > 1, append index to make it unique
					if cint(item.qty) > 1 and base_coupon_code:
						coupon_code = f"{base_coupon_code}-{i+1}"
					elif not base_coupon_code:
						# Generate a random unique code if none provided
						import random
						import string
						coupon_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))
					else:
						coupon_code = base_coupon_code

					# Build unique coupon_name with index when qty > 1
					if cint(item.qty) > 1:
						coupon_name = _("Gift card {0} - {1} - {2} ({3}/{4})").format(
							format_currency_value(item.rate, currency=sales_invoice.currency),
							sales_invoice.customer,
							coupon_code,
							i + 1,
							cint(item.qty)
						)
					else:
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


#//// Neoffice — added helper (a9615e2771, 2026-08-03 "retirer un morceau d'un sejour
#//// emporte le reste, au bon moment"). A booking sold by neoffice_theme is one
#//// product made of several cart lines (the stay, its tourist tax, its options);
#//// removing one line has to remove the others, and it has to be decided HERE —
#//// just before webshop decides whether to delete the draft quotation. The import is
#//// optional: a shop without the booking module sees no difference.
#//// TO REVIEW: the docstring is in French (RULE #00).
def _drop_booking_companions(quotation, removed_item, remaining):
	"""Les lignes qui ne survivent pas au retrait d'un séjour.

	Le module de réservation de neoffice_theme vend une prestation d'un bloc :
	le séjour, sa taxe de séjour, ses options. Retirer un morceau doit emporter
	le reste — et cela doit se décider ICI, dans le même geste, parce que c'est
	juste après que webshop choisit de supprimer ou non son brouillon. Fait plus
	tard, la taxe reste seule au panier et le devis vide survit.

	Silencieux si le module n'est pas installé : une boutique sans réservation
	ne voit aucune différence.
	"""
	try:
		from neoffice_theme.booking.extras import companions_of_a_removed_line
	except ImportError:
		return remaining
	try:
		return companions_of_a_removed_line(quotation, removed_item, remaining)
	except Exception:
		frappe.log_error("Booking: could not clean the cart after removing an item",
			frappe.get_traceback())
		return remaining
