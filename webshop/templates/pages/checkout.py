import frappe
import json
from frappe import _
from frappe.utils import flt, get_link_to_form
from webshop.webshop.utils.utils import format_currency_value
from webshop.webshop.shopping_cart.cart import get_cart_quotation, get_party, get_address_docs, apply_shipping_rule, _get_cart_quotation
from webshop.controllers.payment_handler import PaymentHandler
from webshop.webshop.utils.utils import get_gateway_configuration
from erpnext.setup.utils import get_exchange_rate
from erpnext.stock.get_item_details import get_conversion_factor
from erpnext.accounts.doctype.shipping_rule.shipping_rule import ShippingRule

no_cache = 1

#//// Neoffice — les libellés que les dialogues de Frappe posent eux-mêmes.
#//// Ils passent par `__()` côté navigateur, donc par un dictionnaire que la
#//// page publique ne reçoit jamais : ils s'affichaient en anglais au milieu
#//// d'un tunnel francophone. On les sème dans le gabarit.
_LIBELLES_DIALOGUES = (
	"Yes", "No", "Close", "Cancel", "Confirm", "Error", "Message", "Not permitted",
	#//// Neoffice — the order summary is rebuilt in JS after every change, so
	#//// its labels need to travel to the page like the dialog ones.
	"{0} items", "Subtotal excl. tax ({0} items)",
	#//// Neoffice — failures now speak to the shopper instead of dying in
	#//// the console, so their wording has to travel too.
	"Something went wrong. Please try again.",
	"The quantity could not be updated. Please try again.",
	"The server is taking too long to answer. Please check your connection and try again.",
	"Payment methods could not be loaded. Please try again.",
	#//// Neoffice — address book, rendered in JS.
	"New address", "Default", "Delivery",
	"This address could not be selected. Please try again.",
	#//// Neoffice — the terms line of an intent-engine tile is built in JS
	#//// (wrapWithTerms), so its words travel through here like the rest. Without
	#//// them the shopper read « I accept the conditions générales » — half
	#//// English, in the middle of a French checkout, right above the button that
	#//// takes their money. Seen on the Payrexx tiles, 31.08.2026.
	"I accept the", "terms and conditions", "Continue to payment",
)


#//// Neoffice — added helper (no upstream equivalent).
#////
#//// Sends an anonymous visitor to the sign-in page when the site they are on is
#//// flagged b2b_only. Returns silently everywhere else, so a fleet without
#//// Website Profiles — or a plain B2C site — behaves exactly as before.
def _exiger_connexion_sur_site_professionnel():
	if frappe.session.user != "Guest":
		return

	profile = getattr(frappe.local, "website_profile_doc", None)
	if not profile or not profile.get("b2b_only"):
		return

	#//// Vers /login, jamais vers /app: un client portail n'a pas le desk.
	frappe.local.flags.redirect_location = "/login?redirect-to=/checkout"
	raise frappe.Redirect


