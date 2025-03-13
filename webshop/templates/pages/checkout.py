import frappe
import json
from frappe import _
from frappe.utils import flt, fmt_money, get_link_to_form
from webshop.webshop.shopping_cart.cart import get_cart_quotation, get_party, get_address_docs, apply_shipping_rule, _get_cart_quotation
from webshop.controllers.payment_handler import PaymentHandler
from webshop.webshop.utils.utils import get_gateway_configuration
from erpnext.setup.utils import get_exchange_rate
from erpnext.stock.get_item_details import get_conversion_factor
from erpnext.accounts.doctype.shipping_rule.shipping_rule import ShippingRule

no_cache = 1

def get_context(context):
	"""Context for the payment page"""
	from webshop.webshop.shopping_cart.guest_cart import check_and_merge_guest_cart
	
	# Check and merge guest cart if needed
	check_and_merge_guest_cart()
	
	# Check if a quotation exists
	quotation = _get_cart_quotation()
	
	# Check shop settings
	settings = frappe.get_doc("Webshop Settings")
	
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
	cart_quotation = get_cart_quotation()
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
			context.billing_address_2 = billing_address.address_line2
			context.billing_city = billing_address.city
			context.billing_state = billing_address.state
			context.billing_country = billing_address.country
			context.billing_postcode = billing_address.pincode
			# Use customer's contact info if address doesn't have it
			context.billing_phone = billing_address.phone or (customer.mobile_no if customer else '')
			context.billing_email = billing_address.email_id or (customer.email_id if customer else '')
	
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

		loyalty_program_details = get_loyalty_program_details_with_points(
			context.doc.customer_name, customer_loyalty_program
		)

		available_loyalty_points = loyalty_program_details.get("loyalty_points")
		conversion_factor = loyalty_program_details.get("conversion_factor")

		context = {
			"loyalty_points": loyalty_program_details.get("loyalty_points"),
			"available_loyalty_points": available_loyalty_points,
			"conversion_factor": conversion_factor,
			"loyalty_points_value": frappe.utils.fmt_money(available_loyalty_points * conversion_factor, currency=quotation.currency)
		}
	
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
				
				# Calculate cart dimensions if needed (max dimensions from items)
				length = width = height = 0
				total_weight = 0
				
				# Calculate dimensions and weight from items
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
						item_length = getattr(item_doc, 'length', 0) or 0
						item_width = getattr(item_doc, 'width', 0) or 0
						item_height = getattr(item_doc, 'height', 0) or 0
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
						
						# Update max dimensions
						if item_length > length:
							length = item_length
						if item_width > width:
							width = item_width
						if item_height > height:
							height = item_height
				
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
			
			available_methods.append({
				"name": rule.name,
				"title": rule.label or rule.name,
				"description": rule.description or _("Shipping to {0}").format(country),
				"rate": shipping_amount,
				"display_rate": display_amount,
				"formatted_rate": frappe.format_value(display_amount, {"fieldtype": "Currency"}),
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
				"formatted_tax_amount": fmt_money(tax.tax_amount, currency=quotation_doc.currency)
			} for tax in quotation_doc.taxes] if quotation_doc.taxes else [],
			'formatted_grand_total': fmt_money(quotation_doc.grand_total, currency=quotation_doc.currency),
			'formatted_net_total': fmt_money(quotation_doc.net_total, currency=quotation_doc.currency),
			'formatted_shipping_amount': fmt_money(quotation_doc.shipping_rule_rate if hasattr(quotation_doc, 'shipping_rule_rate') else 0, currency=quotation_doc.currency)
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

@frappe.whitelist(allow_guest=True)
def get_payment_methods():
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
				
				title = payment_gateway_account.checkout_title or payment_gateway_account.name
				logo_html = f"<img src='{payment_gateway_account.logo}' alt='{title}' class='payment-logo'>" if payment_gateway_account.logo else ""
				description = payment_gateway_account.checkout_description or ""
				cart_info = get_cart_quotation()
				quotation_doc = cart_info.get('doc')
				
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

		# Get updated quotation
		cart_info = get_cart_quotation()
		quotation_doc = cart_info.get('doc')
		
		if not quotation_doc:
			frappe.throw(_('Your basket is empty'))

		# Add required variables to template
		context.update({
			"payment_gateway": gateway_info["type"],
			"currency": gateway_info["account"].currency,
			"company": frappe.db.get_default("company"),
			"payment_gateway_account": payment_gateway_account,
			"gateway_settings": gateway_info["settings"],
			"_": frappe._,
			"amount": quotation_doc.rounded_total if quotation_doc else 0,
			"quotation_id": quotation_doc.name if quotation_doc else "",
			"submit_id": f"submit_{gateway_info['type'].lower().replace(' ', '_')}",
			"reference_doctype": "Quotation",  
			"reference_docname": quotation_doc.name if quotation_doc else "",  
			"description": f"Payment for order {quotation_doc.name}" if quotation_doc else "",
			"doc": quotation_doc  # Add quotation document to context
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
