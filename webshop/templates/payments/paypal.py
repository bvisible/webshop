import frappe
from frappe import _

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