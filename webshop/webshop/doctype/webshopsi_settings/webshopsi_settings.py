# Copyright (c) 2025, Neoffice Team and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _
from frappe.utils import today

class WebshopSISettings(Document):
	def get_restricted_countries(self):
		"""Returns the list of restricted countries"""
		restricted_countries = []
		if self.restricted_countries:
			restricted_countries = [d.country for d in self.restricted_countries]
		return restricted_countries
	
	def get_available_installments(self, amount):
		"""Returns the available payment options for a given amount"""
		available_installments = []
		if self.installment_plans:
			for installment in self.installment_plans:
				# Do not check min/max amounts here
				payment_terms = frappe.get_doc("Payment Terms Template", installment.payment_terms_template) if installment.payment_terms_template else None
				num_payments = len(payment_terms.terms) if payment_terms and payment_terms.terms else 1
				
				available_installments.append({
					'name': installment.name,
					'num_payments': num_payments,
					'min_amount': float(installment.minimum_amount or 0),
					'max_amount': float(installment.maximum_amount or float('inf')),
					'description': installment.title,
					'fee_percentage': float(installment.fee_percentage) if installment.fee_percentage else 0,
					'payment_terms_template': installment.payment_terms_template
				})
		
		# If no option is configured, add the default single payment option
		if not available_installments:
			available_installments.append({
				'name': 'single_payment',
				'num_payments': 1,
				'min_amount': 0,
				'max_amount': float('inf'),
				'description': _("Single payment"),
				'fee_percentage': 0,
				'payment_terms_template': None
			})
			
		return available_installments
	
	def get_terms_and_conditions(self):
		"""Returns the content of the terms and conditions"""
		terms_content = ""
		if self.terms_and_conditions:
			try:
				terms_doc = frappe.get_doc("Terms and Conditions", self.terms_and_conditions)
				terms_content = terms_doc.terms
			except Exception:
				frappe.log_error("Error retrieving terms and conditions")
		return terms_content

	def apply_payment_fees(self, quotation, installment):
		"""Adds payment fees to the order if necessary"""
		if not installment or not installment.get('fee_percentage'):
			return

		# Check if a fee line already exists
		has_fee = False
		for tax in quotation.taxes:
			if tax.get('is_webshopsi_fee'):
				has_fee = True
				break
		
		# If the fee line does not exist, add it
		if not has_fee:
			fee_amount = (quotation.grand_total * installment['fee_percentage']) / 100
			
			quotation.append("taxes", {
				"charge_type": "Actual",
				"description": f"Payment fees ({installment['fee_percentage']}%)",
				"account_head": self.fee_account,
				"cost_center": self.fee_cost_center,
				"tax_amount": fee_amount,
				"is_webshopsi_fee": 1
			})
			
			quotation.save(ignore_permissions=True)

def make_invoice(sales_order_name):
	"""Create a Sales Invoice from a Sales Order"""
	from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice

	so = frappe.get_doc("Sales Order", sales_order_name)
	si = make_sales_invoice(sales_order_name, ignore_permissions=True)
	
	# Copy payment terms and schedule
	if so.payment_terms_template:
		si.payment_terms_template = so.payment_terms_template
		si.payment_schedule = []
		for schedule in so.payment_schedule:
			si.append("payment_schedule", {
				"payment_term": schedule.payment_term,
				"description": schedule.description,
				"due_date": schedule.due_date,
				"invoice_portion": schedule.invoice_portion,
				"payment_amount": schedule.payment_amount,
				"base_payment_amount": schedule.base_payment_amount,
				"mode_of_payment": schedule.mode_of_payment
			})
	
	si.insert(ignore_permissions=True)
	si.submit()

	return si

