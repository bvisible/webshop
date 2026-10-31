# //// Neoffice — added file (no upstream equivalent). One reseller's access to the partner API: the request they
# //// made, what staff allowed, the state it is in and the hash of its key (2026-11-01).
from frappe.model.document import Document

REQUESTED, ACTIVE, SUSPENDED, REFUSED = "Requested", "Active", "Suspended", "Refused"


class PartnerAPIAccess(Document):
	pass