def get_context(context):
	"""Context for the payment page"""
	#//// Neoffice multi-site — un site réservé aux professionnels exige d'être
	#//// connecté pour COMMANDER.
	#////
	#//// Le contrôle existant (check_website_profile_login) ne porte que sur la
	#//// connexion, et exempte explicitement Guest: un visiteur anonyme pouvait
	#//// donc remplir un panier sur le domaine B2B, atteindre ce tunnel et le
	#//// dérouler — aux tarifs réservés aux revendeurs. Vérifié sur osiris.
	#////
	#//// Naviguer reste permis (le catalogue sert de vitrine); c'est la commande
	#//// qui demande un compte approuvé.
	_exiger_connexion_sur_site_professionnel()

	#//// Neoffice — Frappe derives context.title from the route when nobody
	#//// sets it, and never translates it; themes print it as the visible
	#//// page heading, so the page read "checkout".
	#////
	#//// Deliberately NOT _("Checkout"): that string is shared with the cart
	#//// button, where fr renders it "Paiement" — which is right for a button but
	#//// made the page heading and the breadcrumb read "Paiement" while the
	#//// shopper stood on step 2, next to a step 4 also labelled "Paiement".
	context.title = _("Your order")
	context.js_messages = frappe.as_json({m: _(m) for m in _LIBELLES_DIALOGUES})
	#//// Neoffice — the one thing client-side currency formatting cannot know
	#//// on its own. Seeded once instead of being re-asked through a round trip
	#//// for every amount displayed.
	#////
	#//// Same precedence as utils.format_currency_value: a shop that answered
	#//// the question ("Yes" or "No") decides on its own, and only an unset
	#//// shop setting defers to the ERPNext global. Writing this as a plain
	#//// `or` would be wrong — an explicit "No" would still let the global
	#//// hide the symbol.
	_shop_hide = frappe.db.get_single_value("Webshop Settings", "hide_currency_symbol_in_shop")
	if _shop_hide:
		context.hide_currency_symbol = _shop_hide == "Yes"
	else:
		context.hide_currency_symbol = frappe.defaults.get_global_default("hide_currency_symbol") == "Yes"
	from webshop.webshop.shopping_cart.guest_cart import check_and_merge_guest_cart
	
	# Check and merge guest cart if needed
	check_and_merge_guest_cart()
	
	# Check shop settings first
	settings = frappe.get_doc("Webshop Settings")
	
	# For Guest users, try to get their cart from session
	if frappe.session.user == "Guest":
		guest_session_id = frappe.request.cookies.get('guest_session_id')
		quotation = None
		
		if guest_session_id:
			# Try to find guest quotation
			existing_quotation = frappe.db.get_value(
				"Quotation",
				{
					"guest_session_id": guest_session_id,
					"docstatus": 0,
					"status": "Draft",
					"order_type": "Shopping Cart"
				},
				"name"
			)
			
			if existing_quotation:
				quotation = frappe.get_doc("Quotation", existing_quotation)
		
		# If no quotation or empty cart for guest, redirect
		if not quotation or not quotation.get('items'):
			frappe.local.flags.redirect_location = '/cart'
			raise frappe.Redirect
	else:
		# For logged in users, get cart quotation normally
		quotation = _get_cart_quotation()
		
		# If quotation is not saved or None, check cookies
		if not quotation or quotation.is_new():
			quotation_name = frappe.request.cookies.get('quotation_name')
			guest_session_id = frappe.request.cookies.get('guest_session_id')
			
			if quotation_name and guest_session_id:
				# Check if quotation exists with correct guest_session_id
				existing_quotation = frappe.db.get_value(
					"Quotation",
					{
						"name": quotation_name,
						"guest_session_id": guest_session_id,
						"docstatus": 0,
						"status": "Draft"
					},
					["name", "guest_session_id"],
					as_dict=True
				)
				
				if existing_quotation:
					quotation = frappe.get_doc("Quotation", existing_quotation.name)
		
		if not quotation or not quotation.get('items'):
			frappe.local.flags.redirect_location = '/all-products'
			raise frappe.Redirect
	
	# Check if B2B checkout is enabled
	if settings.activate_b2b_checkout:
		# Get cart information to check if it's a B2B customer
		cart_info = get_cart_quotation()
		
		# If it's a B2B customer, redirect to B2B checkout
		if cart_info.get("is_b2b_customer"):
			frappe.local.flags.redirect_location = '/checkout_b2b'
			raise frappe.Redirect
	
	# Continue with the rest of the code if a quotation exists
	if not frappe.db.get_single_value("Webshop Settings", "enable_checkout") or \
	   not frappe.db.get_single_value("Webshop Settings", "enable_checkout_page"):
		frappe.throw(_("Checkout is disabled. Please enable it in Webshop Settings."))

	context.no_cache = 1
	
	# Get cart details using the same function as cart.py
	try:
		cart_quotation = get_cart_quotation()
	except Exception as e:
		# If there's an error with shipping rules, log it but continue
		error_message = str(e)
		if "Shipping Rule Not Applicable" in error_message or "not within the range" in error_message:
			frappe.log_error(f"Shipping rule error on checkout: {error_message}", "Checkout")
			# Get cart without applying shipping rules
			quotation = _get_cart_quotation()
			cart_quotation = {
				'doc': quotation,
				'cart_settings': frappe.get_cached_doc("Webshop Settings"),
				'shipping_addresses': get_address_docs(party=get_party()),
				'billing_addresses': get_address_docs(party=get_party()),
				'shipping_rules': []
			}
		else:
			# Re-raise other errors
			raise
	
	context.update(cart_quotation)
	
	# The quotation document is in cart_quotation['doc']
	quotation = cart_quotation.get('doc', {})
	
	# Get loyalty program details if available
	if quotation.get('loyalty_program'):
		loyalty_program = frappe.get_doc('Loyalty Program', quotation.loyalty_program)
		context.conversion_factor = loyalty_program.conversion_factor
	else:
		context.conversion_factor = 0
	
	# Get cart items from the quotation
	context.cart_items = quotation.get('items', [])
	
	# Add cart currency from price list
	context.cart_currency = quotation.get('price_list_currency')
	
	# Calculate totals from the quotation document
	context.subtotal = quotation.get('total', 0)
	context.tax_amount = quotation.get('total_taxes_and_charges', 0)
	context.shipping_amount = quotation.get('shipping_fee', 0)
	context.total = quotation.get('grand_total', 0)
	
	# Get CGV from Webshop Settings
	if cart_quotation.get('cart_settings') and cart_quotation['cart_settings'].get('checkout_cgv'):
		cgv_terms = cart_quotation['cart_settings'].checkout_cgv
		context.cgv_tc_name = cgv_terms
		context.cgv_terms = frappe.db.get_value("Terms and Conditions", cgv_terms, "terms")
	
	# Get customer information
	customer = None
	contact_info_set = False
	
	if quotation.get('party_name'):
		customer = frappe.get_doc('Customer', quotation.party_name)
		
		# Get primary contact
		if customer.customer_primary_contact:
			contact = frappe.get_doc('Contact', customer.customer_primary_contact)
			context.contact_name = contact.name
			context.contact_first_name = contact.first_name
			context.contact_last_name = contact.last_name
			context.contact_email = contact.email_id
			context.contact_phone = contact.mobile_no or contact.phone
			contact_info_set = True
	
	# If no primary contact found, try to get contact info from quotation's contact_person
	if not contact_info_set and quotation.get('contact_person'):
		contact = frappe.get_doc('Contact', quotation.get('contact_person'))
		if contact:
			context.contact_name = contact.name
			context.contact_first_name = contact.first_name
			context.contact_last_name = contact.last_name or ''  
			context.contact_email = contact.email_id
			context.contact_phone = contact.mobile_no or contact.phone
			contact_info_set = True
			# Update customer
			try:
				customer = frappe.get_doc('Customer', quotation.party_name)
				if contact and contact.name:
					customer.customer_primary_contact = contact.name
					
				# Update primary address if needed
				if quotation.get('customer_address'):
					customer.customer_primary_address = quotation.customer_address
				
				customer.save(ignore_permissions=True)
				# Reload document to check changes
				customer.reload()
				frappe.db.commit()

			except Exception as e:
				frappe.log_error(f"Error updating customer", str(e))
	
	# Get billing address
	if quotation.get('customer_address'):
		billing_address = frappe.get_doc('Address', quotation.customer_address)
		if billing_address:
			# Only set company name if customer type is Company
			if customer and customer.customer_type == "Company":
				context.billing_company = billing_address.address_title
			else:
				context.billing_company = ""
				
			context.billing_address_1 = billing_address.address_line1
			context.billing_house_number = billing_address.get("custom_house_number")
			context.billing_address_2 = billing_address.address_line2
			context.billing_city = billing_address.city
			context.billing_state = billing_address.state
			context.billing_country = billing_address.country
			context.billing_postcode = billing_address.pincode
			# Use customer's contact info if address doesn't have it
			context.billing_phone = billing_address.phone or (customer.mobile_no if customer else '')
			context.billing_email = billing_address.email_id or (customer.email_id if customer else '')

	# Set default country if not already set
	if not context.get('billing_country'):
		context.billing_country = frappe.db.get_single_value("System Settings", "country") or "Switzerland"
	if not context.get('shipping_country'):
		context.shipping_country = context.billing_country

	# Get shipping address
	if quotation.get('shipping_address_name'):
		shipping_address = frappe.get_doc('Address', quotation.shipping_address_name)
		if shipping_address:
			# Only set company name if customer type is Company
			if customer and customer.customer_type == "Company":
				context.shipping_company = shipping_address.address_title
			else:
				context.shipping_company = ""
				
			context.shipping_address_1 = shipping_address.address_line1
			context.shipping_house_number = shipping_address.get("custom_house_number")
			context.shipping_address_2 = shipping_address.address_line2
			context.shipping_city = shipping_address.city
			context.shipping_state = shipping_address.state
			context.shipping_country = shipping_address.country
			context.shipping_postcode = shipping_address.pincode
			# Use customer's contact info if address doesn't have it
			context.shipping_phone = shipping_address.phone or (customer.mobile_no if customer else '')
			context.shipping_email = shipping_address.email_id or (customer.email_id if customer else '')
	
	# Check for the loyalty program of the customer
	customer_loyalty_program = frappe.db.get_value(
		"Customer", context.doc.customer_name, "loyalty_program"
	)
	if customer_loyalty_program:
		from erpnext.accounts.doctype.loyalty_program.loyalty_program import (
			get_loyalty_program_details_with_points,
		)
		import math

		loyalty_program_details = get_loyalty_program_details_with_points(
			context.doc.customer_name, customer_loyalty_program
		)

		# Get the raw points
		available_loyalty_points = loyalty_program_details.get("loyalty_points")
		conversion_factor = loyalty_program_details.get("conversion_factor")
		
		# Round down loyalty points to the nearest 10
		rounded_loyalty_points = math.floor(available_loyalty_points / 10) * 10
		
		# Calculate the equivalent value based on rounded points
		equivalent_value = rounded_loyalty_points * conversion_factor
		
		# Format the money value
		formatted_value = format_currency_value(equivalent_value, currency=quotation.currency)
		
		# Update the loyalty_program_details to use the rounded points
		loyalty_program_details["loyalty_points"] = rounded_loyalty_points
		
		# Update the context with properly rounded values
		context.update({
			"loyalty_points": rounded_loyalty_points,  # This is important - update ALL instances
			"available_loyalty_points": rounded_loyalty_points,
			"conversion_factor": conversion_factor,
			"loyalty_points_value": formatted_value,
			"loyalty_program_details": loyalty_program_details  # Update with modified details
		})

	# Add loyalty points to earn information
	from webshop.webshop.utils.loyalty_cart import get_loyalty_points_for_cart
	loyalty_info = get_loyalty_points_for_cart(quotation)
	if loyalty_info:
		context.loyalty_cart_info = loyalty_info

	return context

