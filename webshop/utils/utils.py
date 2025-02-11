import frappe
import json

from frappe import _
from frappe.utils.data import fmt_money

@frappe.whitelist()
def format_currency_value(value, currency=None, precision=None):
    """Formats the 'value' with the provided currency and precision."""
    return fmt_money(value, precision=precision, currency=currency)

def get_gateway_configuration(payment_method):
    """Gets the JSON configuration for a given payment method"""
    try:
        config_path = frappe.get_app_path("webshop", "templates", "payments", f"{payment_method}.json")
        with open(config_path, "r") as f:
            return json.load(f)
    except Exception as e:
        frappe.log_error(f"Error reading payment configuration", e)
        return {}
