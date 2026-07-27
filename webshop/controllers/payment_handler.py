import frappe
from frappe import _
import json
from webshop.webshop.shopping_cart.cart import place_order, _get_cart_quotation, is_gift_card_item
from erpnext.accounts.doctype.payment_request.payment_request import make_payment_entry

class PaymentHandler:
    def __init__(self):
        self.settings = frappe.get_doc("Webshop Settings")
        
    def create_payment_request(self, quotation_id=None, gateway_settings=None, idempotency_token=None):
        """Create a payment request for a quotation
        
        Args:
            quotation_id (str, optional): ID of the quotation. If not provided, uses the cart.
            gateway_settings (str, optional): Name of the Gateway Settings to use. If provided, bypasses the default payment method.
            idempotency_token (str, optional): Token to prevent duplicate payment requests.
        """
        try:
            # Check for idempotency token to prevent duplicate requests
            if idempotency_token:
                # Check if a payment request already exists with this token
                existing_pr = frappe.db.get_value(
                    "Payment Request",
                    {"custom_idempotency_token": idempotency_token},
                    ["name", "status", "reference_name"],
                    as_dict=True
                )
                
                if existing_pr:
                    # If payment request exists and is not failed, return existing one
                    if existing_pr.status != "Failed":
                        frappe.log_error(f"Duplicate payment request prevented. Token: {idempotency_token}", "Payment Idempotency")
                        
                        # Check if a Sales Order was already created for this quotation
                        sales_order = frappe.db.get_value(
                            "Sales Order",
                            {"quotation": existing_pr.reference_name},
                            "name"
                        )
                        
                        if sales_order:
                            return {
                                "status": "error",
                                "message": _("This order has already been processed. Order ID: {0}").format(sales_order),
                                "existing_order": sales_order
                            }
                        
                        return {
                            "status": "success",
                            "payment_request_id": existing_pr.name,
                            "message": _("Using existing payment request")
                        }
            # if not quotation, get cart quotation
            if not quotation_id:
                quotation = _get_cart_quotation()
                if not quotation:
                    frappe.log_error(_("Cart Error"), _("Error during quotation retrieval: Cart is empty or quotation not found"))
                    frappe.throw(_("Cart is empty"))
            else:
                quotation = frappe.get_doc("Quotation", quotation_id)
            
            # Get webshop parameters
            settings = frappe.get_cached_doc("Webshop Settings")
            
            # Initialize payment variables
            payment_method = None
            payment_method_doc = None
            gateway_account = None
            payment_terms_template = None
            
            # If gateway_settings is provided, use it directly
            if gateway_settings:
                # Get Payment Gateway
                gateway = frappe.get_value("Payment Gateway", {"gateway_settings": gateway_settings}, "name")
                if not gateway:
                    frappe.throw(_("Payment Gateway not found for settings: {0}").format(gateway_settings))
                    
                # Get Payment Gateway Account
                gateway_account = frappe.get_doc("Payment Gateway Account", {"payment_gateway": gateway})
                
                # Get the payment method from webshop settings based on the gateway name
                # Extract the payment method name (part before the dash if any)
                payment_method_name = gateway.split("-")[0].strip()
                
                # Find matching payment method in webshop settings
                for method in settings.payment_methods:
                    if method.payment_gateway_account.startswith(payment_method_name):
                        payment_terms_template = method.payment_terms_template
                        break
                
            else:
                # Use default payment method
                payment_method = self.get_default_payment_method()
                payment_method_doc = frappe.get_doc("Webshop Payment Method", payment_method)
                payment_terms_template = payment_method_doc.payment_terms_template
                # Get payment gateway account
                gateway_account = frappe.get_doc("Payment Gateway Account", payment_method_doc.payment_gateway_account)
            
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
            
            # Update payment_terms_template 
            if payment_terms_template:
                quotation.payment_terms_template = payment_terms_template
                quotation.save(ignore_permissions=True)
                
                # Get and update payment schedule
                from erpnext.controllers.accounts_controller import get_payment_terms
                payment_schedule = get_payment_terms(
                    payment_terms_template,
                    posting_date=quotation.transaction_date,
                    grand_total=quotation.rounded_total or quotation.grand_total,
                    base_grand_total=quotation.base_rounded_total or quotation.base_grand_total
                )
                if payment_schedule:
                    quotation.set("payment_schedule", payment_schedule)
                    quotation.save(ignore_permissions=True)

            # Create context for payment request
            context = {
                "reference_doctype": "Quotation",
                "reference_name": quotation.name,
                "amount": quotation.rounded_total,
                "currency": quotation.currency,
                "payment_gateway": gateway_account.payment_gateway
            }
            
            # Prepare data for template
            context.update({
                "payment_method": payment_method,
                "callback_url": frappe.utils.get_url("/api/payment/callback"),
            })
            
            # Create payment request with transaction date
            pr_data = {
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
            }
            
            # Add idempotency token if provided
            if idempotency_token:
                pr_data["custom_idempotency_token"] = idempotency_token
            
            payment_request = frappe.get_doc(pr_data)
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
            # Bypass all permission checks - payment is confirmed by payment provider
            # We need to run as Administrator because get_mapped_doc checks permissions
            frappe.set_user("Administrator")
            frappe.flags.ignore_permissions = True

            # Get and validate payment request
            payment_request_id = kwargs.get('payment_request_id')
            if not payment_request_id:
                return self.handle_error("Missing payment request ID")

            payment_request = frappe.get_doc("Payment Request", payment_request_id)
            payment_request.flags.ignore_permissions = True
            self.payment_request = payment_request

            # Submit payment request now that payment is successful
            if payment_request.docstatus == 0:  # If not already submitted
                payment_request.flags.ignore_permissions = True
                payment_request.submit()
            
            # Check if payment request is already processed - redirect to thank you page
            if payment_request.status in ["Paid", "Completed"]:
                # Already processed, find the Sales Order and redirect
                if payment_request.reference_doctype == "Sales Order":
                    return {
                        "status": "success",
                        "redirect_to": f"/thank_you?sales_order={payment_request.reference_name}",
                        "message": _("Payment already processed")
                    }
                return {"status": "success", "message": _("Payment already processed")}

            # Concurrent-finalize guard: a second call (e.g. the TWINT poller
            # racing the consumer redirect / simulate) can arrive after the
            # first one already swapped the PR reference from the Quotation to
            # the created Sales Order. In that case the order is being
            # finalised by the other call — treat it as already processed
            # instead of trying to load the Sales Order name as a Quotation
            # (which would raise "Quotation <SO> not found").
            if payment_request.reference_doctype == "Sales Order":
                return {
                    "status": "success",
                    "redirect_to": f"/thank_you?sales_order={payment_request.reference_name}",
                    "message": _("Payment already processed")
                }

            # 1. Get quotation
            quotation = frappe.get_doc("Quotation", payment_request.reference_name)
            quotation.flags.ignore_permissions = True
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
                limit=1,
                ignore_permissions=True
            )

            if linked_docs:
                sales_order_name = linked_docs[0].name
            else:
                # Submit quotation first if not already submitted (required for make_sales_order)
                if quotation.docstatus == 0:
                    quotation.flags.ignore_permissions = True
                    quotation.submit()

                # Use make_sales_order from quotation
                from erpnext.selling.doctype.quotation.quotation import make_sales_order
                sales_order = make_sales_order(quotation.name)
                sales_order.flags.ignore_permissions = True
                sales_order.order_type = "Shopping Cart"

                # Update transaction_date to today and recalculate payment schedule
                # This fixes the "Due Date cannot be before Posting Date" error
                # when quotation was created on a previous day
                today = frappe.utils.today()
                sales_order.transaction_date = today
                sales_order.delivery_date = today
                # Clear and recalculate payment schedule with today's date
                if sales_order.payment_schedule:
                    for ps in sales_order.payment_schedule:
                        if ps.due_date and str(ps.due_date) < today:
                            ps.due_date = today

                # Preserve gift card discount from quotation
                if quotation.discount_amount:
                    sales_order.apply_discount_on = quotation.apply_discount_on or "Grand Total"
                    sales_order.discount_amount = quotation.discount_amount

                # Preserve gift card coupon code if quotation has one
                if hasattr(quotation, 'gift_card_coupon') and quotation.gift_card_coupon:
                    coupon_code = quotation.gift_card_coupon
                    if frappe.db.exists("Coupon Code", coupon_code):
                        sales_order.coupon_code = coupon_code

                sales_order.submit()
                sales_order_name = sales_order.name

                if not sales_order_name:
                    return self.handle_error("Error creating order")
                            
            # 3. Update Payment Request with Sales Order reference
            payment_request.db_set('reference_doctype', 'Sales Order', update_modified=False)
            payment_request.db_set('reference_name', sales_order_name, update_modified=False)
        
            # 4. Mark the Payment Request as paid.
            #    ERPNext's Payment Request no longer exposes
            #    ``on_payment_authorized`` (it was removed in a recent upgrade),
            #    so the previous ``run_method("on_payment_authorized", ...)``
            #    became a SILENT no-op — the PR stayed "Requested" forever even
            #    though the PSP (Stripe / Wallee / TWINT) had captured the money.
            #    The payment itself is tracked on the Payment Intent; the
            #    created Sales Order drives downstream invoicing/delivery. Here
            #    we only need the PR to reflect Paid (same end state as the old
            #    on_payment_authorized -> set_as_paid for "Phone" channel).
            try:
                if payment_request.status not in ("Paid", "Completed"):
                    payment_request.db_set(
                        {"status": "Paid", "outstanding_amount": 0},
                        update_modified=False,
                    )
            except Exception as e:
                frappe.log_error("Error marking Payment Request as paid", f"{e}\n{frappe.get_traceback()}")
                return self.handle_error(str(e))
            
            # 5. Invoice the order and book the money in.
            #    The PSP has already captured the funds at this point. Until
            #    this call existed the flow stopped at the Sales Order: the
            #    order stayed "To Bill" forever and the cash never reached the
            #    ledger. `handle_direct_order` (unpaid orders) always invoiced,
            #    so PAID orders were the only ones left unbilled.
            self._invoice_paid_order(sales_order_name, payment_request)

            # Build default success URL
            success_url = f"/thank_you?sales_order={sales_order_name}"
            
            return {
                "status": "success",
                "redirect_to": success_url,
                "message": _("Payment processed successfully")
            }
            
        except Exception as e:
            frappe.log_error(message=f"{str(e)}\n{frappe.get_traceback()}", title="Detailed error while processing payment")
            return {
                "status": "error",
                "message": _("Error processing payment")
            }

    def _invoice_paid_order(self, sales_order_name, payment_request):
        """Create and submit the Sales Invoice + Payment Entry for a paid order.

        Best effort by design: the money is already captured by the PSP, so a
        bookkeeping failure must never break the buyer's confirmation page nor
        roll back the order. Failures are logged for manual follow-up.
        """
        try:
            sales_order = frappe.get_doc("Sales Order", sales_order_name)
            if (sales_order.per_billed or 0) >= 100:
                # Already invoiced (retry, duplicate webhook, manual billing).
                return

            from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice

            invoice = make_sales_invoice(sales_order_name, ignore_permissions=True)
            invoice.allocate_advances_automatically = True
            invoice.flags.ignore_permissions = True
            invoice.insert(ignore_permissions=True)
            invoice.submit()

            self._record_gateway_payment(invoice, payment_request, sales_order.company)
        except Exception as e:
            frappe.log_error(
                "Webshop: invoicing a paid order failed",
                f"sales_order={sales_order_name} payment_request={payment_request.name}\n"
                f"{e}\n{frappe.get_traceback()}",
            )

    def _record_gateway_payment(self, invoice, payment_request, company):
        """Book the captured amount against `invoice`, on the gateway account."""
        gateway_account = frappe.db.get_value(
            "Payment Gateway Account",
            payment_request.payment_gateway_account,
            ["payment_account", "payment_gateway"],
            as_dict=True,
        ) if payment_request.payment_gateway_account else None

        if not gateway_account or not gateway_account.payment_account:
            frappe.log_error(
                "Webshop: no gateway account, invoice left unpaid",
                f"invoice={invoice.name} payment_request={payment_request.name}",
            )
            return

        # The Mode of Payment is the one wired to the same clearing account
        # (e.g. "Twint" -> "1036 Compte d'attente Twint").
        mode_of_payment = frappe.db.get_value(
            "Mode of Payment Account",
            {"default_account": gateway_account.payment_account, "company": company},
            "parent",
        )

        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        entry = get_payment_entry("Sales Invoice", invoice.name)
        entry.paid_to = gateway_account.payment_account
        if mode_of_payment:
            entry.mode_of_payment = mode_of_payment
        entry.reference_no = payment_request.name
        entry.reference_date = frappe.utils.today()
        entry.remarks = f"Webshop payment via {gateway_account.payment_gateway} ({payment_request.name})"
        entry.flags.ignore_permissions = True
        entry.insert(ignore_permissions=True)
        entry.submit()

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

    def handle_direct_order(self, idempotency_token=None):
        """Handle direct order validation without payment"""
        try:
            # Check for existing order with idempotency token
            if idempotency_token:
                # Check in cache or database for existing order with this token
                cache_key = f"direct_order_{idempotency_token}"
                existing_order = frappe.cache().get_value(cache_key)
                
                if existing_order:
                    frappe.log_error(f"Duplicate direct order prevented. Token: {idempotency_token}", "Order Idempotency")
                    return {
                        "status": "error",
                        "message": _("This order has already been processed. Order ID: {0}").format(existing_order),
                        "existing_order": existing_order
                    }
            # Create sales order
            from webshop.webshop.shopping_cart.cart import place_order
            sales_order_name = place_order()
            
            if not sales_order_name:
                return {
                    "status": "error",
                    "message": _("Error creating order")
                }
            
            # Store order in cache with idempotency token
            if idempotency_token:
                cache_key = f"direct_order_{idempotency_token}"
                # Store for 24 hours
                frappe.cache().set_value(cache_key, sales_order_name, expires_in_sec=86400)
            
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
def create_payment_request(quotation_id=None, gateway_settings=None, idempotency_token=None):
    """Create a payment request for a quotation
    
    Args:
        quotation_id (str, optional): Quotation ID
        gateway_settings (str, optional): Gateway Settings name
        idempotency_token (str, optional): Token to prevent duplicate payment requests
    """
    try:
        handler = PaymentHandler()
        return handler.create_payment_request(
            quotation_id=quotation_id, 
            gateway_settings=gateway_settings,
            idempotency_token=idempotency_token
        )
    except Exception as e:
        frappe.log_error("Error creating payment request", e)
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
def handle_direct_order(idempotency_token=None):
    """Handle direct order validation without payment"""
    try:
        handler = PaymentHandler()
        return handler.handle_direct_order(idempotency_token=idempotency_token)
    except Exception as e:
        frappe.log_error("Error while validating order", str(e))
        return {
            "status": "error",
            "message": _("An error occurred while validating the order")
        }