@frappe.whitelist()
def get_shipping_methods():
	"""Get available shipping methods based on the cart items and shipping/billing address"""
	quotation = _get_cart_quotation()
	if not quotation:
		return []

	# Get form data
	ship_to_different = frappe.parse_json(frappe.form_dict.get('ship_to_different', 'false'))
	shipping_country = frappe.form_dict.get('shipping_country')
	billing_country = frappe.form_dict.get('billing_country')
	
	# Determine country to use
	country = shipping_country if ship_to_different else billing_country
	
	if not country:
		# Fallback to existing addresses if no country in form
		if quotation.shipping_address_name:
			shipping_address = frappe.get_doc("Address", quotation.shipping_address_name)
			country = shipping_address.country
		elif quotation.customer_address:
			billing_address = frappe.get_doc("Address", quotation.customer_address)
			country = billing_address.country
	
	if not country:
		return []

	cart_total = quotation.net_total
	cart_weight = quotation.total_net_weight if hasattr(quotation, 'total_net_weight') else 0
	
	# Get all enabled shipping rules
	shipping_rules = frappe.get_all(
		"Shipping Rule",
		fields=["name", "label", "shipping_amount", "disabled", "calculate_based_on", 
			"description", "taxable_account", "tax_is_included", "weight_uom", "dimensions_uom"],
		filters={"disabled": 0, "shipping_rule_type": "Selling"},
	)

	available_methods = []
	for rule in shipping_rules:
		# Get countries for this rule
		countries = frappe.get_all(
			"Shipping Rule Country",
			fields=["country"],
			filters={"parent": rule.name}
		)
		
		# If no country specified or if country is in list
		if not countries or any(c.country == country for c in countries):
			# Calculate shipping amount based on rule type
			shipping_amount = rule.shipping_amount  # Default amount
			
			# If fixed amount, no need to check conditions
			if rule.calculate_based_on == "Fixed":
				pass  # Use the fixed amount by default
			
			# If multiple constraints, use the new logic
			elif rule.calculate_based_on == "Multiple Constraints":
				# Check if units of measure are defined
				if not rule.weight_uom or not rule.dimensions_uom:
					frappe.log_error(
						"Error in shipping rule configuration",
						f"Shipping rule {rule.name} : missing units of measure"
					)
					continue
					
				# Get conditions for this rule, including new constraint fields
				conditions = frappe.get_all(
					"Shipping Rule Condition Multiple Constraints",
					fields=["condition_group", "constraint_type", "min_value", "max_value", "shipping_amount"],
					filters={"parent": rule.name},
					order_by="condition_group, constraint_type"
				)
				
				# Use bin packing algorithm to calculate optimal dimensions
				total_weight = 0
				packing_items = []
				
				# Collect dimensions and weights of items
				for item in quotation.items:
					# Get item document to read dimensions and weight
					item_doc = None
					qty = flt(item.qty or 1)
					
					try:
						item_doc = frappe.get_cached_doc("Item", item.item_code)
					except:
						pass
					
					# Get weight and dimensions from item doc
					if item_doc:
						# Calculate weight and convert to shipping rule UOM
						item_weight = flt(getattr(item_doc, 'weight_per_unit', 0) or 0) * qty
						item_weight_uom = getattr(item_doc, 'weight_uom', None) or ''
						
						# Convert weight to shipping rule UOM if different
						if item_weight_uom and rule.weight_uom and item_weight_uom != rule.weight_uom:
							try:
								item_weight = convert_to_uom(item_weight, item_weight_uom, rule.weight_uom)
							except Exception as e:
								frappe.log_error(
									"Error converting weight unit",
									f"Error converting weight unit: {str(e)} for item {item.item_code}"
								)
						
						total_weight += item_weight
						
						# Get dimensions and convert to shipping rule UOM
						item_length = flt(getattr(item_doc, 'length', 0) or 0)
						item_width = flt(getattr(item_doc, 'width', 0) or 0)
						item_height = flt(getattr(item_doc, 'height', 0) or 0)
						item_dim_uom = getattr(item_doc, 'dimension_uom', None) or ''
						
						# Convert dimensions to shipping rule UOM if different
						if item_dim_uom and rule.dimensions_uom and item_dim_uom != rule.dimensions_uom:
							try:
								item_length = convert_to_uom(item_length, item_dim_uom, rule.dimensions_uom)
								item_width = convert_to_uom(item_width, item_dim_uom, rule.dimensions_uom)
								item_height = convert_to_uom(item_height, item_dim_uom, rule.dimensions_uom)
							except Exception as e:
								frappe.log_error(
									"Error calculating shipping rules",
									f"Error converting dimension unit: {str(e)} for item {item.item_code}"
								)
						
						# Add each unit of the item as a distinct item for bin packing
						for i in range(int(qty)):
							packing_items.append({
								"name": f"{item.item_code}_{i}",
								"length": item_length,
								"width": item_width,
								"height": item_height,
								"weight": item_weight / qty
							})
				
				# Calculate optimal packing using ShippingRule's method
				optimal_packing = ShippingRule.calculate_optimal_packing(packing_items)
				
				# Use optimized dimensions for validation
				length = optimal_packing.get("length", 0)
				width = optimal_packing.get("width", 0)
				height = optimal_packing.get("height", 0)
				
				# Group conditions by condition_group
				grouped_conditions = {}
				for condition in conditions:
					group = condition.condition_group
					if group not in grouped_conditions:
						grouped_conditions[group] = {
							"constraints": [],
							"shipping_amount": condition.shipping_amount
						}
					grouped_conditions[group]["constraints"].append(condition)
				
				# Check each condition group
				shipping_amount = 0
				valid_groups = {}
				
				for group, data in grouped_conditions.items():
					# Initialize group if not exists
					if group not in valid_groups:
						valid_groups[group] = {
							"valid": True, 
							"shipping_amount": data["shipping_amount"]
						}
					
					for condition in data["constraints"]:
						# Skip validation if group already invalid
						if not valid_groups[group]["valid"]:
							continue
						
						# Determine the constraint value based on type
						if condition.constraint_type == "Weight":
							constraint_value = total_weight or cart_weight
							constraint_label = _("Weight")
							constraint_uom = rule.weight_uom
						elif condition.constraint_type == "Price":
							constraint_value = cart_total
							constraint_label = _("Price")
							constraint_uom = quotation.currency if hasattr(quotation, 'currency') else ''
						elif condition.constraint_type == "Length":
							constraint_value = length
							constraint_label = _("Length")
							constraint_uom = rule.dimensions_uom
						elif condition.constraint_type == "Width":
							constraint_value = width
							constraint_label = _("Width")
							constraint_uom = rule.dimensions_uom
						elif condition.constraint_type == "Height":
							constraint_value = height
							constraint_label = _("Height")
							constraint_uom = rule.dimensions_uom
						else:
							continue
							
						# Check if value is within constraints
						min_value = flt(condition.min_value) if condition.min_value is not None else 0
						max_value = flt(condition.max_value) if condition.max_value is not None else float('inf')
						
						# Check if value is within constraints
						if not (min_value <= constraint_value <= max_value):
							valid_groups[group]["valid"] = False
							break
					
				# Find the first valid group and apply its shipping amount
				valid_group_found = False
				for group, data in valid_groups.items():
					if data["valid"]:
						shipping_amount = data["shipping_amount"]
						valid_group_found = True
						break
				
				# Si aucun groupe valide n'est trouvé, passer à la règle suivante
				if not valid_group_found:
					continue
				
			# For legacy rules (Net Total and Net Weight)
			else:
				# Get conditions using legacy fields
				conditions = frappe.get_all(
					"Shipping Rule Condition",
					fields=["from_value", "to_value", "shipping_amount"],
					filters={"parent": rule.name},
					order_by="from_value"
				)
				
				if conditions:
					condition_matched = False
					for condition in conditions:
						value = cart_total if rule.calculate_based_on == "Net Total" else cart_weight
						if (value >= flt(condition.from_value) and 
							(not condition.to_value or value <= flt(condition.to_value))):
							shipping_amount = condition.shipping_amount
							condition_matched = True
							break
					# If no condition matches, skip this rule
					if not condition_matched:
						continue
			
			# Calculate the display amount with tax if applicable
			display_amount = shipping_amount
			if rule.taxable_account:
				try:
					# If tax is included, show the gross amount
					if rule.tax_is_included:
						tax_templates = frappe.get_doc("Item Tax Template", rule.taxable_account)
						total_tax_rate = 0
						
						for tax in tax_templates.taxes:
							if tax.tax_rate:
								total_tax_rate += flt(tax.tax_rate)
						
						if total_tax_rate > 0:
							# For display purposes, we show the amount including tax
							display_amount = shipping_amount
					else:
						# If tax is not included, still show the base amount
						display_amount = shipping_amount
				except:
					pass
			
			# Final gate: dry-run the real ERPNext apply() so this list can never
			# diverge from what applying the rule accepts later (the listing math
			# above and ShippingRule.apply compute packing dimensions differently).
			# Free rules (e.g. in-store pickup, Fixed 0.00) are legitimately zero —
			# apply() clears any zero-amount rule, so only dry-run paid ones.
			if flt(shipping_amount):
				try:
					probe = frappe.copy_doc(quotation)
					probe.shipping_rule = rule.name
					# suppress the fork's "not applicable" msgprint during the dry-run
					probe._skip_shipping_rule_notification = True
					frappe.get_doc("Shipping Rule", rule.name).apply(probe)
					if not probe.shipping_rule:
						# the fork's apply() clears the field when constraints don't match
						continue
				except frappe.ValidationError:
					continue
				except Exception:
					pass  # never block the listing on unexpected probe errors

			available_methods.append({
				"name": rule.name,
				"title": rule.label or rule.name,
				"description": rule.description or _("Shipping to {0}").format(country),
				"rate": shipping_amount,
				"display_rate": display_amount,
				"formatted_rate": format_currency_value(display_amount, currency=quotation.currency),
				"calculate_based_on": rule.calculate_based_on,
				"taxable": bool(rule.taxable_account) 
			})
	
	return available_methods

