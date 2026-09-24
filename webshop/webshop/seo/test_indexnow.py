# //// Neoffice — added file (no upstream equivalent): IndexNow (seo/indexnow.py). #691 lot 4.
"""What IndexNow hears of, and how: nothing while switched off, the pages of what changed, one
request per site open to search engines, and the key at the root of each site."""

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.seo import indexnow

KEY = "0123456789abcdef0123456789abcdef"


def _settings(enabled=1, key=KEY):
	"""Webshop Settings as get_cached_doc returns it, in memory: nothing written to the Single."""
	return frappe._dict(enable_indexnow=enabled, indexnow_key=key)


def _item(published, route, before=None):
	doc = MagicMock(published=published, route=route)
	doc.get_doc_before_save.return_value = before
	return doc


class TestQueue(FrappeTestCase):
	def setUp(self):
		frappe.cache.delete_value(indexnow.QUEUE_KEY)
		self.addCleanup(frappe.cache.delete_value, indexnow.QUEUE_KEY)

	def test_nothing_is_queued_while_switched_off(self):
		with patch("frappe.get_cached_doc", return_value=_settings(enabled=0)):
			indexnow.queue_routes(["shop/a"])
		self.assertEqual(indexnow.take_queue(), [])

	def test_a_published_page_its_old_address_and_a_withdrawn_one(self):
		with patch("frappe.get_cached_doc", return_value=_settings()):
			renamed = _item(1, "shop/new-name", frappe._dict(published=1, route="shop/old-name"))
			indexnow.queue_website_item(renamed, "on_update")
			withdrawn = _item(0, "shop/withdrawn", frappe._dict(published=1, route="shop/withdrawn"))
			indexnow.queue_website_item(withdrawn, "on_update")
			draft = _item(0, "shop/draft", frappe._dict(published=0, route="shop/draft"))
			indexnow.queue_website_item(draft, "on_update")
			deleted = _item(1, "shop/deleted")
			indexnow.queue_website_item(deleted, "on_trash")
			# saved twice, sent once: the queue is a set
			indexnow.queue_website_item(renamed, "on_update")
		self.assertEqual(indexnow.take_queue(), ["shop/deleted", "shop/new-name", "shop/old-name", "shop/withdrawn"])
		self.assertEqual(indexnow.take_queue(), [], "taking the queue empties it")

	def test_a_selling_price_queues_the_item_and_its_model(self):
		with (
			patch("frappe.get_cached_doc", return_value=_settings()),
			patch("frappe.db.get_value", return_value="TEE"),
			patch("frappe.get_all", return_value=["shop/tee", "shop/tee-red-m"]) as get_all,
		):
			indexnow.queue_item_price(frappe._dict(selling=1, item_code="TEE-RED-M"), "on_update")
			indexnow.queue_item_price(frappe._dict(selling=0, buying=1, item_code="TEE-RED-M"), "on_update")
		self.assertEqual(get_all.call_count, 1, "a buying price is not on any page")
		self.assertEqual(get_all.call_args.kwargs["filters"]["item_code"], ["in", ["TEE-RED-M", "TEE"]])
		self.assertEqual(indexnow.take_queue(), ["shop/tee", "shop/tee-red-m"])


class TestSubmit(FrappeTestCase):
	SITES = [
		frappe._dict(key="shop", profile=frappe._dict(name="Shop", primary_domain="shop.test")),
		frappe._dict(key="pro", profile=frappe._dict(name="Pro", primary_domain="pro.test", b2b_only=1)),
	]

	def submit(self, settings, response):
		with (
			patch("frappe.get_cached_doc", return_value=settings),
			patch.object(indexnow, "take_queue", return_value=["shop/a", "shop/b"]) as take,
			patch("webshop.webshop.seo.feeds.google.feed_sites", return_value=self.SITES),
			patch("requests.post", return_value=response) as post,
			patch("frappe.log_error") as log_error,
		):
			indexnow.submit_queue()
		return take, post, log_error

	def test_one_request_per_site_open_to_engines_naming_its_key_file(self):
		_take, post, log_error = self.submit(_settings(), MagicMock(status_code=202))
		self.assertEqual(post.call_count, 1, "the business-only site is left out, as robots.txt closes it")
		self.assertEqual(post.call_args.args[0], indexnow.ENDPOINT)
		self.assertEqual(
			post.call_args.kwargs["json"],
			{
				"host": "shop.test",
				"key": KEY,
				"keyLocation": f"https://shop.test/{KEY}.txt",
				"urlList": ["https://shop.test/shop/a", "https://shop.test/shop/b"],
			},
		)
		log_error.assert_not_called()

	def test_nothing_leaves_while_switched_off_and_a_refusal_is_logged(self):
		take, post, _log_error = self.submit(_settings(enabled=0), MagicMock(status_code=202))
		take.assert_not_called()
		post.assert_not_called()
		_take, _post, log_error = self.submit(_settings(), MagicMock(status_code=403, text="key not valid"))
		self.assertEqual(log_error.call_args.args[0], "IndexNow: notification refused")


class TestKeyFile(FrappeTestCase):
	def test_the_key_at_the_root_only_while_switched_on(self):
		with patch("frappe.get_cached_doc", return_value=_settings()):
			renderer = indexnow.KeyRenderer(path=f"/{KEY}.txt")
			self.assertTrue(renderer.can_render())
			response = renderer.render()
			self.assertEqual(
				(response.status_code, response.mimetype, response.get_data(as_text=True)), (200, "text/plain", KEY)
			)
			self.assertFalse(indexnow.KeyRenderer(path="/robots.txt").can_render())
		with patch("frappe.get_cached_doc", return_value=_settings(enabled=0)):
			self.assertFalse(indexnow.KeyRenderer(path=f"/{KEY}.txt").can_render())
