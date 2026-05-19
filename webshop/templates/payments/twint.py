"""Webshop TWINT glue.

The actual transaction creation lives in :mod:`payments.integrations.twint.api`
since the fusion of ``twint_integration`` into the ``payments`` app (Phase 11).
This module only exposes a thin helper used by the Jinja template — the JS
itself (``frappe.twint.processPayment``) is shipped by the ``payments`` app
via ``app_include_js`` / ``web_include_js`` hooks.
"""

import frappe


@frappe.whitelist(allow_guest=True)
def is_twint_enabled():
    """Quick guard so the checkout template can hide the TWINT option when no
    provider is configured.

    Returns True only when there is BOTH an enabled TWINT Payment Provider
    AND a Twint Bridge Settings record (the per-merchant config that carries
    the store_uuid + cert references on neoservice).
    """
    provider = frappe.db.get_value(
        "Payment Provider",
        {"driver_class": ["like", "payments.drivers.twint.%"], "enabled": 1},
        "name",
    )
    if not provider:
        return False
    return bool(frappe.db.exists("Twint Bridge Settings", {}))