def convert_to_uom(value, from_uom, to_uom):
	"""Convert value from one UOM to another
	
	Args:
		value (float): The value to convert
		from_uom (str): Source UOM
		to_uom (str): Target UOM
	
	Returns:
		float: Converted value
	"""
	# If the value is null or the UOMs are identical, return the value as is
	if not value or not from_uom or not to_uom or from_uom == to_uom:
		return value
	
	# Try direct conversion first
	uom_conversion = frappe.db.get_value(
		"UOM Conversion Factor",
		{"from_uom": from_uom, "to_uom": to_uom},
		"value"
	)
	
	if uom_conversion:
		return flt(value) * flt(uom_conversion)
	
	# Try inverse conversion
	reverse_conversion = frappe.db.get_value(
		"UOM Conversion Factor",
		{"from_uom": to_uom, "to_uom": from_uom},
		"value"
	)
	
	if reverse_conversion:
		return flt(value) / flt(reverse_conversion)
	
	# Method of fallback: use standard conversion factors
	try:
		from_conversion_factor = frappe.get_value("UOM Conversion Detail", 
			{"parent": "UOM", "uom": from_uom}, "conversion_factor") or 1.0
		to_conversion_factor = frappe.get_value("UOM Conversion Detail", 
			{"parent": "UOM", "uom": to_uom}, "conversion_factor") or 1.0
		
		# Convert value
		return flt(value) * flt(from_conversion_factor) / flt(to_conversion_factor)
	except Exception as e:
		frappe.log_error(f"Error converting unit from {from_uom} to {to_uom}: {str(e)}")
		frappe.throw(_("No conversion factor found between {0} and {1}").format(from_uom, to_uom))

