# Copyright (c) 2026, Neoffice. What a fresh install puts in the desk.
import frappe
from frappe.tests.utils import FrappeTestCase


class TestDesk(FrappeTestCase):
	"""The features have to be reachable, not only importable."""

	def test_the_webshop_workspace_is_installed(self):
		"""A fresh site gets the workspace with its shortcuts and cards."""
		self.assertTrue(frappe.db.exists("Workspace", "Webshop"))
		workspace = frappe.get_doc("Workspace", "Webshop")
		self.assertEqual(workspace.parent_page, "Website")
		self.assertTrue(workspace.public)
		linked = {row.link_to for row in workspace.links if row.type == "Link"}
		for doctype in ("Cross Sell Offer", "Purchase Follow-up", "Purchase Follow-up Entry", "Abandoned Cart Reminder", "Webshop Settings"):
			self.assertIn(doctype, linked)
		self.assertIn("/occasions", {row.url for row in workspace.shortcuts})

	def test_every_workspace_link_points_at_an_installed_doctype(self):
		workspace = frappe.get_doc("Workspace", "Webshop")
		for row in workspace.links:
			if row.type == "Link" and row.link_type == "DocType":
				self.assertTrue(frappe.db.exists("DocType", row.link_to), row.link_to)
		for row in workspace.shortcuts:
			if row.type == "DocType":
				self.assertTrue(frappe.db.exists("DocType", row.link_to), row.link_to)

	def test_orders_invoices_and_quotations_show_the_emails_they_triggered(self):
		# The dashboard data is what the form's "Connections" section reads.
		from frappe.desk.form.meta import get_meta

		for doctype, fieldname in (
			("Sales Order", "source_name"),
			("Sales Invoice", "source_name"),
			("Quotation", "quotation"),
		):
			data = get_meta(doctype).get_dashboard_data()
			labels = {t["label"] for t in data.get("transactions", [])}
			self.assertIn("Webshop emails", labels, doctype)
			if doctype == "Quotation":
				self.assertEqual(data["non_standard_fieldnames"]["Abandoned Cart Reminder"], fieldname)
			else:
				self.assertEqual(data["non_standard_fieldnames"]["Purchase Follow-up Entry"], fieldname)
				self.assertEqual(data["dynamic_links"]["source_name"], [doctype, "source_doctype"])

	def test_a_follow_up_lists_the_customers_it_enrolled(self):
		from frappe.desk.form.meta import get_meta

		data = get_meta("Purchase Follow-up").get_dashboard_data()
		self.assertEqual(data.get("fieldname"), "flow")
		self.assertIn("Purchase Follow-up Entry", data["transactions"][0]["items"])
