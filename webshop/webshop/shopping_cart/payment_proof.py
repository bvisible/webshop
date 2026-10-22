# //// Neoffice — added file (no upstream equivalent). What proves, on the server, that a Payment Request was paid.
"""Proof that a payment arrived: the gateway's word, as the server heard it.

A payment request is concluded (the real order, the invoice, the payment entry) only on a proof that does not come
from whoever asks. Who the buyer is says nothing about whether the gateway took the money (maintenance#1807).

| Gateway                       | How the money is known to the server                                                  |
|-------------------------------|---------------------------------------------------------------------------------------|
| Wallee, Payrexx, TWINT        | a Payment Intent of the request in `succeeded`, written by the gateway's webhook, by  |
|                               | the poller or by the return page after it asked the gateway                           |
| Stripe card tile              | the receipt of the charge (`payments.utils.stripe_receipt`): the server asked Stripe, |
|                               | read the answer, and the amount it reported covers the request                        |
| PayPal                        | not here: `confirm_payment` asks PayPal for the payment and only then runs            |
|                               | `on_payment_authorized` of the request                                                |
| Offline (transfer, on         | no payment to conclude: the order is placed, the money follows (`offline_payment.py`) |
| delivery)                     |                                                                                       |

The staff (System Manager) and the server itself (Administrator: a background task, the TWINT poller) conclude
without a proof: they are the ones who answer for it.
"""

import frappe


def intent_succeeded(payment_request_id: str) -> bool:
	"""A Payment Intent of this request that the gateway reported `succeeded`."""
	try:
		return bool(
			frappe.db.exists("DocType", "Payment Intent")
			and frappe.db.exists(
				"Payment Intent",
				{"reference_doctype": "Payment Request", "reference_name": payment_request_id, "status": "succeeded"},
			)
		)
	except Exception:
		return False


def stripe_charge_covers(payment_request_id: str) -> bool:
	"""Stripe captured a charge for this request, for the amount and the currency it asks."""
	try:
		from payments.utils import stripe_receipt
	except ImportError:  # the payments app is not installed: there is no card charge to read
		return False
	return stripe_receipt.covers(payment_request_id)


def is_confirmed(payment_request_id: str) -> bool:
	"""The gateway has told the server that this request was paid."""
	return intent_succeeded(payment_request_id) or stripe_charge_covers(payment_request_id)
