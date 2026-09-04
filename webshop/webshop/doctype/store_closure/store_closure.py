# //// Neoffice — added file (store hours, no upstream equivalent).
from frappe.model.document import Document


class StoreClosure(Document):
	"""Days the store is closed regardless of the weekly hours: holidays, inventory, a move."""