@frappe.whitelist()
def on_payment_authorized(gateway_settings , birthday=None, contactName=None):
	"""
	Secure method to validate and finalize a WebshopSI payment.
	This method is called after creating the payment_request.
	
	Args:
		gateway_settings (dict): WebshopSI gateway settings
		
	Returns:
		dict: Payment result with redirection
	"""
	try:
		from webshop.webshop.shopping_cart.cart import place_order, _get_cart_quotation
		
		# 1. Get quotation
		quotation = _get_cart_quotation()
		if not quotation:
			frappe.throw(_("No active quotation found"))

		# Get Payment Gateway
		gateway = frappe.get_value("Payment Gateway", {"gateway_settings": gateway_settings}, "name")
		if not gateway:
			frappe.throw(_("Payment Gateway not found for settings: {0}").format(gateway_settings))
		
		webshopsi_settings = frappe.get_doc("WebshopSI Settings")
		
		# Set birthday in contact
		if birthday and contactName:
			contact = frappe.get_doc("Contact", contactName)
			contact.birthday = birthday
			contact.save(ignore_permissions=True)
		
		# Get Payment Gateway Account
		gateway_account = frappe.get_doc("Payment Gateway Account", {"payment_gateway": gateway})
		if not gateway_account:
			frappe.throw(_("Payment Gateway Account not found"))
		
		rounded_total = quotation.rounded_total or quotation.grand_total

		# WebshopSI Invoice Installments
		selected_installment = frappe.form_dict.get('installment')
		if not selected_installment:
			selected_installment = frappe.cache().get_value(f'webshopsi_installment_{quotation.name}')
		
		if selected_installment:
			available_installments = webshopsi_settings.get_available_installments(rounded_total)
			installment_found = False
			for installment in available_installments:
				if installment['name'] == selected_installment:
					installment_found = True
					if rounded_total < installment['min_amount'] or rounded_total > installment['max_amount']:
						frappe.throw(_("The order amount does not match the criteria of the selected payment option"))
					
					# Apply payment fees if necessary
					webshopsi_settings.apply_payment_fees(quotation, installment)
					
					# Update payment terms template based on the number of payments
					if installment['num_payments'] > 1:
						payment_terms_template = f"WebshopSI_{installment['num_payments']}_payments"
						if frappe.db.exists('Payment Terms Template', payment_terms_template):
							quotation.payment_terms_template = payment_terms_template
							quotation.save(ignore_permissions=True)
							
							# Update payment schedule
							from erpnext.controllers.accounts_controller import get_payment_terms
							payment_schedule = get_payment_terms(
								payment_terms_template,
								posting_date=quotation.transaction_date,
								grand_total=rounded_total,
								base_grand_total=quotation.base_rounded_total or quotation.base_grand_total
							)
							
							if payment_schedule:
								quotation.set("payment_schedule", payment_schedule)
								quotation.save(ignore_permissions=True)
					break
			
			if not installment_found:
				frappe.throw(_("Invalid payment option"))
		
		# Create payment request with transaction date
		# payment_request = frappe.get_doc({
		# 	"doctype": "Payment Request",
		# 	"payment_gateway_account": gateway_account.name,
		# 	"payment_request_type": "Inward",
		# 	"reference_doctype": "Quotation",
		# 	"reference_name": quotation.name,
		# 	"grand_total": quotation.rounded_total or quotation.grand_total,
		# 	"email_to": quotation.contact_email,
		# 	"status": "Draft",
		# 	"payment_gateway": gateway_account.payment_gateway,
		# 	"gateway_data": quotation.name,
		# 	"transaction_date": frappe.utils.now(),
		# 	"party_type": "Customer",
		# 	"party": quotation.party_name,
		# 	"from_checkout": 1
		# })
		# payment_request.flags.ignore_permissions = True
		# payment_request.insert(ignore_permissions=True) 
		# payment_request.submit()

		# Create order
		frappe.flags.ignore_permissions = True
		sales_order_name = place_order()
		if not sales_order_name:
			frappe.throw(_("Error creating order"))
						
		# Update payment request reference
		# payment_request.db_set('reference_doctype', 'Sales Order', update_modified=False)
		# payment_request.db_set('reference_name', sales_order_name, update_modified=False)
	
		# Create invoice
		try:
			make_invoice(sales_order_name)
		except Exception as e:
			frappe.log_error("Error creating invoice", str(e))
			return {
				"status": "error",
				"message": _("Error creating invoice"),
				"redirect_to": "/payment-failed"
			}

		# Success URL
		success_url = f"/thank_you?sales_order={sales_order_name}"

		return {
			"status": "success",
			"redirect_to": success_url
		}
			
	except Exception as e:
		frappe.log_error("Error processing payment", str(e))
		return {
			"status": "error",
			"message": str(e),
			"redirect_to": "/payment-failed"
		}

