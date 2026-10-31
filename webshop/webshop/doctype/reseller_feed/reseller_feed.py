# //// Neoffice — added file (no upstream equivalent). A reseller's product feed: what it is made from, how far its
# //// refresh is, and the secret address it is read at. The two files (CSV and JSON) live in the site's private folder.
import frappe
from frappe.model.document import Document

QUEUED, RUNNING, READY, FAILED = "Queued", "Running", "Ready", "Failed"


class ResellerFeed(Document):
	def autoname(self):
		"""A reseller's first feed is named after them (what the first version did, and what its files and its
		address are keyed by); the others get a random name. `flags.name_it` is the name feed.save chose."""
		if self.flags.name_it:
			self.name = self.flags.name_it

	def on_trash(self):
		"""The files go with the record: a feed nobody can reach any more is still somebody's data."""
		from webshop.webshop.catalogue import feed

		feed.remove_files(self.name)
