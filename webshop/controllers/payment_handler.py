import frappe
from frappe import _
# //// Neoffice — what a failure keeps of the caller's text, and the amount of a cart (see below).
from frappe.utils import cstr, flt, strip_html
import json
# //// Neoffice — get_party: whose cart it is (_is_the_session_s_quotation below).
from webshop.webshop.shopping_cart.cart import place_order, _get_cart_quotation, is_gift_card_item, get_party
# //// Neoffice — the placeholder order a cart's payment request is raised on (pending_order.py), and what proves
# //// a request was paid (payment_proof.py, maintenance#1807).
from webshop.webshop.shopping_cart import payment_proof, pending_order
# //// Neoffice — #277: the customer's session reads neither Item nor Account (shop_rights.py).
# //// Neoffice — #2114: the payment terms schedule is computed with the shop's rights too (payment_schedule_for).
from webshop.webshop.shopping_cart.shop_rights import payment_schedule_for, save_as_shop, shop_rights
# //// Neoffice — a payment method is offered to a customer group, and carries that
# //// group's payment terms (utils/payment_methods.py).
from webshop.webshop.utils.payment_methods import (
    customer_group_of,
    row_for_gateway,
    rows_for_group,
)
from erpnext.accounts.doctype.payment_request.payment_request import make_payment_entry

# //// Neoffice — whose cart is it? `create_payment_request` is `allow_guest` and took any quotation name the caller
# //// sent: with the placeholder order it creates, and releases, documents on that cart, so it is the session's own
# //// cart or nothing (the rule maintenance#1764 gave the PayPal tile, for every tile).
def _is_staff():
    return frappe.session.user == "Administrator" or "System Manager" in frappe.get_roles()


def _is_the_session_s_quotation(quotation_id):
    if not quotation_id or not frappe.db.exists("Quotation", quotation_id):
        return False
    row = frappe.db.get_value(
        "Quotation", quotation_id, ["party_name", "contact_email", "guest_session_id"], as_dict=True
    )
    user = frappe.session.user
    if user == "Guest":
        cookie = frappe.request.cookies.get("guest_session_id") if frappe.request else None
        return bool(cookie) and row.guest_session_id == cookie
    party = get_party()
    return bool(party) and row.party_name == party.name and row.contact_email == user


def _cart_of_request(payment_request):
    """The cart a payment request was raised for: its placeholder's, its quotation, or the one the order came from."""
    if payment_request.reference_doctype == "Quotation":
        return payment_request.reference_name
    if payment_request.reference_doctype == "Sales Order":
        if pending_order.is_placeholder(payment_request.reference_name):
            return pending_order.quotation_of(payment_request.reference_name)
        return frappe.db.get_value(
            "Sales Order Item", {"parent": payment_request.reference_name, "docstatus": 1}, "prevdoc_docname"
        )
    return None


# //// Neoffice — what is kept of the text a browser sends with a failed payment. It went as it came into
# //// `message` of the request, a field ERPNext renders as a Jinja template when the request is mailed. One
# //// short plain text is all a decline needs.
FAILURE_NOTE_LENGTH = 200


def _failure_note(error_message):
    text = strip_html(cstr(error_message))[:FAILURE_NOTE_LENGTH]
    return text.replace("{", "(").replace("}", ")").strip() or _("Payment failed")


# //// Neoffice — added function (no upstream equivalent), see `_record_gateway_payment`.
def enabled_mode_of_payment(account, company):
    """The enabled Mode of Payment wired to `account` for `company`, or None.

    erpnext 15.124 refuses a Payment Entry whose Mode of Payment is disabled (4774e7134d). A disabled mode wired
    to the same clearing account came first, so the money of a paid order was captured and never booked (the
    failure was only logged)."""
    rows = frappe.db.sql(
        """
        select mpa.parent
        from `tabMode of Payment Account` mpa
        join `tabMode of Payment` mop on mop.name = mpa.parent
        where mpa.default_account = %s and mpa.company = %s and mop.enabled = 1
        order by mpa.idx, mpa.creation
        limit 1
        """,
        (account, company),
    )
    return rows[0][0] if rows else None