@frappe.whitelist()
def update_shipping_method():
	"""Update shipping method and recalculate totals"""
	try:
		shipping_method = frappe.form_dict.get('shipping_method')
		if not shipping_method:
			frappe.throw(_('Please select a shipping method'))
		
		# Apply shipping rule
		apply_shipping_rule(shipping_method)
		
		# Get updated quotation
		cart_info = get_cart_quotation()
		quotation_doc = cart_info.get('doc')
		
		if not quotation_doc:
			frappe.throw(_('Your basket is empty'))
		
		# Calculate totals
		return {
			'success': True,
			'grand_total': quotation_doc.grand_total,
			'total': quotation_doc.total,
			'net_total': quotation_doc.net_total,
			'shipping_amount': quotation_doc.shipping_rule_rate if hasattr(quotation_doc, 'shipping_rule_rate') else 0,
			'taxes': [{
				"description": tax.description, 
				"tax_amount": tax.tax_amount,
				"formatted_tax_amount": format_currency_value(tax.tax_amount, currency=quotation_doc.currency)
			} for tax in quotation_doc.taxes] if quotation_doc.taxes else [],
			'formatted_grand_total': format_currency_value(quotation_doc.grand_total, currency=quotation_doc.currency),
			'formatted_net_total': format_currency_value(quotation_doc.net_total, currency=quotation_doc.currency),
			'formatted_shipping_amount': format_currency_value(quotation_doc.shipping_rule_rate if hasattr(quotation_doc, 'shipping_rule_rate') else 0, currency=quotation_doc.currency)
		}
	except Exception as e:
		frappe.log_error(f"Error updating the shipping method", e)
		return {
			'success': False, 
			'message': _('An error occurred while updating the shipping method. Please try again.')
		}
@frappe.whitelist(allow_guest=True)
def get_shipping_address(user=None):
	"""Get the shipping address for the current user"""
	try:
		# Get customer
		customer = get_party()
		if not customer:
			return None

		# Get all addresses
		addresses = get_address_docs(party=customer)
		
		# Find shipping address
		shipping_address = None
		for address in addresses:
			if address.address_type == "Shipping":
				shipping_address = address
				break
				
		# If no shipping address found but we have addresses, use the first one
		if not shipping_address and addresses:
			shipping_address = addresses[0]
			
		if shipping_address:
			address_dict = shipping_address.as_dict()
			# Add company_name if customer is a company
			if customer.customer_type == "Company":
				address_dict["company_name"] = customer.customer_name
			else:
				address_dict["company_name"] = ""
			return address_dict
			
		return None

	except Exception as e:
		frappe.log_error(f"Error in get_shipping_address", e)
		return None

def _document_a_payer(reference_doctype=None, reference_docname=None):
	"""//// Neoffice — le document qu'on paie n'est pas toujours un panier.

	La boutique paie son panier ; le module de réservation paie une facture
	déjà émise, sans panier du tout. Ces deux fonctions supposaient le panier
	partout — `get_payment_template` allait jusqu'à jeter « Your basket is
	empty » et à écraser la référence que l'appelant venait de passer.

	Sans référence explicite, rien ne change : on prend le panier, comme avant.

	⚠️ Ce helper NE VÉRIFIE AUCUN DROIT. Il rend ce qu'on lui nomme. Tout
	appelant qui accepte une référence venue du navigateur doit avoir vérifié
	avant lui que le visiteur a bien le droit de payer ce document — c'est ce
	que fait `neoffice_theme.booking.checkout` avec `_may_pay`.
	"""
	if reference_doctype and reference_docname:
		return frappe.get_doc(reference_doctype, reference_docname)
	return (get_cart_quotation() or {}).get("doc")


@frappe.whitelist(allow_guest=True)
def get_payment_methods(reference_doctype=None, reference_docname=None):
	"""Get payment methods configured in Webshop Settings"""
	try:
		# 1. Get payment methods from Webshop Settings
		settings = frappe.get_doc("Webshop Settings")
		if not settings.enable_checkout or not settings.payment_methods:
			return {
				"error": True,
				"message": "Online payment is not enabled"
			}

		methods = []
		for webshop_method in settings.payment_methods:
			try:
				# 1. For each method, get Payment Gateway Account
				payment_gateway_account = frappe.get_doc("Payment Gateway Account", webshop_method.payment_gateway_account)
				if not payment_gateway_account:
					continue

				# 2. Get associated Payment Gateway
				payment_gateway = frappe.get_doc("Payment Gateway", payment_gateway_account.payment_gateway)
				if not payment_gateway:
					continue

				# 3. Get gateway settings if specified
				gateway_settings = None
				if payment_gateway.gateway_settings:
					try:
						# The gateway_settings contains the name of the doctype (e.g. "Stripe Settings")
						# But the document itself is named after the gateway_controller (e.g. "Stripe")
						settings_doctype = payment_gateway.gateway_settings  # Ex: "Stripe Settings"
						settings_name = payment_gateway.gateway_controller  # Ex: "Stripe"
						
						
						# Check if document exists
						if frappe.db.exists(settings_doctype, settings_name):
							settings_doc = frappe.get_doc(settings_doctype, settings_name)
							gateway_settings = settings_doc.as_dict()
							
					except Exception as e:
						frappe.log_error(f"Error retrieving settings", e)

				# Get gateway type from name
				gateway_type = payment_gateway.gateway.split('-')[0].split()[0].lower().strip()
				
				#//// Neoffice — ce qu'un client doit lire : « Payrexx », pas
				#//// « Payrexx - CHF - pri ». Le nom d'un compte de passerelle
				#//// porte la devise et parfois un suffixe d'exploitation :
				#//// c'est le nom du DOSSIER, pas celui du moyen de paiement.
				#//// On préfère donc, dans l'ordre : le libellé écrit par le
				#//// commerçant, puis le nom de la PASSERELLE, puis le compte
				#//// faute de mieux. Même règle que la surface de réservation
				#//// (`neoffice_theme.booking.checkout._moyen_lisible`).
				title = (
					payment_gateway_account.checkout_title
					or payment_gateway_account.payment_gateway
					or payment_gateway_account.name
				)
				logo_html = f"<img src='{payment_gateway_account.logo}' alt='{title}' class='payment-logo'>" if payment_gateway_account.logo else ""
				description = payment_gateway_account.checkout_description or ""
				#//// Neoffice — le panier, ou le document nommé par l'appelant.
				quotation_doc = _document_a_payer(reference_doctype, reference_docname)

				# Hide installment-based methods entirely when the cart doesn't reach
				# the smallest configured minimum (all options would be greyed out).
				installments = (gateway_settings or {}).get("installments") or (gateway_settings or {}).get("installment_plans")
				if installments is None and payment_gateway.gateway_settings:
					# Settings doc not resolved above (no gateway_controller) — try the
					# Single doc of the settings doctype, like the payment template does.
					try:
						_sdoc = frappe.get_cached_doc(payment_gateway.gateway_settings)
						installments = [r.as_dict() for r in (_sdoc.get("installment_plans") or _sdoc.get("installments") or [])]
					except Exception:
						installments = []
				installments = installments or []
				if installments and quotation_doc:
					mins = [flt(i.get("min_amount") or i.get("minimum_amount")) for i in installments]
					mins = [m for m in mins if m]
					cart_amount = flt(quotation_doc.get("rounded_total") or quotation_doc.get("grand_total"))
					if mins and len(mins) == len(installments) and cart_amount < min(mins):
						continue
				
				# Utilisation sécurisée de mode_of_payment (sans logging d'erreur)
				mode_of_payment = getattr(webshop_method, 'mode_of_payment', None)
				
				# Utilisation sécurisée de client_configuration (sans logging d'erreur)
				client_configuration = getattr(webshop_method, 'client_configuration', None)
					
				# Check if mode_of_payment attribute exists before trying to access it
				if not mode_of_payment and hasattr(webshop_method, 'payment_terms_template') and webshop_method.payment_terms_template:
					mode_of_payment = webshop_method.payment_terms_template
					
				# Build payment method dictionary with security for missing attributes
				payment_method = {
					"id": payment_gateway_account.name,
					"title": title,
					"description": description,
					"logo": logo_html,
					"is_default": payment_gateway_account.is_default,
					"payment_gateway": payment_gateway.name,
					"payment_gateway_account": payment_gateway_account.name,
					"currency": payment_gateway_account.currency,
					"gateway_type": gateway_type,
					"doc": quotation_doc
				}
				
				# Add conditionally missing attributes
				if mode_of_payment:
					payment_method["mode_of_payment"] = mode_of_payment
					
				if hasattr(webshop_method, 'gateway_settings'):
					payment_method["gateway_settings"] = webshop_method.gateway_settings
					
				if client_configuration:
					payment_method["client_configuration"] = client_configuration
					
				# Add template_path if available
				if hasattr(webshop_method, 'template_path') and webshop_method.template_path:
					payment_method["template_path"] = webshop_method.template_path
				
				methods.append(payment_method)

			except Exception as e:
				frappe.log_error("payment_method_error", f"Error retrieving payment method: {str(e)}")

		return {"error": False, "methods": methods}

	except Exception as e:
		frappe.log_error("payment_methods_global_error", f"Error retrieving payment methods: {str(e)}")
		return {"error": True, "message": str(e)}

