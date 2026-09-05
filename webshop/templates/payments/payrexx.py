# //// Neoffice — added file (no upstream equivalent).
"""Webshop Payrexx glue.

Payrexx hosted checkout is a plain redirect, so this module is thinner than its
Wallee and TWINT siblings: no iframe mode to read, no QR to build, no in-page SDK.
The transaction itself is created by
:mod:`payments.integrations.payrexx.api`, and the buyer is sent to the URL it
returns.

The checkout template only needs to know whether the option can be offered.
"""

import frappe


@frappe.whitelist(allow_guest=True)
def is_payrexx_enabled():
    """Whether the checkout should show the Payrexx option.

    Delegates to the payments app, which checks both that an enabled Payrexx
    Payment Provider exists and that it has a binding for the web channel — a
    provider configured for the POS terminal alone cannot serve a webshop payment,
    and offering it would only fail once the buyer clicks.

    Returns False rather than raising when the payments app is absent, so a site
    without it still renders its checkout.
    """
    try:
        from payments.integrations.payrexx.api import is_payrexx_enabled as _enabled
    except ImportError:
        return False
    return _enabled()
