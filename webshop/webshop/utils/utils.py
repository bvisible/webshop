import frappe
import json

from frappe import _
from frappe.utils.data import fmt_money

@frappe.whitelist( allow_guest=True )
def format_currency_value(value, currency=None, precision=None):
    """Formats the 'value' with the provided currency and precision.
    
    Webshop setting 'hide_currency_symbol_in_shop' controls currency symbol display:
    - Empty/None: Use global ERPNext setting
    - 'Yes': Hide currency symbol
    - 'No': Show currency symbol
    """
    from frappe.utils import cint, flt, get_number_format_info
    
    # Cache the webshop settings lookup
    cache_key = "webshop_hide_currency_symbol"
    webshop_hide_symbol = frappe.cache().get_value(cache_key)
    
    if webshop_hide_symbol is None:
        # Get from database and cache for 1 hour
        webshop_settings = frappe.get_cached_doc("Webshop Settings")
        webshop_hide_symbol = webshop_settings.get("hide_currency_symbol_in_shop") or ""
        frappe.cache().set_value(cache_key, webshop_hide_symbol, expires_in_sec=3600)
    
    # Determine if we should hide the symbol
    if webshop_hide_symbol:
        # Webshop setting overrides global
        hide_symbol = (webshop_hide_symbol == "Yes")
    else:
        # Use global setting
        hide_symbol = frappe.defaults.get_global_default("hide_currency_symbol") == "Yes"
    
    # If we should hide the symbol, format without currency
    if hide_symbol:
        return fmt_money(value, precision=precision, currency=None)
    
    # If no currency specified, use standard formatting
    if not currency:
        return fmt_money(value, precision=precision, currency=currency)
    
    # Otherwise, we want to show the symbol
    # Format the number without currency first (to avoid double symbol issues)
    formatted_number = fmt_money(value, precision=precision, currency=None)
    
    # Add currency symbol manually
    symbol = frappe.db.get_value("Currency", currency, "symbol", cache=True) or currency
    symbol_on_right = frappe.db.get_value("Currency", currency, "symbol_on_right", cache=True)
    
    if symbol_on_right:
        return f"{formatted_number} {symbol}"
    else:
        return f"{symbol} {formatted_number}"

def get_gateway_configuration(payment_method, payment_gateway_account=None):
    """Gets the JSON configuration for a given payment method
    
    Args:
        payment_method (str): Payment method type (e.g., 'paypal', 'stripe')
        payment_gateway_account (str, optional): Payment Gateway Account name to check for custom template path
    """
    try:
        # Check for custom template path in payment method
        config_path = None
        if payment_gateway_account:
            webshop_method = frappe.get_doc("Webshop Payment Method", {"payment_gateway_account": payment_gateway_account})
            if webshop_method.get("template_path"):
                # Get the JSON file from the same location as the template
                template_path = webshop_method.template_path
                if template_path.startswith('apps/'):
                    # Remove apps/ prefix and .html extension, add .json
                    path_parts = template_path[5:].rsplit('.', 1)[0].split('/')
                    # Remove duplicate app name if present
                    if len(path_parts) > 1 and path_parts[0] == path_parts[1]:
                        path_parts.pop(1)
                    json_path = '/'.join(path_parts) + '.json'
                    config_path = frappe.get_app_path(*json_path.split('/'))
                else:
                    # Default webshop location
                    config_path = frappe.get_app_path("webshop", "templates", "payments", f"{payment_method}.json")
        
        # If no custom path or not found, use default
        if not config_path:
            config_path = frappe.get_app_path("webshop", "templates", "payments", f"{payment_method}.json")
            
        with open(config_path, "r") as f:
            return json.load(f)
    except Exception as e:
        frappe.log_error(f"Error reading payment configuration: {str(e)}")
        return {}

@frappe.whitelist( allow_guest=True )
def get_first_name(user):
    return frappe.db.get_value("User", user, "first_name")

def webshop_fmt_money(value, currency=None, precision=None):
    """
    Template helper function for formatting money in webshop templates.
    This is a wrapper around format_currency_value that can be used directly in Jinja templates.
    """
    return format_currency_value(value, currency=currency, precision=precision)