class PaymentHandler:
    def __init__(self):
        self.settings = frappe.get_doc("Webshop Settings")
        
    def create_payment_request(self, quotation_id=None, gateway_settings=None, idempotency_token=None,
                               payment_gateway=None):
        """Create a payment request for a quotation
        
        Args:
            quotation_id (str, optional): ID of the quotation. If not provided, uses the cart.
            gateway_settings (str, optional): Name of the Gateway Settings to use. If provided, bypasses the default payment method.
            idempotency_token (str, optional): Token to prevent duplicate payment requests.
            payment_gateway (str, optional): Payment Gateway name, resolved directly.
                Takes precedence over gateway_settings. See the //// Neoffice note below.
        """
        # //// Neoffice — the cart is the session's own, checked before anything is read or written, and before the try
        # //// below so that the refusal is a refusal and not an "error creating the payment request".
        if quotation_id and not _is_staff() and not _is_the_session_s_quotation(quotation_id):
            frappe.throw(_("Not permitted"), frappe.PermissionError)

        try:
            # Check for idempotency token to prevent duplicate requests
            if idempotency_token:
                # Check if a payment request already exists with this token
                existing_pr = frappe.db.get_value(
                    "Payment Request",
                    {"custom_idempotency_token": idempotency_token},
                    # //// Neoffice — `reference_doctype` added: the request may
                    # //// already point to the created order, not the quotation.
                    # //// Neoffice — `grand_total`: what the request asks of the gateway (see below).
                    ["name", "status", "reference_name", "reference_doctype", "grand_total"],
                    as_dict=True
                )

                # //// Neoffice — a request that is another buyer's is no request of this one: a token is not a key
                # //// to someone else's cart (the answer below releases the placeholder of a cart that changed).
                if existing_pr and not _is_staff() and not _is_the_session_s_quotation(_cart_of_request(existing_pr)):
                    existing_pr = None

                if existing_pr:
                    # If payment request exists and is not failed, return existing one
                    if existing_pr.status != "Failed":
                        frappe.log_error(f"Duplicate payment request prevented. Token: {idempotency_token}", "Payment Idempotency")
                        
                        # //// Neoffice — the order→quotation link lives on the LINE
                        # //// (`Sales Order Item.prevdoc_docname`): `Sales Order`
                        # //// has no `quotation` column. The original query therefore
                        # //// raised « Unknown column 'quotation' » on EVERY
                        # //// payment retry, the exception bubbled up to the general
                        # //// except, and the customer received « Erreur lors de la
                        # //// création de la demande de paiement » instead of
                        # //// finding their request again. Only visible on the second attempt.
                        # //// Neoffice — "the request points at a Sales Order" no longer means the order
                        # //// exists: until the money is in, it points at the cart's placeholder order
                        # //// (pending_order.py). A request on a placeholder is the one to find again, unless
                        # //// the cart changed since: then it is released and a new one is raised below.
                        sales_order = pending_order.confirmed_order(existing_pr)
                        on_placeholder = (
                            not sales_order
                            and existing_pr.reference_doctype == "Sales Order"
                            and pending_order.is_placeholder(existing_pr.reference_name)
                        )
                        stale = False
                        if on_placeholder:
                            cart_name = pending_order.quotation_of(existing_pr.reference_name)
                            # //// Neoffice — the total as well as the lines: a shipping rule, an address or
                            # //// loyalty points move the total and leave the lines alone, so the request
                            # //// found again kept the old amount while the gateway was asked for the new
                            # //// one, and the order and its payment entry were then booked for an amount
                            # //// the gateway never captured.
                            cart = (
                                frappe.get_doc("Quotation", cart_name)
                                if frappe.db.exists("Quotation", cart_name)
                                else None
                            )
                            if (
                                cart
                                and pending_order.is_current(existing_pr.reference_name, cart)
                                and pending_order.amount_matches(existing_pr, cart)
                            ):
                                # //// Neoffice — the buyer is still here: the hold of the placeholder starts over.
                                pending_order.touch(existing_pr.reference_name)
                                return {
                                    "status": "success",
                                    "payment_request_id": existing_pr.name,
                                    "message": _("Using existing payment request")
                                }
                            if not pending_order.release(cart_name):
                                return {
                                    "status": "error",
                                    "message": _("A payment for this cart is being processed. Please wait a moment.")
                                }
                            stale = True
                        # //// Neoffice — only when confirmed_order found no real order above.
                        elif not sales_order and existing_pr.reference_doctype == "Sales Order":
                            sales_order = existing_pr.reference_name
                        # //// Neoffice — idem: a request raised before the placeholder points at the quotation.
                        elif not sales_order and existing_pr.reference_name:
                            sales_order = frappe.db.get_value(
                                "Sales Order Item",
                                # //// Neoffice — a SUBMITTED order only: the lines of a placeholder (a draft) carry the
                                # //// quotation's name too, and are no order.
                                {"prevdoc_docname": existing_pr.reference_name, "docstatus": 1},
                                "parent"
                            )
                        
                        # //// Neoffice — a stale placeholder was released above and a new request is raised below.
                        if not stale:
                            if sales_order:
                                return {
                                    "status": "error",
                                    "message": _("This order has already been processed. Order ID: {0}").format(sales_order),
                                    "existing_order": sales_order
                                }
                            
                            # //// Neoffice — the request is found again (a legacy one, raised on the quotation).
                            return {
                                "status": "success",
                                "payment_request_id": existing_pr.name,
                                "message": _("Using existing payment request")
                            }
            # //// Neoffice — upstream's `return` of the found request moved up, under `if not stale`.
            # if not quotation, get cart quotation
            if not quotation_id:
                quotation = _get_cart_quotation()
                if not quotation:
                    frappe.log_error(_("Cart Error"), _("Error during quotation retrieval: Cart is empty or quotation not found"))
                    frappe.throw(_("Cart is empty"))
            else:
                quotation = frappe.get_doc("Quotation", quotation_id)
            
            # Get webshop parameters
            settings = frappe.get_cached_doc("Webshop Settings")
            
            # Initialize payment variables
            payment_method = None
            payment_method_doc = None
            gateway_account = None
            payment_terms_template = None
            
            # //// Neoffice — accept a Payment Gateway name directly, in addition to
            # //// resolving one from its gateway_settings doctype.
            # //// Upstream only looks the gateway up by `gateway_settings`, which is a
            # //// Link to DocType — so the lookup returns whichever gateway happens to
            # //// reference that doctype first. That is fine while every PSP owns a
            # //// dedicated settings doctype (Stripe Settings, Wallee Settings, …), but
            # //// our unified providers share `Provider Channel Settings`: the second
            # //// one added would silently resolve to the first. Passing the gateway
            # //// name removes the ambiguity instead of working around it.
            # //// Drop this once upstream resolves gateways by name.
            if payment_gateway:
                if not frappe.db.exists("Payment Gateway", payment_gateway):
                    frappe.throw(_("Payment Gateway not found: {0}").format(payment_gateway))
                gateway = payment_gateway
                gateway_account = frappe.get_doc("Payment Gateway Account", {"payment_gateway": gateway})
                # //// Neoffice — the terms come from the row this customer was OFFERED,
                # //// not from the first row whose account name happens to start with the
                # //// gateway's. Two groups can share a gateway on different terms — 30
                # //// days for one, 2% within 10 for the other — and `startswith` handed
                # //// both of them whichever row came first. See utils/payment_methods.py.
                _row = row_for_gateway(gateway_account.name, settings, customer_group_of(quotation))
                payment_terms_template = _row.payment_terms_template if _row else None

            # If gateway_settings is provided, use it directly
            elif gateway_settings:
                # Get Payment Gateway
                gateway = frappe.get_value("Payment Gateway", {"gateway_settings": gateway_settings}, "name")
                if not gateway:
                    frappe.throw(_("Payment Gateway not found for settings: {0}").format(gateway_settings))
                    
                # Get Payment Gateway Account
                gateway_account = frappe.get_doc("Payment Gateway Account", {"payment_gateway": gateway})
                
                # //// Neoffice — see the marker above: the row this customer was offered.
                _row = row_for_gateway(gateway_account.name, settings, customer_group_of(quotation))
                payment_terms_template = _row.payment_terms_template if _row else None
                
            else:
                # //// Neoffice — the default is the first method THIS customer is offered,
                # //// not the first row of the table: falling back to a row aimed at another
                # //// group would charge them through a method the shop never showed them.
                offered = rows_for_group(settings, customer_group_of(quotation))
                if not offered:
                    frappe.throw(_("No payment method is available for your account."))
                payment_method_doc = offered[0]
                payment_terms_template = payment_method_doc.payment_terms_template
                gateway_account = frappe.get_doc("Payment Gateway Account", payment_method_doc.payment_gateway_account)
            
            # Update quotation with payment_gateway
            quotation.payment_gateway = gateway_account.payment_gateway
            
            # Ensure amounts are defined
            if not quotation.rounded_total:
                with shop_rights():  # //// Neoffice — #277
                    quotation.run_method("set_missing_values")
                    quotation.run_method("calculate_taxes_and_totals")
                
            # Clear and recalculate payment schedule
            quotation.payment_schedule = []
            # //// Neoffice — #2173: with the shop's rights, like the calls around it. ERPNext reads the party's receivable account here
            # //// and, since the merge of 4 Oct 2026, refuses a session that may not read it: a portal buyer paying by invoice on a
            # //// shop whose customer has no account of its own ended in « Error creating payment request » at the last click.
            with shop_rights():
                quotation.set_payment_schedule()
            save_as_shop(quotation, ignore_permissions=True)  # //// Neoffice — #277
            
            # Update payment_terms_template 
            if payment_terms_template:
                quotation.payment_terms_template = payment_terms_template
                save_as_shop(quotation, ignore_permissions=True)  # //// Neoffice — #277
                
                # Get and update payment schedule
                # //// Neoffice — #2114: asked with the shop's rights, not the buyer's session. Upstream's get_payment_terms
                # //// (0f64354085, 4 Oct 2026) refuses a session that may not read the Payment Terms Template, and a
                # //// portal customer may not: every payment on a method whose row names a template ended in « Error
                # //// creating payment request ». The template is this row's (the shop's), never one the buyer named.
                payment_schedule = payment_schedule_for(
                    payment_terms_template,
                    posting_date=quotation.transaction_date,
                    grand_total=quotation.rounded_total or quotation.grand_total,
                    base_grand_total=quotation.base_rounded_total or quotation.base_grand_total
                )
                if payment_schedule:
                    quotation.set("payment_schedule", payment_schedule)
                    save_as_shop(quotation, ignore_permissions=True)  # //// Neoffice — #277

            # Create context for payment request
            context = {
                "reference_doctype": "Quotation",
                "reference_name": quotation.name,
                "amount": quotation.rounded_total,
                "currency": quotation.currency,
                "payment_gateway": gateway_account.payment_gateway
            }
            
            # Prepare data for template
            context.update({
                "payment_method": payment_method,
                "callback_url": frappe.utils.get_url("/api/payment/callback"),
            })
            
            # //// Neoffice — raised on the cart's PLACEHOLDER order, not on the quotation: upstream ERPNext
            # //// (v15.12x) refuses a Payment Request against a Quotation ("Payment Requests cannot be created
            # //// against: Quotation"). The placeholder is a draft Sales Order named outside the order series;
            # //// the real order is made only once the gateway has confirmed the money, as it always was, and
            # //// the request then moves to it (handle_payment_success, on_payment_authorized). See
            # //// pending_order.py (neoffice-maintenance#1802).
            carrier = pending_order.carrier_for(quotation)

            # Create payment request with transaction date
            pr_data = {
                "doctype": "Payment Request",
                "payment_gateway_account": gateway_account.name,
                "payment_request_type": "Inward",
                "reference_doctype": "Sales Order",
                "reference_name": carrier,
                # //// Neoffice — upstream's validate compares the request's company with its document's
                "company": quotation.company,
                "currency": quotation.currency,
                "grand_total": quotation.rounded_total,
                "email_to": quotation.contact_email,
                "status": "Draft",
                "payment_gateway": gateway_account.payment_gateway,
                "gateway_data": json.dumps(context),
                "transaction_date": frappe.utils.now(),
                "party_type": "Customer",
                "party": quotation.party_name,
                "from_checkout": 1
            }
            
            # Add idempotency token if provided
            if idempotency_token:
                pr_data["custom_idempotency_token"] = idempotency_token
            
            payment_request = frappe.get_doc(pr_data)
            payment_request.flags.ignore_permissions = True
            # //// Neoffice — save_as_shop, not a plain insert: upstream's validate reads the document the
            # //// request is raised on with the SESSION user's rights (ref_doc.check_permission), which a
            # //// customer or a visitor does not have on an order; the request stays the buyer's (owner).
            save_as_shop(payment_request, ignore_permissions=True)
            
            return {
                "status": "success",
                "payment_url": payment_request.payment_url,
                "payment_request_id": payment_request.name,
                "gateway_data": context
            }
            
        except Exception:
            # //// Neoffice — #2114: the traceback is the message; `e` alone kept str(e) (« Not permitted ») and pointed nowhere.
            frappe.log_error("Detailed error while creating payment request", frappe.get_traceback())
            return {
                "status": "error",
                "message": _("Error creating payment request")
            }
    
    def handle_payment_success(self, **kwargs):
        try:
            # //// Neoffice — WHO is allowed to complete this payment.
            # ////
            # //// The endpoint is `allow_guest` and the body switches to Administrator
            # //// "because the gateway confirmed it" — but NOTHING actually
            # //// checked that. A visitor who was never signed in and posted a request
            # //// number would get a submitted Sales Order, `advance_paid`
            # //// at 0. Since the numbers are sequential (ACC-PRQ-2026-00060), every
            # //// pending cart would confirm without paying. Demonstrated on
            # //// osiris on 2026-08-24: order BC-2026-00326, CHF 15, created
            # //// from an anonymous session.
            # ////
            # //// The guard is placed BEFORE `set_user`, otherwise it would judge
            # //// itself as Administrator.
            payment_request_id = kwargs.get('payment_request_id')
            if not payment_request_id:
                return self.handle_error("Missing payment request ID")
            if not frappe.db.exists("Payment Request", payment_request_id):
                return self.handle_error("Missing payment request ID")
            # //// Neoffice — RULE #00 pass (#925): was `_peut_conclure`.
            if not _may_conclude(payment_request_id):
                # //// Neoffice — the buyer's own request, but no gateway has confirmed the money (maintenance#1807):
                # //// refused and left exactly as it is, with a message that tells them what to do. Marking it
                # //// Failed would let a call with no proof kill a payment the gateway is still about to confirm.
                # //// Anyone else is simply not permitted.
                if _is_the_buyer(payment_request_id):
                    return self._not_confirmed_yet(payment_request_id)
                # //// Neoffice — the answer a stranger always got, without the `frappe.throw` that went
                # //// through the except below: a refusal is no fault, and each refused POST committed an
                # //// Error Log row. A browser never reads this: the web method refuses first.
                return {"status": "error", "message": _("Error processing payment")}

            # Bypass all permission checks - payment is confirmed by payment provider
            # We need to run as Administrator because get_mapped_doc checks permissions
            frappe.set_user("Administrator")
            frappe.flags.ignore_permissions = True

            # //// Neoffice — the cart is locked FIRST, then the request: two requests of one cart concluding together
            # //// (a double payment) then wait in a single file, instead of each holding its own row while the first
            # //// one's move of the sibling requests waits for the other's (a deadlock).
            _first = frappe.db.get_value(
                "Payment Request", payment_request_id, ["reference_doctype", "reference_name"], as_dict=True
            )
            if _first.reference_doctype == "Sales Order" and pending_order.is_placeholder(_first.reference_name):
                _cart = pending_order.quotation_of(_first.reference_name)
            else:
                _cart = _first.reference_name if _first.reference_doctype == "Quotation" else None
            if _cart and frappe.db.exists("Quotation", _cart):
                frappe.get_doc("Quotation", _cart, for_update=True)

            # //// Neoffice — the request is read FOR UPDATE: the gateway's callback, the buyer's return page and the
            # //// TWINT poller all conclude it, and a second call arriving while the first makes the order must wait
            # //// for it and then find the request moved to that order, instead of making a second one.
            payment_request = frappe.get_doc("Payment Request", payment_request_id, for_update=True)
            payment_request.flags.ignore_permissions = True
            self.payment_request = payment_request

            # //// Neoffice — already on a REAL order: concluded there, or moved there by another request of the same cart
            # //// (it followed it). Judged BEFORE the request is submitted, which validates it against the order: a call
            # //// that waited for the lock reads, in its snapshot, the state from before the other one committed.
            if payment_request.reference_doctype == "Sales Order" and not pending_order.is_placeholder(
                payment_request.reference_name
            ):
                if payment_request.status not in ("Paid", "Completed"):
                    # This request is not Paid and the order is real: the order was made by ANOTHER request of the same
                    # cart, so this payment may be a second one for the same cart. It is not booked here; somebody has
                    # to look (refund or credit).
                    frappe.log_error(
                        "Webshop: a second payment request of a cart concluded",
                        f"payment_request={payment_request.name} order={payment_request.reference_name} "
                        f"status={payment_request.status}: money may have been taken twice for one cart",
                    )
                return {
                    "status": "success",
                    # //// Neoffice — upstream sends the buyer to /thank_you. Here the page is /thank-you (English hyphenated
                    # //// addresses, #1862); /thank_you stays as a 301 that keeps the query string (neoffice_theme.renamed_routes).
                    "redirect_to": f"/thank-you?sales_order={payment_request.reference_name}",
                    "message": _("Payment already processed")
                }

            # Submit payment request now that payment is successful
            if payment_request.docstatus == 0:  # If not already submitted
                payment_request.flags.ignore_permissions = True
                payment_request.submit()
            
            # Check if payment request is already processed - redirect to thank you page
            if payment_request.status in ["Paid", "Completed"]:
                # Already processed, find the Sales Order and redirect
                # //// Neoffice — a request still on its placeholder order has no order to redirect to.
                if payment_request.reference_doctype == "Sales Order" and not pending_order.is_placeholder(
                    payment_request.reference_name
                ):
                    return {
                        "status": "success",
                        # //// Neoffice — upstream sends the buyer to /thank_you. Here the page is /thank-you (English hyphenated
                        # //// addresses, #1862); /thank_you stays as a 301 that keeps the query string (neoffice_theme.renamed_routes).
                        "redirect_to": f"/thank-you?sales_order={payment_request.reference_name}",
                        "message": _("Payment already processed")
                    }
                # //// Neoffice — Paid but still on the cart's placeholder: the order was never made (a gateway marked
                # //// the request, or the move failed). That is not "processed": the order is made below.
                if not (
                    payment_request.reference_doctype == "Sales Order"
                    and pending_order.is_placeholder(payment_request.reference_name)
                ):
                    return {"status": "success", "message": _("Payment already processed")}

            # Concurrent-finalize guard: a second call (e.g. the TWINT poller
            # racing the consumer redirect / simulate) can arrive after the
            # first one already swapped the PR reference from the Quotation to
            # the created Sales Order. In that case the order is being
            # finalised by the other call — treat it as already processed
            # instead of trying to load the Sales Order name as a Quotation
            # (which would raise "Quotation <SO> not found").
            # //// Neoffice — only a REAL order says "already processed": until the money is in, the request
            # //// points at the cart's placeholder order (pending_order.py), and that is the one to conclude.
            placeholder = None
            if payment_request.reference_doctype == "Sales Order":
                # a placeholder: a request on a real order returned above
                placeholder = payment_request.reference_name

            # 1. Get quotation
            # //// Neoffice — the cart the placeholder stands for (or the quotation itself, for a request raised
            # //// before the placeholder existed).
            quotation = frappe.get_doc(
                "Quotation",
                pending_order.quotation_of(placeholder) if placeholder else payment_request.reference_name,
            )
            quotation.flags.ignore_permissions = True
            self.quotation = quotation

            # 2. Check if Sales Order already exists for this Quotation
            linked_docs = frappe.get_all(
                "Sales Order",
                filters={
                    "order_type": "Shopping Cart",
                    "docstatus": 1,
                    "prevdoc_docname": quotation.name
                },
                fields=["name"],
                limit=1,
                ignore_permissions=True
            )

            if linked_docs:
                sales_order_name = linked_docs[0].name
            else:
                # //// Neoffice — the order is built from the cart as it is NOW and its payment is booked against its
                # //// invoice: a cart changed after this request was raised (a quantity in another tab, a code applied)
                # //// would order and book more or less than the buyer paid. Not concluded: the request is kept with a
                # //// note, and somebody looks (the gateway has the money).
                if not pending_order.amount_matches(payment_request, quotation):
                    pending_order.keep_unmatched(payment_request, quotation)
                    return {
                        "status": "error",
                        "message": _(
                            "The cart changed after the payment was started. The payment is kept: please contact us."
                        ),
                        "redirect_to": "",
                    }

                # Submit quotation first if not already submitted (required for make_sales_order)
                if quotation.docstatus == 0:
                    quotation.flags.ignore_permissions = True
                    quotation.submit()

                # Use make_sales_order from quotation
                from erpnext.selling.doctype.quotation.quotation import make_sales_order
                sales_order = make_sales_order(quotation.name)
                sales_order.flags.ignore_permissions = True
                sales_order.order_type = "Shopping Cart"

                # Update transaction_date to today and recalculate payment schedule
                # This fixes the "Due Date cannot be before Posting Date" error
                # when quotation was created on a previous day
                today = frappe.utils.today()
                sales_order.transaction_date = today
                sales_order.delivery_date = today

                # //// Neoffice — multi-warehouse: replace the placeholder
                # //// delivery_date with the real per-line estimate from each
                # //// line's stock source (supplier lines promise a longer
                # //// date); header becomes the latest line. No-op when the
                # //// feature is off.
                from webshop.webshop.multi_warehouse.sources import is_enabled as _mw_enabled
                if _mw_enabled():
                    from webshop.webshop.shopping_cart.cart import (
                        _set_delivery_dates_from_sources,
                    )
                    _set_delivery_dates_from_sources(sales_order)
                # Clear and recalculate payment schedule with today's date
                if sales_order.payment_schedule:
                    for ps in sales_order.payment_schedule:
                        if ps.due_date and str(ps.due_date) < today:
                            ps.due_date = today

                # Preserve gift card discount from quotation
                if quotation.discount_amount:
                    sales_order.apply_discount_on = quotation.apply_discount_on or "Grand Total"
                    sales_order.discount_amount = quotation.discount_amount

                # Preserve gift card coupon code if quotation has one
                if hasattr(quotation, 'gift_card_coupon') and quotation.gift_card_coupon:
                    coupon_code = quotation.gift_card_coupon
                    if frappe.db.exists("Coupon Code", coupon_code):
                        sales_order.coupon_code = coupon_code

                sales_order.submit()
                sales_order_name = sales_order.name

                if not sales_order_name:
                    return self.handle_error("Error creating order")
                            
            # 3. Update Payment Request with Sales Order reference
            # //// Neoffice — also drops the placeholder order the request stood on (pending_order.py).
            pending_order.move_request_to(payment_request, sales_order_name)
        
            # 4. Mark the Payment Request as paid.
            #    ERPNext's Payment Request no longer exposes
            #    ``on_payment_authorized`` (it was removed in a recent upgrade),
            #    so the previous ``run_method("on_payment_authorized", ...)``
            #    became a SILENT no-op — the PR stayed "Requested" forever even
            #    though the PSP (Stripe / Wallee / TWINT) had captured the money.
            #    The payment itself is tracked on the Payment Intent; the
            #    created Sales Order drives downstream invoicing/delivery. Here
            #    we only need the PR to reflect Paid (same end state as the old
            #    on_payment_authorized -> set_as_paid for "Phone" channel).
            try:
                if payment_request.status not in ("Paid", "Completed"):
                    payment_request.db_set(
                        {"status": "Paid", "outstanding_amount": 0},
                        update_modified=False,
                    )
            except Exception as e:
                frappe.log_error("Error marking Payment Request as paid", f"{e}\n{frappe.get_traceback()}")
                return self.handle_error(str(e))
            
            # 5. Invoice the order and book the money in.
            #    The PSP has already captured the funds at this point. Until
            #    this call existed the flow stopped at the Sales Order: the
            #    order stayed "To Bill" forever and the cash never reached the
            #    ledger. `handle_direct_order` (unpaid orders) always invoiced,
            #    so PAID orders were the only ones left unbilled.
            self._invoice_paid_order(sales_order_name, payment_request)

            # Build default success URL
            # //// Neoffice — upstream sends the buyer to /thank_you. Here the page is /thank-you (English hyphenated
            # //// addresses, #1862); /thank_you stays as a 301 that keeps the query string (neoffice_theme.renamed_routes).
            success_url = f"/thank-you?sales_order={sales_order_name}"
            
            return {
                "status": "success",
                "redirect_to": success_url,
                "message": _("Payment processed successfully")
            }
            
        except Exception as e:
            frappe.log_error(message=f"{str(e)}\n{frappe.get_traceback()}", title="Detailed error while processing payment")
            return {
                "status": "error",
                "message": _("Error processing payment")
            }

    def _not_confirmed_yet(self, payment_request_id):
        """The answer to a buyer asking to conclude a request the gateway has not confirmed. Touches nothing.

        //// Neoffice — maintenance#1807. One short line in the Error Log, no traceback: it is a refusal, not a fault.
        If the proof arrives afterwards (the gateway's return, its webhook, the TWINT poller), the request is
        concluded as usual.
        """
        # //// Neoffice — once an hour per request: each reload of a waiting buyer wrote a row. Per request,
        # //// not per title (payments' `log_once_an_hour`): a second buyer's charge in that hour is its
        # //// own case.
        key = f"webshop:not_confirmed_yet:{payment_request_id}"
        if not frappe.cache().get_value(key):
            frappe.cache().set_value(key, 1, expires_in_sec=3600)
            frappe.log_error(
                "Webshop: a payment was asked to be concluded before the gateway confirmed it",
                f"payment_request={payment_request_id} user={frappe.session.user}",
            )
        return {
            "status": "error",
            "redirect_to": "",
            "message": _(
                "Your payment is not confirmed yet. If your card was charged, do not pay again: "
                "the order will appear in your orders as soon as the payment is confirmed."
            ),
        }

    def _invoice_paid_order(self, sales_order_name, payment_request):
        """Create and submit the Sales Invoice + Payment Entry for a paid order.

        Best effort by design: the money is already captured by the PSP, so a
        bookkeeping failure must never break the buyer's confirmation page nor
        roll back the order. Failures are logged for manual follow-up.
        """
        try:
            sales_order = frappe.get_doc("Sales Order", sales_order_name)
            if (sales_order.per_billed or 0) >= 100:
                # Already invoiced (retry, duplicate webhook, manual billing).
                return

            from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice

            # //// Neoffice — the invoice and the payment entry with the shop's rights, whoever the
            # //// session is: upstream v15.123.0 asks the session user for the right to create a
            # //// Payment Entry and read the invoice (get_payment_entry, 5289982059), for Customer
            # //// read when the invoice books loyalty points (aea326869b), and for Item read when a
            # //// line is priced (the mapping included, #277). A failure here is only logged, so a
            # //// portal customer's or a visitor's session would leave money captured by the PSP
            # //// and never booked. handle_payment_success runs as Administrator already; this no
            # //// longer depends on it.
            with shop_rights():
                invoice = make_sales_invoice(sales_order_name, ignore_permissions=True)
                invoice.allocate_advances_automatically = True
                invoice.flags.ignore_permissions = True
                invoice.insert(ignore_permissions=True)
                invoice.submit()

                self._record_gateway_payment(invoice, payment_request, sales_order.company)
        except Exception as e:
            frappe.log_error(
                "Webshop: invoicing a paid order failed",
                f"sales_order={sales_order_name} payment_request={payment_request.name}\n"
                f"{e}\n{frappe.get_traceback()}",
            )

    def _record_gateway_payment(self, invoice, payment_request, company):
        """Book the captured amount against `invoice`, on the gateway account."""
        gateway_account = frappe.db.get_value(
            "Payment Gateway Account",
            payment_request.payment_gateway_account,
            ["payment_account", "payment_gateway"],
            as_dict=True,
        ) if payment_request.payment_gateway_account else None

        if not gateway_account or not gateway_account.payment_account:
            frappe.log_error(
                "Webshop: no gateway account, invoice left unpaid",
                f"invoice={invoice.name} payment_request={payment_request.name}",
            )
            return

        # The Mode of Payment is the one wired to the same clearing account
        # (e.g. "Twint" -> "1036 Compte d'attente Twint").
        # //// Neoffice — erpnext 15.124 refuses a Payment Entry whose Mode of Payment is
        # disabled; the lookup used to take the first mode wired to the gateway's clearing
        # account whether enabled or not, so the money was captured but never booked
        # (dfa641c6f0 "fix(payment): the shop books a paid order on an enabled Mode of
        # Payment")
        mode_of_payment = enabled_mode_of_payment(gateway_account.payment_account, company)

        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        entry = get_payment_entry("Sales Invoice", invoice.name)
        entry.paid_to = gateway_account.payment_account
        if mode_of_payment:
            entry.mode_of_payment = mode_of_payment
        entry.reference_no = payment_request.name
        entry.reference_date = frappe.utils.today()
        entry.remarks = f"Webshop payment via {gateway_account.payment_gateway} ({payment_request.name})"
        entry.flags.ignore_permissions = True
        entry.insert(ignore_permissions=True)
        entry.submit()

    def handle_error(self, message):
        error_url = "/payment-failed"
        return {
            "status": "error",
            "redirect_to": error_url,
            "message": _(message)
        }

    def handle_payment_failure(self, payment_request_id, error_message=None):
        """Handle payment failure"""
        try:
            # //// Neoffice — same family as `handle_payment_success`: the endpoint
            # //// is `allow_guest` and did not check WHO the request belongs to. An
            # //// anonymous visitor could set it to `Failed` with a message of their
            # //// choosing — enough to kill, by enumerating the sequential numbers,
            # //// every payment in progress for a shop. Demonstrated on osiris
            # //// on 2026-08-24 on ACC-PRQ-2026-00189.
            # //// No "intent succeeded" case here: a failure is never confirmed
            # //// on the PSP side by a `succeeded` intent.
            if not payment_request_id or not frappe.db.exists("Payment Request", payment_request_id):
                return self.handle_error("Missing payment request ID")
            # //// Neoffice — one answer, recorded or not: the card tile shows it. A `frappe.throw` here
            # //// ended in the except below, one Error Log row per refused POST and a visitor told of a
            # //// system error.
            note = _failure_note(error_message)
            answer = {"status": "error", "message": note, "redirect_to": ""}
            if not _is_the_buyer(payment_request_id):
                return answer

            # //// Neoffice — read under lock, then judged. This wrote docstatus 1 / Failed on whatever the
            # //// request was: a paid request read as failed and could then be released, a cancelled one
            # //// came back to life. Only a request that moved no money can fail, and a gateway concluding
            # //// it at this moment is waited for.
            payment_request = frappe.get_doc("Payment Request", payment_request_id, for_update=True)
            payment_request.flags.ignore_permissions = True
            if (
                payment_request.docstatus == 2
                or payment_request.status not in pending_order.UNPAID_STATUSES
                or payment_proof.is_confirmed(payment_request_id)
            ):
                return answer

            frappe.db.set_value("Payment Request", payment_request_id, {
                "docstatus": 1,
                "status": "Failed",
                # //// Neoffice — the answer the shop's script can read: a refusal here left the card tile frozen.
                "message": note
            }, update_modified=False)

            frappe.db.commit()
            
            # //// Neoffice — the answer the shop's script can read: a refusal here left the card tile frozen.
            return answer
            
        except Exception:
            # //// Neoffice — #2114: the traceback is the message; `e` alone kept str(e) (« Not permitted ») and pointed nowhere.
            frappe.log_error("Detailed error while processing payment failure", frappe.get_traceback())
            return {
                "status": "error",
                "message": _("A system error occurred while processing payment failure"),
                "redirect_to": ""
            }

    def get_default_payment_method(self, customer_group=None):
        """The first payment method offered, for `customer_group` when one is given.

        //// Neoffice — takes the customer group into account. Without it, the answer
        //// was the first row of the table, which may be aimed at another group
        //// entirely (utils/payment_methods.py).
        """
        offered = rows_for_group(frappe.get_cached_doc("Webshop Settings"), customer_group)
        return offered[0].name if offered else None

    def handle_direct_order(self, idempotency_token=None):
        """Handle direct order validation without payment"""
        try:
            # Check for existing order with idempotency token
            if idempotency_token:
                # Check in cache or database for existing order with this token
                cache_key = f"direct_order_{idempotency_token}"
                existing_order = frappe.cache().get_value(cache_key)
                
                if existing_order:
                    frappe.log_error(f"Duplicate direct order prevented. Token: {idempotency_token}", "Order Idempotency")
                    return {
                        "status": "error",
                        "message": _("This order has already been processed. Order ID: {0}").format(existing_order),
                        "existing_order": existing_order
                    }
            # Create sales order
            from webshop.webshop.shopping_cart.cart import place_order
            sales_order_name = place_order()
            
            if not sales_order_name:
                return {
                    "status": "error",
                    "message": _("Error creating order")
                }
            
            # Store order in cache with idempotency token
            if idempotency_token:
                cache_key = f"direct_order_{idempotency_token}"
                # Store for 24 hours
                frappe.cache().set_value(cache_key, sales_order_name, expires_in_sec=86400)
            
            # Create invoice
            from erpnext.accounts.doctype.payment_request.payment_request import make_payment_entry
            sales_order = frappe.get_doc("Sales Order", sales_order_name)
            
            # Create and submit invoice
            from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice
            # //// Neoffice — mapped, saved and submitted with the shop's rights, then handed back to
            # //// the buyer as owner (save_as_shop): this runs in the buyer's session, and upstream
            # //// v15.123.0 asks that user for Item read when a line is priced (the mapping
            # //// included, #277) and for Customer read whenever the invoice books or redeems
            # //// loyalty points (make_loyalty_point_entry, validate_loyalty_points, aea326869b). The
            # //// buyer got "An error occurred" after their order was already submitted, and the
            # //// order was never invoiced.
            with shop_rights():
                si = make_sales_invoice(sales_order_name, ignore_permissions=True)
            si.allocate_advances_automatically = True
            save_as_shop(si, ignore_permissions=True)  # //// Neoffice — see above
            save_as_shop(si, submit=True)

            # Redirect to thank you page
            # //// Neoffice — upstream sends the buyer to /thank_you. Here the page is /thank-you (English hyphenated
            # //// addresses, #1862); /thank_you stays as a 301 that keeps the query string (neoffice_theme.renamed_routes).
            success_url = f"/thank-you?sales_order={sales_order_name}"
            
            return {
                "status": "success",
                "redirect_to": success_url,
                "message": _("Order validated successfully")
            }
            
        except Exception as e:
            frappe.log_error("Error while validating order", str(e))
            return {
                "status": "error",
                "message": _("An error occurred while validating the order")
            }

