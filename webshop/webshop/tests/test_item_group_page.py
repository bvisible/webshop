# //// Neoffice — added file (no upstream equivalent).
"""The category page's title: the heading is the category's name, the browser tab
adds the shop's name after it.

`context.title` is what the site chrome prints as the H1 and as the last breadcrumb;
the shop name belongs to `context.html_title`, which the template feeds to the
<title> tag only. Reported on a client shop on 2026-09-11 as "Fleece | <shop>"
printed as the page heading.
"""

import re
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.tests.utils import leaf_item_group


class TestItemGroupPage(FrappeTestCase):
	def _published_group(self):
		name = frappe.db.get_value("Item Group", {"show_in_website": 1, "is_group": 0}, "name")
		if not name:
			name = frappe.db.get_value("Item Group", {"show_in_website": 1}, "name")
		if name:
			return frappe.get_doc("Item Group", name)
		# //// Neoffice — a fresh site publishes no group, and a skipped test reads exactly like a
		# //// passing one (#399): publish one for the test instead of standing down.
		group = frappe.get_doc("Item Group", leaf_item_group())
		group.show_in_website = 1
		group.save()
		return group

	def test_heading_is_the_name_and_tab_title_adds_the_shop(self):
		group = self._published_group()
		context = frappe._dict(metatags={})
		group.get_context(context)

		expected = group.website_title or group.name
		self.assertEqual(context.title, expected)
		self.assertNotIn(" | ", context.title)

		# //// Neoffice — the suffix is the site's one name (seo/site.py shop_name), the name the
		# //// home page declares to Google, since 2026-09-24 (#691).
		from webshop.webshop.seo.site import shop_name

		shop = shop_name()
		if shop:
			self.assertEqual(context.html_title, f"{expected} | {shop}")
		else:
			self.assertEqual(context.html_title, expected)


	def test_the_controller_fills_everything_its_own_template_reads(self):
		"""`window.discount_count` was read by the template and set by nobody: the discount
		facet disappeared from every category page while /all-products kept it (2026-09-22).
		The template is the contract; this reads it rather than naming the variables again."""
		template = (Path(__file__).resolve().parents[2] / "templates" / "generators" / "item_group.html").read_text()
		expected = sorted(set(re.findall(r"window\.[a-z_]+ = \{\{ *([a-z_]+)", template)))
		self.assertIn("discount_count", expected, "the template stopped reading the counts")

		group = self._published_group()
		context = frappe._dict(metatags={})
		group.get_context(context)
		missing = [name for name in expected if context.get(name) is None]
		self.assertEqual(missing, [], f"read by item_group.html, set by nobody: {missing}")