@frappe.whitelist(allow_guest=True)
def start_cart_intent(payment_gateway_account: str) -> dict:
	"""//// Neoffice — encaisser le panier par le moteur d'INTENTIONS de `payments`.

	Un second chemin, POSÉ À CÔTÉ du premier et éteint par défaut. Le checkout
	historique — gabarit par passerelle + `window.checkout_manager` — n'est pas
	touché : il tourne en production chez des clients, et une migration d'un
	seul tenant sur des paiements ne se fait pas.

	Ce chemin ne s'emprunte que si la méthode porte `use_payment_intent`. Tant
	que la case est décochée, absolument rien ne change pour elle.

	Pourquoi l'ajouter : les pilotes de `payments` (Payrexx, Wallee, TWINT,
	terminaux) alimentent les Payment Intent, pas les gabarits. Ce que la
	boutique sait faire d'une passerelle dépend donc aujourd'hui de ce qu'on a
	recopié dans son gabarit, au lieu de suivre le pilote. TWINT, par exemple,
	sait rendre un QR à afficher sur place — la boutique l'ignore.

	Rend la même forme que `neoffice_theme.booking.checkout.start_payment` :
	l'écran n'a pas à savoir quelle passerelle il a devant lui.
	"""
	cart = get_cart_quotation()
	devis = (cart or {}).get("doc")
	if not devis:
		frappe.throw(_("Your basket is empty"))

	if not _intent_is_wanted(payment_gateway_account):
		# La méthode n'a pas été basculée : on ne décide pas à sa place.
		return {"action": "legacy"}

	gateway = frappe.db.get_value("Payment Gateway Account", payment_gateway_account, "payment_gateway")
	kind = (gateway or "").split("-")[0].split()[0].strip().lower()
	couple = _intent_binding(kind)
	if not couple:
		return {"action": "legacy"}

	from payments.api.intent import create_intent

	#//// Neoffice — l'intention porte sur la PAYMENT REQUEST, jamais sur le
	#//// devis. C'est la Payment Request que les pages de retour de `payments`
	#//// savent conclure (`payments/www/{wallee,payrexx}/success.py` : elles
	#//// testent `reference_doctype == "Payment Request"`), et c'est elle qui
	#//// transforme le panier en commande. Une intention accrochée à la
	#//// Quotation encaisserait sans que personne ne crée la commande — le
	#//// client paierait pour rien. On réutilise la fabrique de webshop, qui
	#//// est idempotente : deux clics sur le même panier ne font qu'une demande.
	from webshop.controllers.payment_handler import PaymentHandler

	# On NOMME le devis. Sans lui, la fabrique re-résout le panier de son côté
	# (`_get_cart_quotation`) et peut tomber sur un autre devis — vécu le
	# 2026-08-24 : un devis vide, refusé pour « items » manquants, et le chemin
	# retombait en `legacy` sans que personne ne comprenne pourquoi.
	demande = PaymentHandler().create_payment_request(
		quotation_id=devis.name,
		payment_gateway=gateway,
		idempotency_token="intent-{0}-{1}".format(devis.name, payment_gateway_account),
	)
	if not demande or demande.get("status") != "success" or not demande.get("payment_request_id"):
		frappe.log_error(
			"Webshop: pas de Payment Request pour l'intention",
			"devis={0} methode={1} retour={2}".format(devis.name, payment_gateway_account, demande),
		)
		return {"action": "legacy"}

	montant = flt(devis.get("rounded_total") or devis.get("grand_total"))
	#//// Neoffice — la restriction voyage en métadonnée, pas en configuration de
	#//// canal : le canal est partagé par toutes les tuiles du fournisseur, et
	#//// une restriction posée là s'appliquerait aussi à celles qui ne la
	#//// veulent pas. Les pilotes qui savent filtrer la lisent
	#//// (`payments/drivers/payrexx/web_driver.py` la relit même dans la réponse
	#//// et journalise si la passerelle l'a laissée tomber) ; les autres
	#//// l'ignorent sans bruit.
	moyens = _restricted_methods(payment_gateway_account)
	intention = create_intent(
		provider=couple[0],
		channel=couple[1],
		# Les intentions comptent en centimes.
		amount=int(round(montant * 100)),
		currency=devis.currency or "CHF",
		reference_doctype="Payment Request",
		reference_name=demande["payment_request_id"],
		metadata={"payment_methods": moyens} if moyens else None,
	)
	charge = intention.get("next_action_payload")
	if isinstance(charge, str):
		charge = frappe.parse_json(charge) if charge else {}
	charge = charge or {}
	quoi = (intention.get("next_action_type") or "none").strip()

	#//// Neoffice — l'écran d'intention est dessiné par le navigateur, donc ses
	#//// deux libellés passent par `__()`. Or le dictionnaire du client ne
	#//// contient que ce qu'un appel lui a déjà envoyé : sans ça, un tunnel
	#//// francophone affiche « Or type 12345 in the app. » sous le QR. Frappe
	#//// fusionne le `__messages` de CETTE réponse avant que le rappel ne dessine.
	from frappe.translate import send_translations

	send_translations({
		"Continue to payment": _("Continue to payment"),
		"Or type {0} in the app.": _("Or type {0} in the app."),
		"Waiting for your payment…": _("Waiting for your payment…"),
		"Payment not received. You can try again.": _("Payment not received. You can try again."),
	})

	if quoi == "redirect_to_url" and charge.get("url"):
		return {"action": "redirect", "url": charge["url"], "intent": intention.get("intent_name")}
	if quoi == "display_qr_payload":
		return {"action": "qr", "intent": intention.get("intent_name"), "payload": charge,
			"amount": montant, "currency": devis.currency}
	if quoi == "requires_confirmation" or intention.get("client_secret"):
		return {"action": "confirm", "intent": intention.get("intent_name"),
			"client_secret": intention.get("client_secret"), "payload": charge}

	# Rien d'exploitable : on retombe sur le chemin historique plutôt que de
	# laisser le client devant un écran vide.
	frappe.log_error(
		"Webshop: intention sans action exploitable",
		"intention={0} type={1} methode={2}".format(intention.get("intent_name"), quoi, payment_gateway_account),
	)
	return {"action": "legacy"}


