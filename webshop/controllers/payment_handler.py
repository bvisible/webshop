import frappe
from frappe import _
import json
from webshop.webshop.shopping_cart.cart import place_order, _get_cart_quotation, is_gift_card_item
from erpnext.accounts.doctype.payment_request.payment_request import make_payment_entry
from webshop.utils.utils import get_gateway_configuration

class PaymentHandler:
    def __init__(self):
        self.settings = frappe.get_doc("Webshop Settings")
        
    def create_payment_request(self, quotation_id=None):
        """Create a payment request for a quotation"""
        try:
            # if not quotation, get cart quotation
            if not quotation_id:
                quotation = _get_cart_quotation()
                if not quotation:
                    frappe.throw(_("Cart is empty"))
            else:
                quotation = frappe.get_doc("Quotation", quotation_id)
            
            # Get webshop parameters
            settings = frappe.get_cached_doc("Webshop Settings")
            
            # Get default payment method
            payment_method = self.get_default_payment_method()
            payment_method_doc = frappe.get_doc("Webshop Payment Method", payment_method)
            
            # Get payment gateway account
            pm = payment_method_doc
            gateway_account = frappe.get_doc("Payment Gateway Account", pm.payment_gateway_account)
            
            # Update quotation with payment_gateway
            quotation.payment_gateway = gateway_account.payment_gateway
            
            # Ensure amounts are defined
            if not quotation.rounded_total:
                quotation.run_method("set_missing_values")
                quotation.run_method("calculate_taxes_and_totals")
                
            # Clear and recalculate payment schedule
            quotation.payment_schedule = []
            quotation.set_payment_schedule()
            quotation.save(ignore_permissions=True)
            
            # Update payment_terms_template from payment method
            settings = frappe.get_cached_doc("Webshop Settings")
            for method in settings.payment_methods:
                if method.payment_gateway_account == pm.payment_gateway_account and method.payment_terms_template:
                    quotation.payment_terms_template = method.payment_terms_template
                    quotation.save(ignore_permissions=True)
                    
                    # Get and update payment schedule
                    from erpnext.controllers.accounts_controller import get_payment_terms
                    payment_schedule = get_payment_terms(
                        method.payment_terms_template,
                        posting_date=quotation.transaction_date,
                        grand_total=quotation.rounded_total or quotation.grand_total,
                        base_grand_total=quotation.base_rounded_total or quotation.base_grand_total
                    )
                    
                    if payment_schedule:
                        quotation.set("payment_schedule", payment_schedule)
                        quotation.save(ignore_permissions=True)
                    break

            # Create context for payment request
            context = {
                "reference_doctype": "Quotation",
                "reference_name": quotation.name,
                "amount": quotation.rounded_total,
                "currency": quotation.currency,
                "payment_gateway": gateway_account.payment_gateway
            }
            
            # Get gateway parameters from configuration
            gateway_settings = {}
            gateway_type = gateway_account.payment_gateway.split('-')[0].split()[0].lower().strip()
            config = get_gateway_configuration(gateway_type)
            required_settings = config.get("required_settings", [])
            
            # Get required parameters from gateway account
            for setting in required_settings:
                if hasattr(gateway_account, setting):
                    gateway_settings[setting] = getattr(gateway_account, setting)
            
            # Prepare data for template
            context.update({
                "payment_method": payment_method,
                "gateway_settings": gateway_settings,
                "callback_url": frappe.utils.get_url("/api/payment/callback"),
            })
            
            # Get context IDs from JSON configuration
            context_ids = config.get("context_ids", {})
            context.update({
                "payment_form_id": context_ids.get("payment_form_id", "payment-form"),
                "card_element_id": context_ids.get("card_element_id", "card-element"),
                "card_errors_id": context_ids.get("card_errors_id", "card-errors"),
                "submit_id": context_ids.get("submit_id", "submit")
            })
            
            # Create payment request with transaction date
            payment_request = frappe.get_doc({
                "doctype": "Payment Request",
                "payment_gateway_account": gateway_account.name,
                "payment_request_type": "Inward",
                "reference_doctype": "Quotation",
                "reference_name": quotation.name,
                "grand_total": quotation.rounded_total,
                "email_to": quotation.contact_email,
                "status": "Draft",
                "payment_gateway": gateway_account.payment_gateway,
                "gateway_data": json.dumps(context),
                "transaction_date": frappe.utils.now(),
                "party_type": "Customer",
                "party": quotation.party_name,
                "from_checkout": 1
                
            })
            payment_request.flags.ignore_permissions = True
            payment_request.insert(ignore_permissions=True)
            
            return {
                "status": "success",
                "payment_url": payment_request.payment_url,
                "payment_request_id": payment_request.name,
                "gateway_data": context
            }
            
        except Exception as e:
            frappe.log_error("Detailed error while creating payment request", e)
            return {
                "status": "error",
                "message": _("Error creating payment request")
            }
    
    def handle_payment_success(self, **kwargs):
        try:
            # Get and validate payment request
            payment_request_id = kwargs.get('payment_request_id')
            if not payment_request_id:
                return self.handle_error("Missing payment request ID")
            
            payment_request = frappe.get_doc("Payment Request", payment_request_id)
            payment_request.flags.ignore_permissions = True
            self.payment_request = payment_request
            
            # Submit payment request now that payment is successful
            if payment_request.docstatus == 0:  # If not already submitted
                payment_request.submit()
            
            # Check if payment request is not already processed
            if payment_request.status in ["Paid", "Completed"]:
                return
            
            # 1. Get quotation
            quotation = frappe.get_doc("Quotation", payment_request.reference_name)
            self.quotation = quotation
            
            # 2. Check if Sales Order already exists for this Quotation
            linked_docs = frappe.get_all(
                "Sales Order",
                filters={
                    "order_type": "Shopping Cart",
                    "docstatus": 1,
                    "prevdoc_docname": quotation.name
                },
                fields=["name"],
                limit=1
            )
            
            if linked_docs:
                sales_order_name = linked_docs[0].name
            else:
                # Create Sales Order using place_order
                frappe.flags.ignore_permissions = True
                sales_order_name = place_order()
                if not sales_order_name:
                    return self.handle_error("Error creating order")
                            
            # 3. Update Payment Request with Sales Order reference
            payment_request.db_set('reference_doctype', 'Sales Order', update_modified=False)
            payment_request.db_set('reference_name', sales_order_name, update_modified=False)
        
            # 4. Call on_payment_authorized on Payment Request
            try:
                payment_request.run_method("on_payment_authorized", "Completed")
            except Exception as e:
                frappe.log_error("Error executing on_payment_authorized on Payment Request", e)
                return self.handle_error(str(e))
            
            # Build default success URL
            success_url = f"/thank_you?sales_order={sales_order_name}"
            
            return {
                "status": "success",
                "redirect_to": success_url,
                "message": _("Payment processed successfully")
            }
            
        except Exception as e:
            frappe.log_error("Detailed error while processing payment", e)
            return {
                "status": "error",
                "message": _("Error processing payment")
            }

    def handle_error(self, message):
        error_url = "/payment-failed"
        return {
            "status": "error",
            "redirect_to": error_url,
            "message": _(message)
        }

    def handle_payment_failure(self, payment_request_id, error_message=None):
        """Handle payment failure"""
        try:
            payment_request = frappe.get_doc("Payment Request", payment_request_id)
            payment_request.flags.ignore_permissions = True

            frappe.db.set_value("Payment Request", payment_request_id, {
                "docstatus": 1,
                "status": "Failed",
                "message": error_message or _("Payment failed")
            }, update_modified=False)

            frappe.db.commit()
            
            return {
                "status": "error",
                "message": error_message or _("Payment failed"),
                "redirect_to": ""
            }
            
        except Exception as e:
            frappe.log_error("Detailed error while processing payment failure", e)
            return {
                "status": "error",
                "message": _("A system error occurred while processing payment failure"),
                "redirect_to": ""
            }

    def get_default_payment_method(self):
        """Get default payment method"""
        settings = frappe.get_doc("Webshop Settings")
        payment_methods = settings.get("payment_methods", [])
        return payment_methods[0].name if payment_methods else None

    def handle_direct_order(self):
        """Handle direct order validation without payment"""
        try:
            # Create sales order
            from webshop.webshop.shopping_cart.cart import place_order
            sales_order_name = place_order()
            
            if not sales_order_name:
                return {
                    "status": "error",
                    "message": _("Error creating order")
                }
            
            # Create invoice
            from erpnext.accounts.doctype.payment_request.payment_request import make_payment_entry
            sales_order = frappe.get_doc("Sales Order", sales_order_name)
            
            # Create and submit invoice
            from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice
            si = make_sales_invoice(sales_order_name, ignore_permissions=True)
            si.allocate_advances_automatically = True
            si.insert(ignore_permissions=True)
            si.submit()

            # Redirect to thank you page
            success_url = f"/thank_you?sales_order={sales_order_name}"
            
            return {
                "status": "success",
                "redirect_to": success_url,
                "message": _("Order validated successfully")
            }
            
        except Exception as e:
            frappe.log_error("Error while validating order", str(e))
            return {
                "status": "error",
                "message": _("An error occurred while validating the order")
            }