# //// Neoffice — each parameter a text: a JSON body made a filter of any of them (frappe.db.exists,
# //// get_doc, get_value).
# permission-check: ok the handler refuses a cart that is not the session's (_is_the_session_s_quotation)
@frappe.whitelist(allow_guest=True)
def create_payment_request(quotation_id: str | None = None, gateway_settings: str | None = None,
                           idempotency_token: str | None = None, payment_gateway: str | None = None):
    """Create a payment request for a quotation
    
    Args:
        quotation_id (str, optional): Quotation ID
        gateway_settings (str, optional): Gateway Settings name
        idempotency_token (str, optional): Token to prevent duplicate payment requests
        payment_gateway (str, optional): Payment Gateway name, resolved directly
            (//// Neoffice — see PaymentHandler.create_payment_request)
    """
    try:
        handler = PaymentHandler()
        return handler.create_payment_request(
            quotation_id=quotation_id, 
            gateway_settings=gateway_settings,
            idempotency_token=idempotency_token,
            # //// Neoffice — pass the direct gateway name through to the handler.
            payment_gateway=payment_gateway
        )
    # //// Neoffice — a refusal is no fault: every POST of a visitor with no cookie committed an Error Log
    # //// row. Only the guard of `PaymentHandler.create_payment_request` gets here, the rest ends in its
    # //// own except.
    except frappe.PermissionError as e:
        return {
            "status": "error",
            "message": str(e)
        }
    except Exception as e:
        # //// Neoffice — #2114: the traceback is the message; `e` alone kept str(e) (« Not permitted ») and pointed nowhere.
        frappe.log_error("Error creating payment request", frappe.get_traceback())
        return {
            "status": "error",
            "message": str(e)
        }

