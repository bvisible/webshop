# //// Neoffice — added file (shop assistant, no upstream equivalent).
from frappe.model.document import Document


class ShopAssistantSample(Document):
	"""One anonymised pair of question and answer, written by `assistant.samples.collect` and by nothing else.

	It holds no link to the conversation, no user, no cookie, no address: only the day. It lives for a time of its own and is
	not used for anything until a person has read it and ticked "approved".
	"""
