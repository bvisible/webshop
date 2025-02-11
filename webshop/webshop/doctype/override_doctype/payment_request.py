import frappe
from frappe.utils import get_url
from webshop.webshop.shopping_cart.cart import place_order

from erpnext.accounts.doctype.payment_request.payment_request import (
    PaymentRequest as OriginalPaymentRequest,
)


class PaymentRequest(OriginalPaymentRequest):
    def on_payment_authorized(self, status=None):
        frappe.log_error("on_payment_authorized")
        if not status:
            return

        if status not in ("Authorized", "Completed"):
            return

        if not hasattr(frappe.local, "session"):
            return

        if frappe.local.session.user == "Guest":
            return

        if self.payment_channel == "Phone":
            return

        cart_settings = frappe.get_doc("Webshop Settings")

        if not cart_settings.enabled:
            return

        # If it's a Quotation, create the Sales Order
        if self.reference_doctype == "Quotation":
            payment_request = self
            # 1. Get quotation
            quotation = frappe.get_doc("Quotation", self.reference_name)
            
            # 2. Check if Sales Order already exists for this Quotation
            linked_docs = frappe.get_all(
                "Sales Order",
                filters={
                    "order_type": "Shopping Cart",
                    "docstatus": 1,
                    "prevdoc_docname": quotation.name
                },
                fields=["name"],
                limit=1
            )
            
            if linked_docs:
                sales_order_name = linked_docs[0].name
            else:
                # Create Sales Order using place_order
                frappe.flags.ignore_permissions = True
                sales_order_name = place_order()
                if not sales_order_name:
                    frappe.throw(_("Error creating order"))
                            
            # Update payment request with Sales Order reference
            payment_request.db_set('reference_doctype', 'Sales Order', update_modified=False)
            payment_request.db_set('reference_name', sales_order_name, update_modified=False)
            
            # Submit Payment Request before marking as paid
            if payment_request.docstatus == 0:
                payment_request.flags.ignore_permissions = True
                payment_request.save(ignore_permissions=True)
                payment_request.submit()
                
        success_url = cart_settings.payment_success_url
        redirect_to = get_url("/orders/{0}".format(self.reference_name))

        if success_url:
            redirect_to = (
                {
                    "Orders": "/orders",
                    "Invoices": "/invoices",
                    "My Account": "/me",
                }
            ).get(success_url, "/me")

        self.set_as_paid()

        return redirect_to

    @staticmethod
    def get_gateway_details(args):
        if args.order_type != "Shopping Cart":
            return super().get_gateway_details(args)

        cart_settings = frappe.get_doc("Webshop Settings")
        gateway_account = cart_settings.payment_gateway_account
        return super().get_payment_gateway_account(gateway_account)
