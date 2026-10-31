# //// Neoffice — added file (no upstream equivalent). The order a partner API call made, found again by the call's
# //// idempotency key: a call replayed after a cut connection returns the order, it does not make a second one.
from frappe.model.document import Document


class PartnerAPIOrder(Document):
	pass
