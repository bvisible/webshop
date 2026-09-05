# //// Neoffice — added file (no upstream equivalent). Computes the points a cart would
# //// earn, for the "you will earn N points" line (6fea19b1fe, 2025-06-17).
# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt

def get_loyalty_points_for_cart(doc):
    """
    Calculate total loyalty points that will be earned for a cart/quotation
    
    Args:
        doc: Quotation document
        
    Returns:
        dict with points and value information
    """
    settings = frappe.get_single("Webshop Settings")
    
    if not settings.enable_loyalty_points or not settings.loyalty_program:
        return None
        
    # Check if we should show for guests
    if frappe.session.user == "Guest" and not settings.show_loyalty_points_for_guests:
        return None
        
    try:
        loyalty_program = frappe.get_doc("Loyalty Program", settings.loyalty_program)
    except frappe.DoesNotExistError:
        return None
        
    # Get the appropriate collection factor
    collection_factor = 0
    if loyalty_program.collection_rules:
        # Sort rules by min_spent to get the right tier
        tier_rules = sorted(
            loyalty_program.collection_rules,
            key=lambda rule: rule.min_spent if hasattr(rule, 'min_spent') else 0
        )
        
        # For simplicity, use the first tier (lowest min_spent requirement)
        if tier_rules:
            collection_factor = flt(tier_rules[0].collection_factor, 2)
    
    if not collection_factor:
        collection_factor = 1.0
        
    # Calculate points based on grand total
    grand_total = flt(doc.grand_total) if doc.grand_total else 0
    points_to_earn = int(grand_total / collection_factor) if collection_factor else 0
    
    # Calculate monetary value of points
    points_value = 0
    if loyalty_program.conversion_factor and points_to_earn:
        points_value = flt(points_to_earn) * flt(loyalty_program.conversion_factor)
        
    # Get currency
    currency = doc.currency or frappe.get_cached_value("Company", loyalty_program.company, "default_currency") or "CHF"
    
    # Format the conversion text if available
    conversion_text = ""
    if points_to_earn and points_value and settings.loyalty_points_conversion_text:
        from webshop.webshop.utils.utils import format_currency_value
        conversion_text = settings.loyalty_points_conversion_text
        conversion_text = conversion_text.replace("{points}", str(points_to_earn))
        conversion_text = conversion_text.replace("{amount}", format_currency_value(points_value, currency=currency))
        
    return {
        "points_to_earn": points_to_earn,
        "points_value": points_value,
        "collection_factor": collection_factor,
        "currency": currency,
        "loyalty_program_name": loyalty_program.loyalty_program_name,
        "conversion_text": conversion_text
    }