#//// Neoffice — added file (no upstream equivalent).
#//// Reconciles the data of the former standalone `webshopsi_integration` app so it
#//// can be uninstalled without losing the configured instalment plans (662c26b650,
#//// 2026-05-26). The module docstring below states the two steps and their order.
"""Fold the former `webshopsi_integration` app into `webshop`.

The "Facture / pay-by-invoice" payment method used to live in a standalone
app. Its three DocTypes (WebshopSI Settings + two child tables), its cart
logic, its checkout template and its two Custom Field patches now ship with
webshop. This patch reconciles existing data so the standalone app can be
uninstalled without losing anything:

1. Reassign the three DocTypes from the old "WebshopSI Integration" module to
   "Webshop". This MUST run before the old app is uninstalled — otherwise the
   uninstall would drop the DocTypes (and their data: the configured
   installment plans) along with the old module.

2. Repoint the ``Webshop Payment Method.template_path`` for the Facture
   gateway from the old app path to the webshop one, so the checkout keeps
   finding the template after the old app is gone.

Idempotent: safe to re-run.
"""

import frappe

_DOCTYPES = (
	"WebshopSI Settings",
	"WebshopSI Invoice Installments",
	"WebshopSI Country",
)

_OLD_TEMPLATE_PATH = (
	"apps/webshopsi_integration/webshopsi_integration/templates/payments/webshopsi.html"
)
_NEW_TEMPLATE_PATH = "apps/webshop/webshop/templates/payments/webshopsi.html"


def execute():
	# 1. Reassign the DocTypes to the Webshop module (only those that exist).
	for dt in _DOCTYPES:
		if frappe.db.exists("DocType", dt):
			current = frappe.db.get_value("DocType", dt, "module")
			if current != "Webshop":
				frappe.db.set_value("DocType", dt, "module", "Webshop", update_modified=False)

	# 2. Repoint the Facture payment method template path(s).
	rows = frappe.get_all(
		"Webshop Payment Method",
		filters={"template_path": _OLD_TEMPLATE_PATH},
		pluck="name",
	)
	for name in rows:
		frappe.db.set_value(
			"Webshop Payment Method", name, "template_path", _NEW_TEMPLATE_PATH, update_modified=False
		)

	# Catch any variant that still points inside the old app.
	stragglers = frappe.get_all(
		"Webshop Payment Method",
		filters={"template_path": ["like", "apps/webshopsi_integration/%"]},
		pluck="name",
	)
	for name in stragglers:
		frappe.db.set_value(
			"Webshop Payment Method", name, "template_path", _NEW_TEMPLATE_PATH, update_modified=False
		)

	frappe.db.commit()
