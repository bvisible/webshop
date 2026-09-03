# //// Neoffice — added file (purchase follow-ups, no upstream equivalent).
"""A follow-up: after a purchase of X, these emails, these many days later.

The flow is the definition; what actually happens to a customer is a
Purchase Follow-up Entry (one per purchase and item), created on submit of
the order and advanced every morning by utils/follow_ups.py.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

TRIGGER_FIELD = {"Item": "trigger_item", "Item Group": "trigger_item_group", "Brand": "trigger_brand"}


class PurchaseFollowup(Document):
	def validate(self):
		field = TRIGGER_FIELD.get(self.trigger_type)
		if field and not self.get(field):
			frappe.throw(_("Pick what the follow-up starts from."))
		for other in TRIGGER_FIELD.values():
			if other != field:
				self.set(other, None)
		if not self.steps:
			frappe.throw(_("A follow-up needs at least one email."))
		previous = -1
		for step in self.steps:
			if not step.use_item_cycle and cint(step.days_after) < 0:
				frappe.throw(_("Step {0}: the delay cannot be negative.").format(step.idx))
			if not step.use_item_cycle and cint(step.days_after) < previous:
				frappe.throw(_("Step {0}: the emails must be in chronological order.").format(step.idx))
			if not step.use_item_cycle:
				previous = cint(step.days_after)
