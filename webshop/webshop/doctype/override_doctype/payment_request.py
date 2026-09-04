import frappe
#//// Neoffice — _ imported for the messages returned to the buyer.
from frappe import _
from frappe.utils import get_url
#//// Neoffice — place_order is called from on_payment_authorized below (see next
#//// marker).
from webshop.webshop.shopping_cart.cart import place_order

from erpnext.accounts.doctype.payment_request.payment_request import (
    PaymentRequest as OriginalPaymentRequest,
)


class PaymentRequest(OriginalPaymentRequest):
    def on_payment_authorized(self, status=None):
        if not status:
            return

        if status not in ("Authorized", "Completed"):
            return

        if not hasattr(frappe.local, "session"):
            return

        if frappe.local.session.user == "Guest":
            #//// Neoffice — a guest CAN pay on our shops, and their payment MUST be
            #//// recorded. The booking module takes money without ever asking for an
            #//// account: the customer leaves their details, a personal space is created
            #//// silently, and they pay straight away — so with no session open.
            #////
            #//// This guard used to return before any processing. Measured end to end
            #//// with the test card on 2026-08-20: the charge was CAPTURED at Stripe, the
            #//// Payment Request stayed "Requested", the invoice unpaid, no accounting
            #//// entry — and the customer landed on "Not Authorized". They paid for
            #//// nothing.
            #////
            #//// The guard stays for the CART, which needs a session to create its order
            #//// (`place_order` reads the visitor's cart). An invoice, on the other hand,
            #//// already exists: the "Sales Invoice" block below even switches to
            #//// Administrator to write the payment.
            if self.reference_doctype != "Sales Invoice":
                return

        #//// Neoffice — read without permissions: a guest has no access to the shop's
        #//// settings, and a guest is exactly who has to be served here.
        cart_settings = frappe.get_cached_doc("Webshop Settings")

        if not cart_settings.enabled:
            return

        #//// Neoffice — upstream's on_payment_authorized only sets the status. Our checkout
        #//// raises the Payment Request against the QUOTATION, so the order has to be created
        #//// here, once the PSP has confirmed — and idempotently, because a PSP retries its
        #//// callback (392e3c313a / 57f71797e1, 2026-06-02).
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

        # If it's a Sales Invoice, only create payment entry (invoice already exists)
        if self.reference_doctype == "Sales Invoice":
            frappe.set_user("Administrator")
            # Only create payment entry, skip make_invoice
            self.create_payment_entry()

            success_url = cart_settings.payment_success_url
            redirect_to = get_url("/invoices/{0}".format(self.reference_name))

            if success_url:
                redirect_to = (
                    {
                        "Orders": "/orders",
                        "Invoices": "/invoices",
                        "My Account": "/me",
                    }
                ).get(success_url, "/me")

            return redirect_to

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

        #//// Neoffice — the callback runs without a session (the PSP is the caller), so the
        #//// user is set explicitly; the finally block that restored it was removed because it
        #//// corrupted the session user (847f9137c3, 2025-12-12).
        #//// Indentation: this file is four-space indented in frappe/webshop develop too
        #//// (`git show frappe/webshop:webshop/webshop/doctype/override_doctype/
        #//// payment_request.py`), so it stays that way — re-tabbing it would rewrite every
        #//// line of a file we barely touch and turn the next upstream merge into a
        #//// whole-file conflict for nothing.
        # Set the user to Administrator to avoid permission errors
        frappe.set_user("Administrator")
        # Call the set_as_paid method
        self.set_as_paid()

        return redirect_to

    @staticmethod
    def get_gateway_details(args):
        if args.order_type != "Shopping Cart":
            return super().get_gateway_details(args)

        cart_settings = frappe.get_doc("Webshop Settings")
        gateway_account = cart_settings.payment_gateway_account
        return super().get_payment_gateway_account(gateway_account)