@frappe.whitelist(allow_guest=True)
def cart_intent_state(intent: str) -> dict:
	"""//// Neoffice — où en est le paiement, pendant que le client tient son téléphone.

	Un QR ne redirige pas : la page reste là et doit apprendre, seule, que
	l'argent est arrivé. Elle demande ici — sur signal de `payments`, et à
	défaut toutes les cinq secondes.

	🔴 Ce n'est PAS l'intention qui fait foi : une intention « succeeded » dont
	la commande n'est pas encore créée laisserait annoncer une commande qui
	n'existe pas. C'est la **Payment Request** qui tranche, parce que c'est
	elle que la machinerie de `payments` transforme en Sales Order.

	🔴 Le nom de l'évènement temps réel porte l'identifiant de l'intention :
	n'importe qui pourrait s'y abonner. On ne rend donc l'état que d'une
	intention dont la Payment Request appartient au panier de CE visiteur.
	"""
	row = frappe.db.get_value(
		"Payment Intent", intent, ["status", "reference_doctype", "reference_name"], as_dict=True
	)
	if not row or row.reference_doctype != "Payment Request":
		frappe.throw(_("Nothing to pay"))

	demande = frappe.db.get_value(
		"Payment Request", row.reference_name,
		["status", "reference_doctype", "reference_name", "party"], as_dict=True
	)
	if not demande:
		frappe.throw(_("Nothing to pay"))

	# La demande doit appartenir à CE client — sinon un numéro d'intention
	# suffirait à surveiller le paiement d'un inconnu.
	#
	# 🔴 On compare le CLIENT, pas le panier. À l'instant précis où la commande
	# naît, le panier courant est remplacé par un neuf : une garde adossée au
	# panier refuse la réponse au moment exact où la page en a besoin — la page
	# resterait sur « en attente » alors que la commande existe. Vécu le
	# 2026-08-24 : commande BC-2026-00343 créée, page jamais prévenue.
	moi = get_party()
	sien = bool(moi) and demande.party and demande.party == moi.name
	if not sien:
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	if demande.reference_doctype == "Sales Order":
		return {"done": True, "redirect_to": "/thank_you?sales_order={0}".format(demande.reference_name)}
	if demande.status in ("Paid", "Completed"):
		return {"done": True, "redirect_to": None}
	return {"done": False, "status": row.status}


def _intent_is_wanted(payment_gateway_account: str) -> bool:
	"""//// Neoffice — cette méthode a-t-elle été basculée sur les intentions ?

	Décoché par défaut, et lu sur la ligne de `Webshop Settings` : c'est le
	commerçant qui bascule, méthode par méthode, quand il a vérifié chez lui.
	"""
	try:
		settings = frappe.get_cached_doc("Webshop Settings")
	except Exception:
		return False
	for row in settings.get("payment_methods") or []:
		if row.payment_gateway_account == payment_gateway_account:
			return bool(row.get("use_payment_intent"))
	return False


def _restricted_methods(payment_gateway_account: str) -> list[str]:
	"""//// Neoffice — les moyens de paiement auxquels cette tuile se limite.

	Ce qui permet à une seule passerelle de tenir plusieurs tuiles : on nomme un
	second Payment Gateway Account d'après le même fournisseur et on restreint
	celui-ci à `twint`, l'autre à `visa,mastercard`. Le client voit deux tuiles
	distinctes — « TWINT » et « Carte » — et les deux s'encaissent par le même
	fournisseur, au lieu d'une tuile unique qui le renvoie vers une page où il
	doit encore choisir.

	Vide = tout ce que le compte autorise, c'est-à-dire le comportement actuel.
	"""
	try:
		settings = frappe.get_cached_doc("Webshop Settings")
	except Exception:
		return []
	for row in settings.get("payment_methods") or []:
		if row.payment_gateway_account == payment_gateway_account:
			brut = (row.get("restrict_payment_methods") or "").strip()
			return [m.strip() for m in brut.split(",") if m.strip()]
	return []


def _intent_binding(kind: str):
	"""//// Neoffice — le couple (fournisseur, canal) web pour ce type de passerelle.

	Résolu et non figé : le fournisseur change d'un site à l'autre
	(`wallee_test`, `payrexx`, `twint_smoke_provider`), seul son préfixe est
	stable. Les canaux `terminal` et `tap_to_pay` appartiennent à la caisse.
	"""
	if not kind:
		return None
	for row in frappe.get_all("Provider Channel Settings", filters={"enabled": 1},
			fields=["provider", "channel"]):
		if not (row.channel or "").endswith("_web"):
			continue
		if not (row.provider or "").lower().startswith(kind):
			continue
		if not frappe.db.get_value("Payment Provider", row.provider, "enabled"):
			continue
		return (row.provider, row.channel)
	return None


