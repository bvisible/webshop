# //// Neoffice — added file (shop assistant, no upstream equivalent).
from frappe.model.document import Document


class ShopAssistantMessage(Document):
	"""One turn of a conversation: what was said, or what a tool answered, and what it cost."""