# //// Neoffice — who may CONCLUDE a payment request, and who may only FAIL one.
# ////
# //// To conclude (money_confirmed=True: the real order, the invoice, the payment entry) there are three cases, and
# //// none of them is "the buyer asks":
# ////   · the server itself (Administrator: a background task, the TWINT poller, the Wallee terminal driver);
# ////   · the staff (System Manager);
# ////   · the gateway's word, as the server heard it (payment_proof.py): a succeeded Payment Intent, or the receipt
# ////     of a Stripe charge that covers the request. Whoever reports it, a guest at a gateway return included:
# ////     the money is confirmed, and that is the invariant.
# //// The identity of the buyer (the request is theirs, or their Contact is its customer) is no proof of payment, so
# //// it concludes nothing (maintenance#1807). The 22.09 arbitration had accepted it because the card tile has no
# //// Payment Intent; the tile now rests on the Stripe receipt, which the server writes itself when Stripe has
# //// captured the charge.
# ////
# //// To FAIL a request (money_confirmed=False) nothing is paid out, so the buyer who opened it, or whose Contact is
# //// its customer, may still do it: the identity cases (3a, 3) stay for that, and only for that.
# //// Neoffice — RULE #00 pass (#925): renamed from `_peut_conclure(…, argent_constate=…)`.
# //// Same behaviour and the same two call sites in this file; the identifiers were the last
# //// French ones of the payment guard.
def _may_conclude(payment_request_id: str, money_confirmed: bool = True) -> bool:
	user = frappe.session.user

	# 1. the server itself (background task, server-side return page)
	# //// Neoffice — RULE #00 pass: local variable renamed from French to
	# //// English "user" (e646274dd3 "chore: RULE #00 pass on identifiers —
	# //// multi_site functions and the local variables")
	if user == "Administrator":
		return True

	# 2. staff
	# //// Neoffice — "user" renamed from French, see the marker above (e646274dd3)
	if user != "Guest" and "System Manager" in frappe.get_roles():
		return True

	# 4. the money is CONFIRMED by the gateway (payment_proof.py).
	#    Checked before the identity cases to cover a gateway return where the
	#    session has not been restored yet.
	# //// Neoffice — RULE #00 pass (#925): the flag was `argent_constate`.
	if money_confirmed:
		return payment_proof.is_confirmed(payment_request_id)

	# //// Neoffice — call site updated for the "user" rename (e646274dd3)
	if user == "Guest":
		return False

	# 3a. the BUYER who opened this request: it was created in their own session. (To fail it only: see above.)
	# //// Neoffice — measured on a live shop (2026-09-22): case 3 below resolves a
	# //// customer through the Contact whose `user` is the session's, and it returned
	# //// nothing for that shop's buyers. A guest cannot reach this line.
	if frappe.db.get_value("Payment Request", payment_request_id, "owner") == user:
		return True

	# 3. the BUYER, back from their gateway: this is their request. (To fail it only: see above.)
	# //// Neoffice — RULE #00 pass: local variables renamed from French to
	# //// English "beneficiary", "customers"/"suppliers", and the log_error title
	# //// (e646274dd3 "chore: RULE #00 pass on identifiers — multi_site functions
	# //// and the local variables")
	beneficiary = frappe.db.get_value("Payment Request", payment_request_id, "party")
	if not beneficiary:
		return False
	try:
		from erpnext.controllers.website_list_for_contact import get_customers_suppliers

		# //// Neoffice — "customers"/"suppliers" renamed from French, see the marker above (e646274dd3)
		customers, _suppliers = get_customers_suppliers("Sales Order", user)
	except Exception:
		# //// Neoffice — log_error title renamed from French, see the marker above (e646274dd3)
		frappe.log_error("Webshop: right to complete a payment", frappe.get_traceback())
		return False
	# //// Neoffice — "customers" renamed from French, see the marker above (e646274dd3)
	return beneficiary in (customers or [])


