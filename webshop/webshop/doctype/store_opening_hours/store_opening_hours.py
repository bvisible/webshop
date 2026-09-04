# //// Neoffice — added file (store hours, no upstream equivalent).
from frappe.model.document import Document


class StoreOpeningHours(Document):
	"""One opening period of one weekday; a day with a lunch break has two rows."""