@frappe.whitelist(allow_guest=True)
def create_payment_request():
    """Create a payment request for a quotation"""
    try:
        handler = PaymentHandler()
        return handler.create_payment_request()
    except Exception as e:
        frappe.log_error("Error creating payment request", e)
        return {
            "status": "error",
            "message": str(e)
        }

@frappe.whitelist(allow_guest=True)
def create_paypal_payment_request(quotation_id):
    """Create a payment request for PayPal"""
    try:
        # Get quotation
        quotation = frappe.get_doc("Quotation", quotation_id)
        
        # Update payment_terms_template for PayPal
        settings = frappe.get_cached_doc("Webshop Settings")
        for method in settings.payment_methods:
            payment_gateway_account = frappe.get_doc("Payment Gateway Account", method.payment_gateway_account)
            payment_gateway = frappe.get_doc("Payment Gateway", payment_gateway_account.payment_gateway)
            gateway_type = payment_gateway.gateway.split('-')[0].split()[0].lower().strip()
            if gateway_type == "paypal" and method.payment_terms_template:
                quotation.payment_terms_template = method.payment_terms_template
                quotation.save(ignore_permissions=True)
                
                # Get and update payment schedule
                from erpnext.controllers.accounts_controller import get_payment_terms
                payment_schedule = get_payment_terms(
                    method.payment_terms_template,
                    posting_date=quotation.transaction_date,
                    grand_total=quotation.rounded_total or quotation.grand_total,
                    base_grand_total=quotation.base_rounded_total or quotation.base_grand_total
                )
                
                if payment_schedule:
                    quotation.set("payment_schedule", payment_schedule)
                    quotation.save(ignore_permissions=True)
                break
        
        # Check if payment request already exists
        payment_request = frappe.get_all(
            "Payment Request",
            filters={
                "reference_doctype": "Quotation",
                "reference_name": quotation.name,
                "docstatus": 1
            },
            limit=1
        )

        if payment_request:
            payment_request = frappe.get_doc("Payment Request", payment_request[0].name)
            if payment_request.status == "Paid":
                frappe.throw(_("This order has already been paid"))
            elif payment_request.status == "Failed":
                # Cancel and delete existing payment request
                payment_request.flags.ignore_permissions = True
                frappe.db.set_value("Payment Request", payment_request.name, "docstatus", 2)
                frappe.db.commit()
                frappe.delete_doc("Payment Request", payment_request.name, ignore_permissions=True)
                frappe.db.commit()
                
                # Create new payment request
                payment_request = frappe.get_doc({
                    "doctype": "Payment Request",
                    "payment_request_type": "Inward",
                    "transaction_date": frappe.utils.now(),
                    "reference_doctype": "Quotation",
                    "reference_name": quotation.name,
                    "grand_total": quotation.rounded_total,
                    "currency": quotation.currency,
                    "email_to": quotation.contact_email,
                    "payment_gateway": "PayPal",
                    "status": "Draft",
                    "party_type": "Customer",
                    "party": quotation.party_name,
                    "from_checkout": 1
                })
                payment_request.flags.ignore_permissions = True
                payment_request.insert(ignore_permissions=True)
                payment_request.save(ignore_permissions=True)
        else:
            # Create new payment request
            payment_request = frappe.get_doc({
                "doctype": "Payment Request",
                "payment_request_type": "Inward",
                "transaction_date": frappe.utils.now(),
                "reference_doctype": "Quotation",
                "reference_name": quotation.name,
                "grand_total": quotation.rounded_total,
                "currency": quotation.currency,
                "email_to": quotation.contact_email,
                "payment_gateway": "PayPal",
                "status": "Draft",
                "party_type": "Customer",
                "party": quotation.party_name,
                "from_checkout": 1
            })
            payment_request.flags.ignore_permissions = True
            payment_request.insert(ignore_permissions=True)
            payment_request.save(ignore_permissions=True)        
        try:
            # Prepare data for PayPal Express Checkout
            payment_details = {
                "amount": payment_request.grand_total,
                "title": f"Payment for {quotation.name}",
                "description": "Payment via PayPal",
                "reference_doctype": payment_request.doctype,
                "reference_docname": payment_request.name,
                "payer_email": payment_request.email_to,
                "payer_name": quotation.customer_name,
                "order_id": payment_request.name,
                "currency": payment_request.currency,
                "payment_gateway": "PayPal",
                "party_type": "Customer",
                "party": quotation.party_name,
                "from_checkout": 1
            }            
            # Get PayPal payment URL via Express Checkout
            from payments.utils import get_payment_gateway_controller
            controller = get_payment_gateway_controller("PayPal")
            payment_url = controller.get_payment_url(**payment_details)
            
            if not payment_url:
                frappe.throw(_("Unable to obtain PayPal payment URL"))
            
            # Update payment request with URL
            payment_request.payment_url = payment_url
            payment_request.status = "Initiated"
            payment_request.flags.ignore_permissions = True
            payment_request.save(ignore_permissions=True)

            return {
                "status": "success",
                "payment_url": payment_url
            }
            
        except Exception as inner_e:
            frappe.log_error("Error creating PayPal payment URL", str(inner_e))
            raise inner_e
            
    except Exception as e:
        frappe.log_error("Error creating PayPal payment request", e)
        return {
            "status": "error",
            "message": str(e)
        }