# //// Neoffice — added function (no upstream equivalent). Who hears about a request and may fail it:
# //// `_may_conclude`'s identity cases, and the visitor with no account whose cart it is, by its cookie, as
# //// `payments.integrations.web_checkout` asks. For a guest only: `get_party` can create a customer. A name
# //// that does not exist is nobody's, so it is refused like a request of somebody else.
def _is_the_buyer(payment_request_id):
    if _may_conclude(payment_request_id, money_confirmed=False):
        return True
    if frappe.session.user != "Guest":
        return False
    row = frappe.db.get_value(
        "Payment Request", payment_request_id, ["reference_doctype", "reference_name"], as_dict=True
    )
    return bool(row) and _is_the_session_s_quotation(_cart_of_request(row))


# //// Neoffice — a text: in a JSON body it was a filter, in frappe.db.exists and in frappe.get_doc.
@frappe.whitelist(allow_guest=True)
def handle_payment_success(payment_request_id: str, transaction_data=None):
    """Handle payment success with Stripe"""
    # //// Neoffice — a refusal is a refusal, a 403 with no Error Log row: it answered 200, and wrote a row
    # //// per call for anyone, on a request that does not move. Whoever may conclude passes, and the buyer,
    # //// who is told where the payment stands. Before the try below, which would log it. The Python
    # //// callers (gateway returns, webhooks, pollers) hold the proof or run as the server, and catch what
    # //// they call.
    if not (_may_conclude(payment_request_id) or _is_the_buyer(payment_request_id)):
        frappe.throw(_("Not permitted"), frappe.PermissionError)
    try:
        handler = PaymentHandler()
        return handler.handle_payment_success(payment_request_id=payment_request_id, transaction_data=transaction_data)
    except Exception:
        # //// Neoffice — #2114: the traceback is the message; `e` alone kept str(e) (« Not permitted ») and pointed nowhere.
        frappe.log_error("Detailed error while processing payment", frappe.get_traceback())
        return {
            "status": "error",
            "message": _("Error processing payment")
        }

