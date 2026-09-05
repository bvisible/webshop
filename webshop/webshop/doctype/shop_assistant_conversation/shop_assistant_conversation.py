# //// Neoffice — added file (shop assistant, no upstream equivalent).
import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class ShopAssistantConversation(Document):
	"""One thread between a visitor and the shop assistant.

	The identity (`user`, `customer`, or the guest cookie) is set by the API from
	the session that opened it and never from the browser. Messages, tokens and
	the escalation are appended by the engine.
	"""

	def before_insert(self):
		self.started_on = self.started_on or now_datetime()
		self.last_message_on = self.last_message_on or self.started_on

	def validate(self):
		# //// Neoffice — was: len([m for m in self.messages if m.role in ("user", "assistant")]),
		# //// which also counted the assistant's own tool-call turns (807c98474e "test(assistant):
		# //// des réglages en mémoire, pas d'écriture dans tabSingles").
		# what the visitor saw: their turns and the assistant's answers, not the
		# assistant's requests for tools
		self.message_count = len([m for m in self.messages if m.role == "user" or (m.role == "assistant" and not m.tool_calls)])
		self.prompt_tokens = sum(int(m.prompt_tokens or 0) for m in self.messages)
		self.completion_tokens = sum(int(m.completion_tokens or 0) for m in self.messages)

	def add_message(self, role, content, **fields):
		row = self.append(
			"messages",
			dict(role=role, content=content or "", sent_on=now_datetime(), **fields),
		)
		self.last_message_on = row.sent_on
		return row


def customer_dashboard_items():
	return ["Shop Assistant Conversation"]