@frappe.whitelist(allow_guest=True)
def get_payment_template(payment_gateway_account, context=None):
	"""Load the HTML template for a payment gateway"""
	try:		
		if not payment_gateway_account:
			return {
				"error": True,
				"message": "No payment gateway account specified"
			}

		# Get all gateway information
		gateway_info = get_gateway_info(payment_gateway_account)
		
		# Initialize context as an empty dictionary if None
		context = context if isinstance(context, dict) else {}
		
		# Add required parameters from settings
		if gateway_info["config"]:
			for setting in gateway_info["config"].get("required_settings", []):
				context[setting] = gateway_info["settings"].get(setting) if gateway_info["settings"] else None

			# Clean ID to avoid conflicts
			clean_id = payment_gateway_account.replace(" ", "-")
			
			# Add unique IDs to context
			context_ids = gateway_info["config"].get("context_ids", {})
			context.update({
				key: f"{value}-{clean_id}" for key, value in context_ids.items()
			})

		#//// Neoffice — le document qu'on paie : celui que l'appelant nomme dans
		#//// son contexte, sinon le panier. Sans ça, une facture de réservation
		#//// se voyait répondre « Your basket is empty » alors qu'elle n'a jamais
		#//// eu de panier, et sa référence était de toute façon écrasée plus bas.
		quotation_doc = _document_a_payer(
			context.get("reference_doctype"), context.get("reference_docname")
		)

		if not quotation_doc:
			frappe.throw(_('Your basket is empty'))

		# Get CGV from Webshop Settings for payment templates
		webshop_settings = frappe.get_cached_doc("Webshop Settings")
		cgv_tc_name = None
		cgv_terms = None
		if webshop_settings.checkout_cgv:
			cgv_tc_name = webshop_settings.checkout_cgv
			cgv_terms = frappe.db.get_value("Terms and Conditions", webshop_settings.checkout_cgv, "terms")
		
		# Add required variables to template
		context.update({
			"payment_gateway": gateway_info["type"],
			"currency": gateway_info["account"].currency,
			"company": frappe.db.get_default("company"),
			"payment_gateway_account": payment_gateway_account,
			"gateway_settings": gateway_info["settings"],
			"_": frappe._,
			#//// Neoffice — `setdefault` et non écrasement : l'appelant peut payer
			#//// autre chose qu'un panier (une facture de réservation), et il l'a
			#//// dit dans son contexte. Ces quatre lignes l'effaçaient juste après.
			"amount": (context.get("amount")
				or (quotation_doc.get("rounded_total") or quotation_doc.get("grand_total") if quotation_doc else 0)),
			"quotation_id": context.get("quotation_id") or (quotation_doc.name if quotation_doc else ""),
			"submit_id": f"submit_{gateway_info['type'].lower().replace(' ', '_')}",
			"reference_doctype": context.get("reference_doctype") or "Quotation",
			"reference_docname": context.get("reference_docname") or (quotation_doc.name if quotation_doc else ""),
			"description": (context.get("description")
				or (f"Payment for order {quotation_doc.name}" if quotation_doc else "")),
			"doc": quotation_doc,  # Add quotation document to context
			"cgv_tc_name": cgv_tc_name,  # Add CGV name for payment templates
			"cgv_terms": cgv_terms  # Add CGV content for payment templates
		})
		
		# Check for custom template path
		try:
			webshop_method = frappe.get_doc("Webshop Payment Method", {"payment_gateway_account": payment_gateway_account})
			template_path = webshop_method.get("template_path")
			if template_path:
				# If path starts with apps/, we look for template in another app
				if template_path.startswith('apps/'):
					# Remove apps/ prefix
					path_parts = template_path[5:].split('/')
					# Remove duplicate app name if present
					if len(path_parts) > 1 and path_parts[0] == path_parts[1]:
						path_parts.pop(1)
					template_path = '/'.join(path_parts)
				
				html = frappe.get_template(template_path).render(context)
				return {"error": False, "html": html, "config": gateway_info["settings"]}
		except Exception as e:
			frappe.log_error(f"Custom template error: {str(e)}")
			pass  # If error, use default template
		
		# Default template rendering
		template_name = f"{gateway_info['type']}.html"
		html = frappe.get_template(f"templates/payments/{template_name}").render(context)
		
		return {"error": False, "html": html, "config": gateway_info["settings"]}

	except Exception as e:
		frappe.log_error(f"General error", e)
		return {
			"error": True,
			"message": f"Error loading template: {str(e)}"
		}

def get_gateway_info(payment_gateway_account):
    """Get payment gateway information"""
    try:
        if not payment_gateway_account:
            raise ValueError("No payment gateway account specified")

        # 1. Get Payment Gateway Account
        account = frappe.get_doc("Payment Gateway Account", payment_gateway_account)
        if not account:
            raise ValueError(f"Gateway account not found: {payment_gateway_account}")

        # 2. Get Payment Gateway
        gateway = frappe.get_doc("Payment Gateway", account.payment_gateway)
        if not gateway:
            raise ValueError(f"Gateway not found: {account.payment_gateway}")

        # 3. Get gateway settings
        gateway_settings = None
        if gateway.gateway_settings:
            settings_doctype = gateway.gateway_settings
            settings_name = gateway.gateway_controller
            
            if frappe.db.exists(settings_doctype, settings_name):
                settings_doc = frappe.get_doc(settings_doctype, settings_name)
                gateway_settings = settings_doc.as_dict()

        # Get gateway type from name
        gateway_type = gateway.gateway.split('-')[0].split()[0].lower().strip()
        
        # Get gateway configuration from JSON file
        gateway_config = get_gateway_configuration(gateway_type, account.name)
        
        return {
            "account": account,
            "gateway": gateway,
            "settings": gateway_settings,
            "type": gateway_type,
            "config": gateway_config
        }
        
    except Exception as e:
        frappe.log_error("Error getting gateway information", e)
        raise

@frappe.whitelist()
def update_payment_method(payment_method):
    """Update the payment method in the cart quotation"""
    quotation = _get_cart_quotation()
    
    # Utiliser db_set pour mettre à jour directement sans vérification de timestamp
    quotation.db_set('payment_method', payment_method, update_modified=False)
    
    return {
        "success": True,
        "payment_method": payment_method
    }

@frappe.whitelist()
def update_address_info(doctype, docname, fieldname_dict):
    """Update address information with ignore_permissions=True"""
    try:
        # Convert JSON string to dict if needed
        if isinstance(fieldname_dict, str):
            fieldname_dict = json.loads(fieldname_dict)
            
        # Update the document with ignore_permissions=True
        doc = frappe.get_doc(doctype, docname)
        doc.update(fieldname_dict)
        doc.save(ignore_permissions=True)
        
        return {"success": True, "name": docname}
    except Exception as e:
        frappe.log_error(f"Error updating address: {str(e)}")
        return {"success": False, "message": str(e)}
