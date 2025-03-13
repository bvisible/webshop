import frappe
import json

from frappe import _
from frappe.utils.data import fmt_money

@frappe.whitelist( allow_guest=True )
def format_currency_value(value, currency=None, precision=None):
    """Formats the 'value' with the provided currency and precision."""
    return fmt_money(value, precision=precision, currency=currency)

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
