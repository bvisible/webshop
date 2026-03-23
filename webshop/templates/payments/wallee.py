import frappe
from frappe import _


@frappe.whitelist(allow_guest=True)
def get_payment_mode():
    """Get the configured payment mode from Wallee Settings"""
    try:
        wallee_settings = frappe.get_single("Wallee Settings")
        return wallee_settings.payment_mode or "Redirect"
    except Exception:
        return "Redirect"


@frappe.whitelist(allow_guest=True)
def create_wallee_payment_request(quotation_id, idempotency_token=None):
    """Create a payment request for Wallee"""
    try:
        # Check for idempotency token to prevent duplicate requests
        if idempotency_token:
            existing_pr = frappe.db.get_value(
                "Payment Request",
                {"custom_idempotency_token": idempotency_token},
                ["name", "status", "reference_name"],
                as_dict=True
            )

            if existing_pr:
                if existing_pr.status != "Failed":
                    frappe.log_error(
                        f"Duplicate Wallee payment request prevented. Token: {idempotency_token}",
                        "Payment Idempotency"
                    )

                    # Check if a Sales Order was already created
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

                    # Get the payment URL from existing payment request
                    pr_doc = frappe.get_doc("Payment Request", existing_pr.name)
                    if pr_doc.payment_url:
                        return {
                            "status": "success",
                            "payment_url": pr_doc.payment_url
                        }

        # Get quotation
        quotation = frappe.get_doc("Quotation", quotation_id)

        # Get Wallee payment gateway account
        settings = frappe.get_cached_doc("Webshop Settings")
        payment_gateway_account = None
        payment_terms_template = None
        wallee_payment_method_id = None

        for method in settings.payment_methods:
            pga = frappe.get_doc("Payment Gateway Account", method.payment_gateway_account)
            pg = frappe.get_doc("Payment Gateway", pga.payment_gateway)
            gateway_type = pg.gateway.lower().strip()

            if "wallee" in gateway_type:
                payment_gateway_account = pga
                payment_terms_template = method.payment_terms_template
                # Get the specific payment method ID if configured
                wallee_payment_method_id = getattr(pga, "wallee_payment_method_id", None)
                break

        if not payment_gateway_account:
            frappe.throw(_("Wallee payment gateway not configured"))

        # Update payment terms if configured
        if payment_terms_template:
            quotation.payment_terms_template = payment_terms_template
            quotation.save(ignore_permissions=True)

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

        # Check if payment request already exists
        existing_payment_request = frappe.get_all(
            "Payment Request",
            filters={
                "reference_doctype": "Quotation",
                "reference_name": quotation.name,
                "docstatus": 1
            },
            limit=1
        )

        if existing_payment_request:
            payment_request = frappe.get_doc("Payment Request", existing_payment_request[0].name)
            if payment_request.status == "Paid":
                frappe.throw(_("This order has already been paid"))
            elif payment_request.status == "Failed":
                # Cancel and delete existing failed payment request
                payment_request.flags.ignore_permissions = True
                frappe.db.set_value("Payment Request", payment_request.name, "docstatus", 2)
                frappe.db.commit()
                frappe.delete_doc("Payment Request", payment_request.name, ignore_permissions=True)
                frappe.db.commit()
                payment_request = None

        # Create new payment request if needed
        if not existing_payment_request or payment_request is None:
            pr_data = {
                "doctype": "Payment Request",
                "payment_request_type": "Inward",
                "transaction_date": frappe.utils.now(),
                "reference_doctype": "Quotation",
                "reference_name": quotation.name,
                "grand_total": quotation.rounded_total or quotation.grand_total,
                "currency": quotation.currency,
                "email_to": quotation.contact_email,
                "payment_gateway": payment_gateway_account.payment_gateway,
                "payment_gateway_account": payment_gateway_account.name,
                "status": "Draft",
                "party_type": "Customer",
                "party": quotation.party_name,
                "from_checkout": 1
            }

            if idempotency_token:
                pr_data["custom_idempotency_token"] = idempotency_token

            payment_request = frappe.get_doc(pr_data)
            payment_request.flags.ignore_permissions = True
            payment_request.insert(ignore_permissions=True)
            payment_request.save(ignore_permissions=True)

        # Create Wallee transaction and get payment URL
        try:
            wallee_settings = frappe.get_single("Wallee Settings")

            if not wallee_settings.enabled:
                frappe.throw(_("Wallee Integration is not enabled"))

            # Build success and failed URLs
            base_url = frappe.utils.get_url()
            success_url = f"{base_url}/wallee/success?payment_request={payment_request.name}"
            failed_url = f"{base_url}/wallee/failed?payment_request={payment_request.name}"

            # Create Wallee transaction
            from wallee_integration.wallee_integration.api.transaction import create_transaction

            # Build line items from quotation
            # Extract tax rates for TaxCreate (only percentage-based taxes, not Actual charges)
            from wallee_integration.wallee_integration.api.tax_utils import get_taxes_for_line_items
            taxes_data = get_taxes_for_line_items("Quotation", quotation.name)

            line_items = []
            for item in quotation.items:
                line_items.append({
                    "name": item.item_name or item.item_code,
                    "sku": item.item_code,
                    "quantity": item.qty,
                    "amount_including_tax": item.amount,
                    "type": "PRODUCT",
                    "taxes": taxes_data or None
                })

            # Add "Actual" charges as separate line items (shipping, fees, etc.)
            # These are charges NOT included in item prices (charge_type = "Actual")
            for tax_row in (quotation.taxes or []):
                if tax_row.charge_type == "Actual" and tax_row.tax_amount > 0:
                    # Determine if this is a shipping charge or a fee
                    desc_lower = (tax_row.description or "").lower()
                    is_shipping = any(kw in desc_lower for kw in ["ship", "post", "livraison", "envoi", "frais de port"])
                    line_type = "SHIPPING" if is_shipping else "FEE"
                    line_items.append({
                        "name": tax_row.description or _("Fee"),
                        "quantity": 1,
                        "amount_including_tax": tax_row.tax_amount,
                        "type": line_type
                    })

            # Build billing address from quotation data
            billing_address = None
            if quotation.contact_display or quotation.customer_address:
                billing_address = {
                    "email_address": quotation.contact_email
                }

                # Parse contact name (first name / last name)
                if quotation.contact_display:
                    name_parts = quotation.contact_display.strip().split(" ", 1)
                    billing_address["given_name"] = name_parts[0] if name_parts else ""
                    billing_address["family_name"] = name_parts[1] if len(name_parts) > 1 else ""

                # Get address details
                if quotation.customer_address:
                    try:
                        addr = frappe.get_doc("Address", quotation.customer_address)
                        billing_address["street"] = addr.address_line1
                        billing_address["city"] = addr.city
                        billing_address["postcode"] = addr.pincode
                        # Convert country name to ISO code (e.g., "Switzerland" -> "CH")
                        if addr.country:
                            country_code = frappe.db.get_value("Country", addr.country, "code")
                            billing_address["country"] = (country_code or "").upper()
                    except Exception:
                        pass  # Address not found, continue without it

            # Create transaction in Wallee
            wallee_response = create_transaction(
                amount=float(quotation.rounded_total or quotation.grand_total),
                currency=quotation.currency,
                customer_email=quotation.contact_email,
                customer_id=quotation.party_name,
                merchant_reference=payment_request.name,
                success_url=success_url,
                failed_url=failed_url,
                line_items=line_items,
                billing_address=billing_address
            )

            if not wallee_response or not wallee_response.get("transaction_id"):
                frappe.throw(_("Unable to create Wallee transaction"))

            wallee_transaction_id = wallee_response.get("transaction_id")

            # Get payment mode from settings (Redirect, Lightbox, or iFrame)
            payment_mode = wallee_settings.payment_mode or "Redirect"

            # Get the appropriate URL based on payment mode
            from wallee_integration.wallee_integration.api.transaction import (
                get_payment_page_url,
                get_lightbox_javascript_url,
                get_iframe_javascript_url
            )

            if payment_mode == "Lightbox":
                javascript_url = get_lightbox_javascript_url(wallee_transaction_id)
                payment_url = None  # No redirect for Lightbox
                payment_methods = None
            elif payment_mode == "iFrame":
                javascript_url = get_iframe_javascript_url(wallee_transaction_id)
                payment_url = None  # No redirect for iFrame
                # Get available payment methods for iFrame
                from wallee_integration.wallee_integration.api.transaction import get_payment_method_configurations
                try:
                    payment_methods = get_payment_method_configurations(wallee_transaction_id, "IFRAME")
                except Exception as e:
                    frappe.log_error(f"Error getting payment methods: {str(e)}", "Wallee Payment Methods")
                    payment_methods = []
            else:
                # Redirect mode (default)
                payment_url = wallee_response.get("payment_url") or get_payment_page_url(wallee_transaction_id)
                javascript_url = None
                payment_methods = None

            # Update payment request with Wallee data
            payment_request.payment_url = payment_url
            payment_request.status = "Initiated"
            payment_request.flags.ignore_permissions = True
            payment_request.save(ignore_permissions=True)

            # Create or update Wallee Transaction record
            existing_wallee_tx = frappe.db.get_value(
                "Wallee Transaction",
                {"reference_doctype": "Quotation", "reference_name": quotation.name},
                "name"
            )

            if existing_wallee_tx:
                wallee_tx = frappe.get_doc("Wallee Transaction", existing_wallee_tx)
                wallee_tx.transaction_id = str(wallee_transaction_id)
                wallee_tx.status = "Pending"
                wallee_tx.payment_request = payment_request.name
                wallee_tx.save(ignore_permissions=True)
            else:
                wallee_tx = frappe.get_doc({
                    "doctype": "Wallee Transaction",
                    "transaction_id": str(wallee_transaction_id),
                    "status": "Pending",
                    "transaction_type": "Online",
                    "amount": quotation.rounded_total or quotation.grand_total,
                    "currency": quotation.currency,
                    "reference_doctype": "Quotation",
                    "reference_name": quotation.name,
                    "customer": quotation.party_name,
                    "customer_name": quotation.customer_name,
                    "email": quotation.contact_email,
                    "merchant_reference": payment_request.name,
                    "payment_request": payment_request.name
                })
                wallee_tx.insert(ignore_permissions=True)

            frappe.db.commit()

            result = {
                "status": "success",
                "payment_mode": payment_mode,
                "payment_request": payment_request.name,
                "wallee_transaction": wallee_tx.name,
                "transaction_id": wallee_transaction_id
            }

            if payment_mode == "Redirect":
                result["payment_url"] = payment_url
            else:
                result["javascript_url"] = javascript_url
                if payment_mode == "iFrame":
                    # If a specific payment method ID is configured, use it directly
                    # Otherwise, use the first available method
                    if wallee_payment_method_id:
                        result["payment_method_id"] = wallee_payment_method_id
                    elif payment_methods:
                        result["payment_method_id"] = payment_methods[0].get("id")

            return result

        except Exception as inner_e:
            frappe.log_error(
                f"Error creating Wallee transaction: {str(inner_e)}",
                "Wallee Payment Error"
            )
            raise inner_e

    except Exception as e:
        frappe.log_error(f"Error creating Wallee payment request: {str(e)}", "Wallee Payment Error")
        return {
            "status": "error",
            "message": str(e)
        }