@frappe.whitelist(allow_guest=True)
def handle_payment_success(payment_request_id, transaction_data=None):
    """Handle payment success with Stripe"""
    try:
        handler = PaymentHandler()
        return handler.handle_payment_success(payment_request_id=payment_request_id, transaction_data=transaction_data)
    except Exception as e:
        frappe.log_error("Detailed error while processing payment", e)
        return {
            "status": "error",
            "message": _("Error processing payment")
        }

@frappe.whitelist(allow_guest=True)
def handle_payment_failure(payment_request_id, error_message=None):
    """Handle payment failure"""
    try:
        handler = PaymentHandler()
        return handler.handle_payment_failure(payment_request_id, error_message)
    except Exception as e:
        frappe.log_error("Detailed error while processing payment failure", e)
        return {
            "status": "error",
            "message": _("Error processing payment failure")
        }

@frappe.whitelist(allow_guest=True)
def handle_direct_order():
    """Handle direct order validation without payment"""
    try:
        handler = PaymentHandler()
        return handler.handle_direct_order()
    except Exception as e:
        frappe.log_error("Error while validating order", str(e))
        return {
            "status": "error",
            "message": _("An error occurred while validating the order")
        }

@frappe.whitelist(allow_guest=True)
def payment_callback():
    """Endpoint for receiving payment gateway callbacks"""
    try:
        data = frappe.request.get_json()
        payment_method = frappe.request.headers.get("X-Payment-Method")
        
        if not payment_method:
            frappe.throw(_("Payment method not specified"))
            
        # Verify signature according to gateway
        verify_payment_signature(payment_method, data)
        
        handler = PaymentHandler()
        
        if data.get("status") == "success":
            return handler.handle_payment_success(
                data.get("payment_request_id"),
                transaction_data=data
            )
        else:
            return handler.handle_payment_failure(
                data.get("payment_request_id"),
                error_message=data.get("error_message")
            )
            
    except Exception as e:
        frappe.log_error("Detailed error in payment callback", e)
        return {
            "status": "error",
            "message": _("Error processing payment callback")
        }

def verify_payment_signature(payment_method, data):
    """Verify payment signature according to method"""
    try:
        # Get payment method and its configuration
        settings = frappe.get_doc("Webshop Settings")
        payment_method_doc = None
        for pm in settings.get("payment_methods", []):
            if pm.name == payment_method:
                payment_method_doc = pm
                break
                
        if not payment_method_doc:
            frappe.throw(_("Payment method not found"))
            
        gateway = frappe.get_doc("Payment Gateway Account", payment_method_doc.payment_gateway_account)
        
        # Get gateway type and its configuration
        gateway_type = gateway.payment_gateway.split('-')[0].split()[0].lower().strip()
        gateway_config = get_gateway_configuration(gateway_type)
        
        # Import and use gateway-specific verification module
        module_name = f"payments.payment_gateways.{gateway_type}_integration"
        verify_function = f"verify_{gateway_type}_signature"
        
        module = frappe.get_module(module_name)
        if hasattr(module, verify_function):
            getattr(module, verify_function)(data, gateway_config)
        else:
            frappe.throw(_("Verification function not found for {0}").format(gateway.payment_gateway))
            
    except Exception as e:
        frappe.log_error("Signature verification error", e)
        frappe.throw(_("Invalid payment signature"))