@frappe.whitelist()
def get_contact_birthday(contact_name):
	"""Securely retrieves a contact's birthday."""
	if not contact_name:
		return None
	
	try:
		birthday = frappe.db.get_value("Contact", contact_name, "birthday")
		return birthday
	except Exception as e:
		frappe.log_error(f"Error retrieving birthday: {str(e)}")
		return None

@frappe.whitelist()
def get_payment_context(reference_doctype=None, reference_docname=None):
    """Get payment context for WebshopSI payment
    
    Args:
        reference_doctype (str): Type of reference document
        reference_docname (str): Name of reference document
    """
    try:
        context = {}
        
        # Get document
        if not reference_doctype or not reference_docname:
            frappe.throw(_("Reference document is required"))
            
        doc = frappe.get_doc(reference_doctype, reference_docname)
        amount = doc.rounded_total or doc.grand_total
        
        # Get settings
        settings = frappe.get_cached_doc("WebshopSI Settings")
        
        # Get payment gateway account
        gateway = frappe.get_value("Payment Gateway", {"gateway_settings": settings.name}, "name")
        if not gateway:
            frappe.throw(_("Payment Gateway not found for settings: {0}").format(settings.name))
            
        # Get Payment Gateway Account
        gateway_account = frappe.get_doc("Payment Gateway Account", {"payment_gateway": gateway})
        
        # Clean gateway name for form ID
        import re
        clean_name = re.sub(r'[^a-zA-Z0-9]', '_', gateway_account.name)
        payment_form_id = f"payment-form-{clean_name}"
        
        # Prepare context IDs
        context.update({
			'form_id': clean_name,
			'gateway_account': gateway_account.name,
            "payment_form_id": payment_form_id,
            "card_element_id": "card-element",
            "card_errors_id": "card-errors",
            "submit_id": "submit"
        })
        
        # Add payment options
        context.update({
            'restricted_countries': settings.get_restricted_countries(),
			'billing_country': doc.get('billing_country') if hasattr(doc, 'billing_country') else None,
            'age_control': settings.get('age_control', 0),
            'min_age': settings.get('min_age', 18),
            'installments': settings.get_available_installments(amount),
            'display_specific_conditions': settings.get('display_specific_conditions', 0),
            'introduction_text': settings.get('introduction_text', ''),
			'terms_title': settings.get('terms_and_conditions', ''),
            'terms_content': settings.get_terms_and_conditions(),
            'today': today()
        })
        
        return context
        
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), _("Failed to get payment context"))
        frappe.throw(_("Failed to get payment context: {0}").format(str(e)))


@frappe.whitelist()
def migrate_installment_fees_to_templates():
    """Idempotent migration: copy each WebshopSI installment plan's fee
    (percentage + min/max) onto its linked Payment Terms Template, and seed every
    Company's default_payment_fee_account from the legacy WebshopSI Settings
    fee_account. The Payment Terms Template becomes the single source of truth for
    the fee; the installment_plans table keeps only its role of listing which
    plans are offered at checkout. Safe to re-run; skips if the target custom
    fields are not synced yet."""
    if not frappe.db.has_column("Payment Terms Template", "apply_percentage_fee"):
        return {"skipped": "custom fields not synced yet"}
    settings = frappe.get_single("WebshopSI Settings")
    migrated = []
    for plan in (settings.installment_plans or []):
        tpl = plan.payment_terms_template
        if not tpl or not frappe.db.exists("Payment Terms Template", tpl):
            continue
        fee = plan.fee_percentage or 0
        frappe.db.set_value("Payment Terms Template", tpl, {
            "apply_percentage_fee": 1 if fee > 0 else 0,
            "fee_percentage": fee,
            "fee_minimum_amount": plan.minimum_amount or 0,
            "fee_maximum_amount": plan.maximum_amount or 0,
        })
        migrated.append({"template": tpl, "fee_percentage": fee})
    acc = settings.fee_account
    cc = settings.fee_cost_center
    if acc:
        for comp in frappe.get_all("Company", pluck="name"):
            if not frappe.db.get_value("Company", comp, "default_payment_fee_account"):
                frappe.db.set_value("Company", comp, "default_payment_fee_account", acc)
            if cc and not frappe.db.get_value("Company", comp, "default_payment_fee_cost_center"):
                frappe.db.set_value("Company", comp, "default_payment_fee_cost_center", cc)
    frappe.db.commit()
    return {"migrated": migrated, "seeded_account": acc}
