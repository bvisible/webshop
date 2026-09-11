# //// Neoffice — added file (no upstream equivalent).
"""The category page's title: the heading is the category's name, the browser tab
adds the shop's name after it.

`context.title` is what the site chrome prints as the H1 and as the last breadcrumb;
the shop name belongs to `context.html_title`, which the template feeds to the
<title> tag only. Reported on a client shop on 2026-09-11 as "Fleece | <shop>"
printed as the page heading.
"""

import frappe
from frappe.tests.utils import FrappeTestCase


class TestItemGroupPage(FrappeTestCase):
	def _published_group(self):
		name = frappe.db.get_value("Item Group", {"show_in_website": 1, "is_group": 0}, "name")
		if not name:
			name = frappe.db.get_value("Item Group", {"show_in_website": 1}, "name")
		if not name:
			self.skipTest("no item group is published on this site")
		return frappe.get_doc("Item Group", name)

	def test_heading_is_the_name_and_tab_title_adds_the_shop(self):
		group = self._published_group()
		context = frappe._dict(metatags={})
		group.get_context(context)

		expected = group.website_title or group.name
		self.assertEqual(context.title, expected)
		self.assertNotIn(" | ", context.title)

		shop = frappe.db.get_single_value("Website Settings", "app_name")
		if shop and shop != "Frappe":
			self.assertEqual(context.html_title, f"{expected} | {shop}")
		else:
			self.assertEqual(context.html_title, expected)
