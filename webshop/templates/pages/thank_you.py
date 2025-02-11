import frappe
import json
from frappe import _
from webshop.webshop.shopping_cart.cart import decorate_quotation_doc

no_cache = 1

def get_context(context):
    context.json = json
    try:
        # Retrieve the sales order ID from the form dictionary
        sales_order_id = frappe.form_dict.get('sales_order')
        
        if not sales_order_id:
            frappe.local.flags.redirect_location = '/all-products'
            raise frappe.Redirect
        
        # Check if the Sales Order exists
        if not frappe.db.exists("Sales Order", sales_order_id):
            context.error_message = _("The specified order does not exist.")
            context.show_sidebar = False
            return context
        
        # Load Sales Order
        sales_order = frappe.get_doc("Sales Order", sales_order_id)
        context.sales_order = sales_order
        context.doc = sales_order
        
        # Decorate the document with web information (images, etc.)
        context.doc = decorate_quotation_doc(context.doc)
        
        # Retrieve payment information
        payment_entry = frappe.get_all(
            "Payment Entry",
            filters={
                "reference_name": sales_order_id,
                "docstatus": 1
            },
            fields=["name", "mode_of_payment", "reference_no", "reference_date", "paid_amount", "`tabPayment Entry`.creation"],
            order_by="`tabPayment Entry`.creation desc",
            limit=1
        )
        
        if payment_entry:
            context.payment_info = payment_entry[0]
            context.payment_info.payment_source = "Payment Entry"
            # Retrieve the translated name of the payment method
            mode_of_payment_doc = frappe.get_doc("Mode of Payment", context.payment_info.mode_of_payment)
            context.payment_info.mode_of_payment_label = _(mode_of_payment_doc.mode_of_payment)
        else:
            # If no Payment Entry, try Payment Request
            payment_request = frappe.get_all(
                "Payment Request",
                filters={
                    "reference_doctype": "Sales Order",
                    "reference_name": sales_order_id,
                    "docstatus": 1,
                    "status": "Paid"
                },
                fields=["name", "payment_gateway", "grand_total", "transaction_date", "`tabPayment Request`.creation"],
                order_by="`tabPayment Request`.creation desc",
                limit=1
            )
            
            if payment_request:
                context.payment_info = payment_request[0]
                context.payment_info.payment_source = "Payment Request"
                context.payment_info.mode_of_payment_label = _(payment_request[0].payment_gateway.split('-')[0].split()[0].strip())
                context.payment_info.reference_no = payment_request[0].name
                context.payment_info.reference_date = payment_request[0].transaction_date
                context.payment_info.paid_amount = payment_request[0].grand_total

        # Add delivery information if available
        shipping_address_name = sales_order.get("shipping_address_name")
        if shipping_address_name:
            context.shipping_address = frappe.get_doc("Address", shipping_address_name)
        
        context.show_sidebar = False
        return context
        
    except frappe.DoesNotExistError:
        context.error_message = _("The specified order does not exist.")
        context.show_sidebar = False
        return context
    except Exception as e:
        frappe.log_error(f"Error loading thank you page", e)
        context.error_message = _("An error occurred while loading the order.")
        context.show_sidebar = False
        return context
