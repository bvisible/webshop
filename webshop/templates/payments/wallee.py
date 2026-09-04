#//// Neoffice — added file (no upstream equivalent). Glue for the Wallee tile: reads
#//// the configured checkout mode and owns the route URLs the JS relies on. The
#//// transaction itself lives in the `payments` app (043924b1d5, 2025-12-10).
"""Webshop Wallee glue.

The actual transaction creation lives in :mod:`payments.integrations.wallee.api`
since the fusion of ``wallee_integration`` into the ``payments`` app. The
webshop only needs to (1) read which checkout mode is configured and (2) own
the route URLs (which are stable contract for the JS template).

The legacy ``create_wallee_payment_request`` endpoint was removed: the webshop
JS now follows the same 2-step pattern as Stripe — create the Payment Request
via ``payment_handler.create_payment_request(gateway_settings="Wallee Settings")``,
then call ``payments.integrations.wallee.api.create_web_transaction`` to get
the Wallee URL.
"""

import frappe
from frappe import _


@frappe.whitelist(allow_guest=True)
def get_payment_mode():
    """Return the Wallee hosted-checkout mode (Redirect / Lightbox / iFrame).

    Reads the first enabled Wallee Payment Provider's ``Wallee Settings`` record
    (the doctype is no longer a singleton — there is one record per provider).
    Falls back to ``Redirect`` if no Wallee provider is configured.
    """
    provider = frappe.db.get_value(
        "Payment Provider",
        {"driver_class": ["like", "payments.drivers.wallee.%"], "enabled": 1},
        "name",
        order_by="modified desc",
    )
    if not provider:
        return "Redirect"
    return (
        frappe.db.get_value("Wallee Settings", {"provider": provider}, "payment_mode")
        or "Redirect"
    )


def get_taxes_for_line_items(doctype, name):
    """Extract percentage-based tax rows for Wallee LineItem taxes.

    Wallee expects a list of ``{title, rate}`` dicts (rate as percentage string,
    e.g. ``"7.7"``). Only rate-based tax rows are forwarded; ``Actual`` charges
    (shipping, fees) are added as separate line items upstream, not as taxes on
    individual products.

    Inlined here (was ``wallee_integration.api.tax_utils.get_taxes_for_line_items``
    before the fusion) so the webshop has no runtime dependency on the payments
    app's internal helpers.
    """
    try:
        doc = frappe.get_doc(doctype, name)
    except frappe.DoesNotExistError:
        return []

    taxes = []
    for tax_row in (doc.taxes or []):
        if tax_row.charge_type in (
            "On Net Total",
            "On Previous Row Amount",
            "On Previous Row Total",
        ) and tax_row.rate:
            taxes.append(
                {"title": tax_row.description or _("Tax"), "rate": str(tax_row.rate)}
            )
    return taxes
