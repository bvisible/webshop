# //// Neoffice — added file (no upstream equivalent). Server side of the PayPal tile:
# //// creates the Payment Request, guarded by the idempotency token so a double click
# //// cannot raise two charges (f3f669f6f3, 2025-02-11 "move PayPal payment handling
# //// to dedicated module"; token 0033eef43d).
import frappe
from frappe import _

# //// Neoffice — the quotation is saved with the shop's rights (#277): upstream v15.123.0 reads the
# //// Item on the SESSION user whenever a line is priced (41effcf754)
from webshop.webshop.shopping_cart.shop_rights import save_as_shop
from webshop.webshop.shopping_cart.cart import _get_cart_quotation
# //// Neoffice — the placeholder order a cart's payment request is raised on (pending_order.py).
from webshop.webshop.shopping_cart import pending_order

@frappe.whitelist(allow_guest=True)
def create_paypal_payment_request(quotation_id, idempotency_token=None):
    """Create a payment request for PayPal"""
    # //// Neoffice — the quotation must be the session's own cart, checked before the try below so the
    # //// refusal is not swallowed by its except (neoffice-maintenance#1764).
    cart = _get_cart_quotation()
    if not cart or cart.name != quotation_id:
        frappe.throw(_("Not Permitted"), frappe.PermissionError)
    try:
        # Check for idempotency token to prevent duplicate requests
        if idempotency_token:
            # Check if a payment request already exists with this token
            existing_pr = frappe.db.get_value(
                "Payment Request",
                {"custom_idempotency_token": idempotency_token},
                ["name", "status", "reference_name", "reference_doctype"],
                as_dict=True
            )
            
            if existing_pr:
                # If payment request exists and is not failed, return existing one
                if existing_pr.status != "Failed":
                    frappe.log_error(f"Duplicate PayPal payment request prevented. Token: {idempotency_token}", "Payment Idempotency")
                    
                    # //// Neoffice — the order, once it is a REAL one: until the money is in, the request points at
                    # //// the cart's placeholder order (pending_order.py). The lookup here read a `quotation`
                    # //// column that `Sales Order` does not have, so a second attempt raised instead of finding
                    # //// its request again.
                    sales_order = pending_order.confirmed_order(existing_pr)
                    if (
                        not sales_order
                        and pending_order.is_placeholder(existing_pr.reference_name)
                        and not pending_order.is_current(existing_pr.reference_name, cart)
                    ):
                        # the cart changed since: this request is for another amount
                        pending_order.release(cart.name)
                        existing_pr = None
                    
                    if sales_order:
                        return {
                            "status": "error",
                            "message": _("This order has already been processed. Order ID: {0}").format(sales_order),
                            "existing_order": sales_order
                        }
                    
                    # Get the payment URL from the existing payment request
                    pr_doc = frappe.get_doc("Payment Request", existing_pr.name) if existing_pr else None
                    if pr_doc and pr_doc.payment_url:
                        return {
                            "status": "success",
                            "payment_url": pr_doc.payment_url
                        }
                        
        # Rest of the code continues...
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
                # //// Neoffice — save_as_shop, not a plain save (#277): validate prices every line, and upstream v15.123.0 reads the Item there on the SESSION user (41effcf754), which the buyer may not
                save_as_shop(quotation, ignore_permissions=True)
                
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
                    save_as_shop(quotation, ignore_permissions=True)  # //// Neoffice — see above (#277)
                break
        
        # //// Neoffice — raised on the cart's PLACEHOLDER order, not on the quotation: upstream ERPNext refuses a
        # //// Payment Request against a Quotation (pending_order.py). A request raised before that change still
        # //// points at the quotation, and is found as before.
        carrier = pending_order.carrier_for(quotation)

        # Check if payment request already exists
        # //// Neoffice — on the placeholder order, or (raised before it existed) on the quotation: two lookups, not
        # //// `or_filters` with a dict each, which Frappe reads by its FIRST key only (it dropped `reference_name`:
        # //// any paid request on any order answered "already paid").
        payment_request = frappe.get_all(
            "Payment Request",
            filters={"docstatus": 1, "reference_doctype": "Sales Order", "reference_name": carrier},
            limit=1
        ) or frappe.get_all(
            "Payment Request",
            filters={"docstatus": 1, "reference_doctype": "Quotation", "reference_name": quotation.name},
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
                pr_data = {
                    "doctype": "Payment Request",
                    "payment_request_type": "Inward",
                    "transaction_date": frappe.utils.now(),
                    "reference_doctype": "Sales Order",
                    "reference_name": carrier,
                    "company": quotation.company,
                    "grand_total": quotation.rounded_total,
                    "currency": quotation.currency,
                    "email_to": quotation.contact_email,
                    "payment_gateway": payment_gateway_account.payment_gateway,
                    "payment_gateway_account": payment_gateway_account.name,
                    "status": "Draft",
                    "party_type": "Customer",
                    "party": quotation.party_name,
                    "from_checkout": 1
                }
                # Add idempotency token if provided
                if idempotency_token:
                    pr_data["custom_idempotency_token"] = idempotency_token
                    
                payment_request = frappe.get_doc(pr_data)
                payment_request.flags.ignore_permissions = True
                # //// Neoffice — save_as_shop: upstream's validate reads the order the request is raised on
                # //// with the SESSION user's rights, which a customer or a visitor does not have on an order.
                save_as_shop(payment_request, ignore_permissions=True)
        else:
            # Create new payment request
            pr_data = {
                "doctype": "Payment Request",
                "payment_request_type": "Inward",
                "transaction_date": frappe.utils.now(),
                "reference_doctype": "Sales Order",
                "reference_name": carrier,
                "company": quotation.company,
                "grand_total": quotation.rounded_total,
                "currency": quotation.currency,
                "email_to": quotation.contact_email,
                "payment_gateway": payment_gateway_account.payment_gateway,
                "payment_gateway_account": payment_gateway_account.name,
                "status": "Draft",
                "party_type": "Customer",
                "party": quotation.party_name,
                "from_checkout": 1
            }
            # Add idempotency token if provided
            if idempotency_token:
                pr_data["custom_idempotency_token"] = idempotency_token
                
            payment_request = frappe.get_doc(pr_data)
            payment_request.flags.ignore_permissions = True
            # //// Neoffice — save_as_shop, see above
            save_as_shop(payment_request, ignore_permissions=True)
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
                "payment_gateway": payment_gateway_account.payment_gateway,
                "payment_gateway_account": payment_gateway_account.name,
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
            # //// Neoffice — save_as_shop: the validate of a Payment Request reads the order it is raised on with
            # //// the SESSION user's rights, on every save, not only the first (pending_order.py).
            save_as_shop(payment_request, ignore_permissions=True)

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