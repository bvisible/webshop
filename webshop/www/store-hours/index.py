# //// Neoffice — added file (store hours, no upstream equivalent).
"""The public /store-hours page: opening hours, address and phone, to link
from a menu, an email or the shop assistant."""

import frappe
from frappe import _

from webshop.webshop.utils.store_hours import opening_hours

no_cache = 1


def get_context(context):
	context.title = _("Opening hours")
	context.parents = [{"name": _("Home"), "route": "/"}]
	context.hours = opening_hours()
	context.no_cache = 1
	return context
