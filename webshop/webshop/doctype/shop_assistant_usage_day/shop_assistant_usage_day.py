# //// Neoffice — added file (shop assistant, no upstream equivalent).
from frappe.model.document import Document


class ShopAssistantUsageDay(Document):
	"""One day of the assistant's counters: how many requests came, how many were answered or refused and why.

	Written by `assistant.usage.flush` from the Redis counters, never typed. It holds figures only: no word a visitor
	wrote and no address, so it stays as long as the shop is billed from it.
	"""
