# //// Neoffice — added file (no upstream equivalent): what a visitor may read of Webshop Settings.
# //// neoffice-maintenance#711, 2026-09-24.
"""get_shopping_cart_settings (allow_guest) and the listing API returned the whole settings
document to anyone: the assistant's model endpoint, its Raven channel and support address, its
token price and knowledge text. Over HTTP they now return the display switches a page's script
reads; a Python caller keeps the document."""

from types import SimpleNamespace

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.doctype.webshop_settings import webshop_settings
from webshop.webshop.doctype.webshop_settings.webshop_settings import (
	PUBLIC_SETTINGS,
	SETTINGS_METHOD,
	get_shopping_cart_settings,
)

# Nothing whose name says it is an address, an endpoint or a credential is ever public.
PRIVATE_MARKERS = ("email", "url", "key", "token", "secret", "password", "assistant", "smtp", "webhook")


class _Request:
	"""frappe.local.form_dict and frappe.local.request for one call."""

	def __init__(self, cmd=None, path=None):
		self.cmd, self.path = cmd, path

	def __enter__(self):
		self.saved = (frappe.local.form_dict, getattr(frappe.local, "request", None))
		frappe.local.form_dict = frappe._dict({"cmd": self.cmd} if self.cmd else {})
		frappe.local.request = SimpleNamespace(path=self.path) if self.path else None

	def __exit__(self, *args):
		frappe.local.form_dict, frappe.local.request = self.saved


class TestPublicSettings(FrappeTestCase):
	def test_no_address_endpoint_or_credential_is_public(self):
		meta = frappe.get_meta("Webshop Settings")
		for fieldname in PUBLIC_SETTINGS:
			with self.subTest(fieldname=fieldname):
				self.assertFalse(any(marker in fieldname for marker in PRIVATE_MARKERS))
				field = meta.get_field(fieldname)
				if field:
					self.assertNotEqual(field.fieldtype, "Password")

	def test_over_http_a_visitor_reads_the_display_switches(self):
		for request in (
			_Request(cmd=SETTINGS_METHOD),
			_Request(path=f"/api/v2/method/{SETTINGS_METHOD}"),
		):
			with self.subTest(request=vars(request)), request:
				settings = get_shopping_cart_settings()
			self.assertEqual(set(settings), set(PUBLIC_SETTINGS))

	def test_a_python_caller_keeps_the_document(self):
		# inside another request (a page, the listing API) the caller is not this endpoint
		with _Request(cmd="webshop.webshop.api.get_product_filter_data", path="/all-products"):
			settings = get_shopping_cart_settings()
		self.assertIn("price_list", settings)
		self.assertGreater(len(settings), len(PUBLIC_SETTINGS))

	def test_the_listing_api_sends_the_display_switches_only(self):
		from webshop.webshop.api import get_product_filter_data

		result = get_product_filter_data({"field_filters": {}, "attribute_filters": {}, "start": 0})
		self.assertTrue(set(result["settings"]) <= set(PUBLIC_SETTINGS))
		# what views.js reads from it
		self.assertIn("products_per_page", result["settings"])
		self.assertIn("enable_infinite_scroll", result["settings"])

	def test_called_over_http_names_the_endpoint_itself(self):
		with _Request(cmd=SETTINGS_METHOD):
			self.assertTrue(webshop_settings.called_over_http(SETTINGS_METHOD))
		with _Request(path=f"/api/method/{SETTINGS_METHOD}/"):
			self.assertTrue(webshop_settings.called_over_http(SETTINGS_METHOD))
		with _Request(path="/all-products"):
			self.assertFalse(webshop_settings.called_over_http(SETTINGS_METHOD))
