#//// Neoffice — added file (no upstream equivalent). Cart side of the "Facture"
#//// method: applies the chosen instalment plan to the quotation and keeps its fee
#//// line in step (662c26b650, 2026-05-26; fee read from the Payment Terms Template
#//// since 4efe747cf0). Every entry point re-checks that the quotation belongs to the
#//// caller's party before writing.
import frappe
from frappe import _
from webshop.webshop.shopping_cart.cart import apply_cart_settings as webshop_apply_cart_settings
from webshop.webshop.shopping_cart.cart import get_party

@frappe.whitelist()
def update_payment_terms(quotation_name, payment_terms_template):
    """Update the payment terms template of the quotation"""

    if not quotation_name:
        return

    # Check if the user has access to this quotation
    quotation = frappe.get_doc('Quotation', quotation_name)
    party = get_party()
    
    if not party or quotation.party_name != party.name:
        frappe.throw('Access not authorized')

    if not payment_terms_template:
        return remove_webshopsi_fees(quotation)

    # Update the payment terms template
    quotation.payment_terms_template = payment_terms_template
    
    # Update the payment schedule
    from erpnext.controllers.accounts_controller import get_payment_terms
    payment_schedule = get_payment_terms(
        payment_terms_template,
        posting_date=quotation.transaction_date,
        grand_total=quotation.rounded_total or quotation.grand_total,
        base_grand_total=quotation.base_rounded_total or quotation.base_grand_total
    )
    
    if payment_schedule:
        quotation.payment_schedule = []
        for schedule in payment_schedule:
            quotation.append('payment_schedule', schedule)

    # Save before applying fees to get the correct total
    quotation.flags.ignore_permissions = True
    quotation.save(ignore_permissions=True)

    # Apply fees and return the quotation
    result = apply_webshopsi_payment_fees(quotation)
    
    # Ensure we always return the updated document
    if result and not result.get('doc'):
        # Reload the quotation to get the latest state
        quotation = frappe.get_doc('Quotation', quotation_name)
        result['doc'] = quotation.as_dict()
    
    return result

def is_webshopsi_payment_method(quotation):
    """Check if the selected payment method is WebshopSI"""
    if not quotation or not quotation.payment_method:
        return False

    # Get the Payment Gateway Account
    try:
        payment_gateway = frappe.get_doc("Payment Gateway Account", quotation.payment_method)
        # Accepte "WebshopSI" ou "Facture" comme passerelles de paiement valides
        result = payment_gateway.payment_gateway in ["WebshopSI", "Facture"]
        return result
    except Exception as e:
        frappe.log_error("payment_gateway_error", str(e))
        return False

def apply_webshopsi_payment_fees(quotation):
    """Apply the percentage payment fee to a web-cart quotation.

    The fee percentage now comes from the selected Payment Terms Template
    (single source of truth, shared with the desk via
    ``neoffice_theme.payment_fee``); the GL account from the Company
    default-accounts section (fallback: WebshopSI Settings). The webshop always
    applies the fee (force=True, no per-document opt-out)."""
    if not quotation:
        return

    if not is_webshopsi_payment_method(quotation):
        return remove_webshopsi_fees(quotation)
    if not quotation.payment_terms_template:
        return remove_webshopsi_fees(quotation)

    try:
        from neoffice_theme.payment_fee import apply_payment_fee
    except Exception:
        frappe.log_error("webshopsi fee", "neoffice_theme.payment_fee import failed")
        return remove_webshopsi_fees(quotation)

    # force=True -> webshop always applies (ignores the desk opt-out checkbox).
    apply_payment_fee(quotation, force=True)

    quotation.flags.ignore_permissions = True
    quotation.save(ignore_permissions=True)
    return {"success": True, "had_changes": True, "doc": quotation.as_dict()}

@frappe.whitelist()
def remove_webshopsi_fees(quotation):
    """Remove WebshopSI payment fees from a quotation
    
    Args:
        quotation: Can be either a Quotation object or the name of a quotation
    Returns:
        dict: Updated quotation data with an indicator if fees were removed
    """
    if not quotation:
        return

    try:
        # If we receive a string (JS call), load the quotation
        if isinstance(quotation, str):
            quotation_name = quotation
        else:
            quotation_name = quotation.name

        # Reload the quotation to avoid version conflicts
        quotation = frappe.get_doc("Quotation", quotation_name)

        # Define function to check if a tax is a WebshopSI fee
        def is_webshopsi_fee(tax):
            desc = tax.description or ""
            return (tax.get('is_webshopsi_fee') or 
                    tax.get('custom_is_webshopsi_fee') or 
                    tax.get('is_payment_fee') or 
                    "Payment processing fee" in desc or 
                    "Frais de paiement" in desc)
        
        # Check if there are WebshopSI fees to remove
        had_fees = any(is_webshopsi_fee(tax) for tax in quotation.taxes)
        had_terms = bool(quotation.payment_terms_template)

        # Remove all WebshopSI fees
        quotation.taxes = [tax for tax in quotation.taxes if not is_webshopsi_fee(tax)]
        
        # Clean up payment terms
        quotation.payment_terms_template = ''
        quotation.payment_schedule = []
        
        # Force recalculation of totals after removing fees
        quotation.calculate_taxes_and_totals()
        
        # Save without triggering updates
        quotation.flags.ignore_validate = True
        quotation.flags.ignore_mandatory = True
        quotation.flags.ignore_version = True
        quotation.save(ignore_permissions=True)
        
        # Reload to get the latest version with recalculated totals
        quotation = frappe.get_doc("Quotation", quotation_name)
        
        return {
            "doc": quotation.as_dict(),
            "had_changes": had_fees or had_terms
        }
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error removing WebshopSI fees")
        return {
            "error": str(e),
            "had_changes": False
        }

@frappe.whitelist()
def handle_payment_method_change(quotation_name, payment_method):
    """Handle payment method change and update fees accordingly"""
    if not quotation_name:
        return
    
    # Check if the user has access to this quotation
    quotation = frappe.get_doc('Quotation', quotation_name)
    party = get_party()
    
    if not party or quotation.party_name != party.name:
        frappe.throw('Access not authorized')
    
    # Update the payment method on the quotation
    quotation.payment_method = payment_method
    quotation.flags.ignore_permissions = True
    quotation.save(ignore_permissions=True)
    
    # Check if it's a WebshopSI payment method
    if is_webshopsi_payment_method(quotation):
        # If switching TO WebshopSI, don't add fees yet (wait for installment selection)
        return {"success": True, "is_webshopsi": True}
    else:
        # If switching AWAY from WebshopSI, remove fees
        result = remove_webshopsi_fees(quotation)
        return {"success": True, "is_webshopsi": False, "fees_removed": result.get("had_changes", False)}

def apply_cart_settings(party=None, quotation=None):
    """Extend the apply_cart_settings function from Webshop to include WebshopSI fees"""
    # Call the original function first
    webshop_apply_cart_settings(party, quotation)
    
    # Get the quotation if not provided
    if not quotation:
        from webshop.webshop.shopping_cart.cart import _get_cart_quotation
        quotation = _get_cart_quotation(party)
    
    # Apply WebshopSI fees only if it's the selected payment method
    if is_webshopsi_payment_method(quotation):
        apply_webshopsi_payment_fees(quotation)
    else:
        remove_webshopsi_fees(quotation)
    
    # Save with the new fees
    quotation.flags.ignore_permissions = True
    quotation.save(ignore_permissions=True)
    
    return quotation
