# //// Neoffice — added file (no upstream equivalent). Webshop comes after payments in installed_apps, so
# //// this template serves /payment-success in place of payments' page, with none of its checks.
# Copyright (c) 2026, Neoffice and contributors
# License: MIT. See LICENSE
"""/payment-success as a visitor reaches it, through the website router."""

from urllib.parse import urlencode

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import set_request
from frappe.website.serve import get_response

BASE = "http://payment-success.test"
SCRIPT = '"></script><script>alert(1)</script>'


def _render(**query) -> tuple[int, str]:
	values = {key: value for key, value in query.items() if isinstance(value, str)}
	set_request(method="GET", path="/payment-success", query_string=urlencode(values), base_url=BASE)
	frappe.form_dict.clear()
	frappe.form_dict.update(query)
	response = get_response()
	return response.status_code, response.get_data(as_text=True)


class TestPaymentSuccessPage(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Guest")
		self.addCleanup(self._leave)

	def _leave(self):
		frappe.set_user("Administrator")
		frappe.form_dict.clear()
		frappe.local.request = None
		frappe.clear_messages()

	def test_a_filter_for_a_name_is_refused(self):
		status, _ = _render(doctype="Payment Request", docname={"name": ["like", "%"]})
		self.assertEqual(status, 403)

	def test_a_name_that_exists_nowhere_reads_like_any_other(self):
		status, page = _render(doctype="Payment Request", docname="_no such request")
		self.assertEqual(status, 200)
		self.assertIn("/orders", page)

	def test_the_page_runs_nothing_it_was_handed(self):
		status, page = _render(redirect_to=SCRIPT)
		self.assertEqual(status, 200)
		self.assertNotIn("<script>alert(1)", page)

	def test_the_page_leaves_for_no_other_site_and_no_script_address(self):
		for target in ("javascript:alert(1)", "https://elsewhere.example/x", "//elsewhere.example/x"):
			with self.subTest(target=target):
				status, page = _render(redirect_to=target)
				self.assertEqual(status, 200)
				self.assertNotIn(target, page)
				self.assertIn('"/orders"', page)

	def test_the_way_back_to_the_shop_still_works(self):
		status, page = _render(redirect_to="/orders/SAL-ORD-1")
		self.assertEqual(status, 200)
		self.assertIn('"/orders/SAL-ORD-1"', page)

	def test_each_visitor_gets_their_own_page(self):
		_render(redirect_to="/orders/FIRST")
		_status, page = _render(redirect_to="/orders/SECOND")
		self.assertIn('"/orders/SECOND"', page)
		self.assertNotIn("/orders/FIRST", page)