# //// Neoffice — texts: in a JSON body `payment_request_id` was the filter of the check AND of the UPDATE,
# //// and one request of the caller's own let that UPDATE reach the requests of every customer.
@frappe.whitelist(allow_guest=True)
def handle_payment_failure(payment_request_id: str, error_message: str | None = None):
    """Handle payment failure"""
    # //// Neoffice — a real refusal, see handle_payment_success. A buyer is never refused here: the card tile
    # //// unfreezes in its callback, which a 403 skips, so a guest's cart counts as theirs (_is_the_buyer).
    if not _is_the_buyer(payment_request_id):
        frappe.throw(_("Not permitted"), frappe.PermissionError)
    try:
        handler = PaymentHandler()
        return handler.handle_payment_failure(payment_request_id, error_message)
    except Exception:
        # //// Neoffice — #2114: the traceback is the message; `e` alone kept str(e) (« Not permitted ») and pointed nowhere.
        frappe.log_error("Detailed error while processing payment failure", frappe.get_traceback())
        return {
            "status": "error",
            "message": _("Error processing payment failure")
        }

# //// Neoffice — a text: it names a cache key.
# permission-check: ok the session's own cart, and only when it has nothing to pay
@frappe.whitelist(allow_guest=True)
def handle_direct_order(idempotency_token: str | None = None):
    """Handle direct order validation without payment"""
    try:
        # //// Neoffice — this door is the checkout's zero-amount button: a cart with nothing to pay, a gift
        # //// card spent in full. Only the browser knew that, so any signed-in customer got a submitted order
        # //// and its invoice on credit the shop never offered. An amount to pay goes through a method the
        # //// buyer is offered (create_payment_request, place_offline_order), and a B2B customer orders from
        # //// /checkout-b2b. An answer, not a 403: a buyer lands here when a gift card leaves the cart in
        # //// another tab, and checkout.js shows this message. Here and not in the class: the browser's
        # //// claim comes in through this door.
        quotation = _get_cart_quotation()
        if not quotation or flt(quotation.rounded_total or quotation.grand_total) > 0:
            return {
                "status": "error",
                "message": _("This order has an amount to pay. Please choose a payment method.")
            }

        handler = PaymentHandler()
        return handler.handle_direct_order(idempotency_token=idempotency_token)
    except Exception as e:
        frappe.log_error("Error while validating order", str(e))
        return {
            "status": "error",
            "message": _("An error occurred while validating the order")
        }
