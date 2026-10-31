# //// Neoffice — added file (no upstream equivalent). One catalogue a reseller asked for: what it was made
# //// from, how far the job is, and the private PDF it produced (2026-10-31).
import frappe
from frappe.model.document import Document

QUEUED, RUNNING, READY, FAILED = "Queued", "Running", "Ready", "Failed"


class ResellerCatalogue(Document):
	def on_trash(self):
		"""The PDF goes with the record: a private file nobody can reach any more is still somebody's data."""
		for name in frappe.get_all(
			"File", filters={"attached_to_doctype": self.doctype, "attached_to_name": self.name}, pluck="name"
		):
			frappe.delete_doc("File", name, ignore_permissions=True, force=True)
