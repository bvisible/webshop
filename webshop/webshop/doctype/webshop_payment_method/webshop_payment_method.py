# //// Neoffice — added file (no upstream equivalent). Child table of the checkout
# //// tiles: one row per method offered, with its gateway, its template path and its
# //// order (3bc2d836f1, 2025-02-11).
# //// Neoffice — `use_payment_intent` ships UNCHECKED on purpose. Unchecked, a
# //// method takes exactly the capture path it has always taken; ticking it moves
# //// the capture to the payment-intent engine, which has to be proven on the site
# //// first. This rationale used to sit in the field's `description`, where the
# //// desk rendered a //// marker to end users (RULE #00 pass, tracker #225).
import frappe
from frappe.model.document import Document

class WebshopPaymentMethod(Document):
    pass
