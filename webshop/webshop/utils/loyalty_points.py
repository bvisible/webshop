# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, fmt_money


def get_loyalty_points_for_item(item_code, price, qty=1, customer=None):
    """
    Calculate loyalty points that would be earned for purchasing an item
    
    Args:
        item_code: Item code
        price: Item price
        qty: Quantity (default 1)
        customer: Customer name (optional)
    
    Returns:
        dict: {
            'points': Points that would be earned,
            'points_value': Monetary value of the points,
            'conversion_factor': Points per currency unit,
            'currency': Currency symbol
        }
    """
    settings = frappe.get_single("Webshop Settings")
    
    if not settings.enable_loyalty_points or not settings.loyalty_program:
        return None
    
    # Check if we should show for guests
    if not customer and not settings.show_loyalty_points_for_guests:
        return None
    
    try:
        loyalty_program = frappe.get_doc("Loyalty Program", settings.loyalty_program)
    except frappe.DoesNotExistError:
        frappe.log_error(
            message=f"Loyalty Program {settings.loyalty_program} not found",
            title="Loyalty program not found"
        )
        return None
    
    # Calculate points based on collection rules
    points = 0
    collection_factor = 0
    
    # Get the default collection rule (usually based on invoice amount)
    if loyalty_program.collection_rules:
        # Sort rules by min_spent to get the right tier
        # For webshop, we'll use the lowest tier (first echelon) for new customers
        tier_rules = sorted(
            loyalty_program.collection_rules,
            key=lambda rule: rule.min_spent if hasattr(rule, 'min_spent') else 0
        )
        
        # Use the first tier (lowest min_spent requirement)
        if tier_rules:
            rule = tier_rules[0]
            collection_factor = flt(rule.collection_factor, 2)
    else:
        # If no collection rules, use a default of 1 point per currency unit
        collection_factor = 1.0
    
    if collection_factor:
        # Calculate points: (price * qty) / collection_factor
        # If collection_factor = 3, it means 3 CHF = 1 point
        points = int(flt(price) * flt(qty) / collection_factor)
    
    # Get currency
    currency = frappe.get_cached_value("Company", loyalty_program.company, "default_currency") if loyalty_program.company else "USD"
    
    # Calculate monetary value of points using redemption conversion
    # Note: conversion_factor is for REDEMPTION (how much 1 point is worth in currency)
    # collection_factor is for EARNING (how many points per currency unit spent)
    points_value = 0
    if loyalty_program.conversion_factor:
        points_value = flt(points) * flt(loyalty_program.conversion_factor)
    
    result = {
        "points": points,
        "points_value": points_value,
        "collection_factor": collection_factor,
        "currency": currency,
        "loyalty_program_name": loyalty_program.loyalty_program_name
    }
    
    return result


def format_loyalty_points_message(item_code, price, qty=1, customer=None):
    """
    Format a message showing loyalty points for an item
    
    Returns:
        str: Formatted message or empty string if loyalty is disabled
    """

    points_data = get_loyalty_points_for_item(item_code, price, qty, customer)
    
    if not points_data or not points_data.get("points"):
        return ""
    
    settings = frappe.get_single("Webshop Settings")
    
    # Format the earned points message with both points and value
    points = points_data["points"]
    value = fmt_money(points_data["points_value"], currency=points_data["currency"])
    
    # Use the template from settings, with support for both {points} and {value}
    earned_text = settings.loyalty_points_earned_text or "Earn {points} points with this purchase"
    earned_text = earned_text.replace("{points}", str(points))
    earned_text = earned_text.replace("{value}", value)
    
    # Format the conversion text if there's a value
    conversion_text = ""
    if points_data.get("points_value") and settings.loyalty_points_conversion_text:
        conversion_text = settings.loyalty_points_conversion_text or "{points} points = {amount}"
        conversion_text = conversion_text.replace("{points}", str(points))
        conversion_text = conversion_text.replace("{amount}", value)
    
    result = {
        "earned_text": earned_text,
        "conversion_text": conversion_text,
        "points": points,
        "points_value": points_data["points_value"],
        "currency": points_data["currency"]
    }
    
    return result


@frappe.whitelist(allow_guest=True)
def get_item_loyalty_points(item_code, price=None, qty=1):
    """
    Web API to get loyalty points for an item
    """
    if not price:
        # Get item price if not provided
        item = frappe.get_doc("Item", item_code)
        # This is simplified - in reality you'd need to get the correct price list price
        price = item.standard_rate or 0
    
    customer = frappe.session.user if frappe.session.user != "Guest" else None
    
    return format_loyalty_points_message(item_code, price, qty, customer)