# //// Neoffice — added file (no upstream equivalent).
"""The throttle counts the connection's peer, never the address a caller wrote.

Frappe's own `rate_limit` keys on `frappe.local.request_ip`, the FIRST entry of `X-Forwarded-For`. Where nginx
appends (`$proxy_add_x_forwarded_for`) that entry is whatever the caller sent, so a caller who changes the header on
every request is never counted twice (measured on a shop vhost: 25 requests out of 25 went through a limit of 20).
The throttle reads the LAST entry, which is nginx's own under both ways of writing the header.

The request and its header are faked; the counters are the real Redis ones, under names that belong to these tests.
"""

import types

import frappe
from frappe.tests.utils import FrappeTestCase

from webshop.webshop.utils import throttle


class TestThrottle(FrappeTestCase):
	def setUp(self):
		self.real_header = frappe.get_request_header
		self.real_request = getattr(frappe.local, "request", None)
		self.real_ip = getattr(frappe.local, "request_ip", None)
		self.name = "_wstest-" + frappe.generate_hash(length=8)
		self.identities = set()

	def tearDown(self):
		frappe.get_request_header = self.real_header
		frappe.local.request = self.real_request
		frappe.local.request_ip = self.real_ip
		for identity in self.identities:
			throttle.reset(self.name, identity)

	def behind_nginx(self, forwarded):
		"""A request that reached Frappe with this `X-Forwarded-For` (None: the header is absent)."""
		frappe.local.request = types.SimpleNamespace(method="POST")
		frappe.get_request_header = lambda key, default=None: forwarded if key == "X-Forwarded-For" else default

	# --- which address is counted ------------------------------------------------------------------

	def test_the_peer_is_the_last_forwarded_address(self):
		self.behind_nginx("10.0.0.7")
		self.assertEqual(throttle.peer_ip(), "10.0.0.7")
		self.behind_nginx("9.9.9.9, 10.0.0.7")
		self.assertEqual(throttle.peer_ip(), "10.0.0.7")
		self.behind_nginx(" 9.9.9.9 ,8.8.8.8,  10.0.0.7 ")
		self.assertEqual(throttle.peer_ip(), "10.0.0.7")

	def test_without_the_header_frappe_s_own_address_stands(self):
		self.behind_nginx(None)
		frappe.local.request_ip = "192.0.2.44"
		self.assertEqual(throttle.peer_ip(), "192.0.2.44")

	# --- the budget --------------------------------------------------------------------------------

	def test_a_caller_who_rewrites_the_header_keeps_the_same_budget(self):
		@throttle.throttle(self.name, 3, 30)
		def endpoint():
			return "ok"

		self.identities.add("10.0.0.7")
		answers = []
		for number in range(5):
			# nginx appended the peer to whatever the caller wrote: the caller writes a new address each time
			self.behind_nginx(f"203.0.113.{number}, 10.0.0.7")
			try:
				answers.append(endpoint())
			except frappe.RateLimitExceededError:
				answers.append("429")
		self.assertEqual(answers, ["ok", "ok", "ok", "429", "429"])

	def test_two_peers_have_two_budgets(self):
		@throttle.throttle(self.name, 1, 30)
		def endpoint():
			return "ok"

		self.identities.update({"10.0.0.7", "10.0.0.8"})
		self.behind_nginx("10.0.0.7")
		self.assertEqual(endpoint(), "ok")
		self.behind_nginx("10.0.0.8")
		self.assertEqual(endpoint(), "ok")
		self.behind_nginx("10.0.0.7")
		with self.assertRaises(frappe.RateLimitExceededError):
			endpoint()

	def test_the_refusal_is_a_429(self):
		@throttle.throttle(self.name, 0, 30)
		def endpoint():
			return "ok"

		self.identities.add("10.0.0.7")
		self.behind_nginx("10.0.0.7")
		with self.assertRaises(frappe.RateLimitExceededError) as caught:
			endpoint()
		self.assertEqual(caught.exception.http_status_code, 429)

	def test_a_call_that_is_not_a_request_is_not_counted(self):
		"""Tests and background jobs call the functions directly."""

		@throttle.throttle(self.name, 1, 30)
		def endpoint():
			return "ok"

		frappe.local.request = None
		self.assertEqual([endpoint() for _count in range(5)], ["ok"] * 5)

	def test_every_window_ends_so_a_crash_cannot_block_an_address_for_good(self):
		self.identities.add("10.0.0.9")
		throttle.hit(self.name, "10.0.0.9", 30)
		cache = frappe.cache()
		ttl = cache.ttl(cache.make_key(f"webshop_throttle:{self.name}:10.0.0.9"))
		self.assertTrue(0 < ttl <= 30, ttl)

	def test_hit_counts_and_reset_forgets(self):
		self.identities.add("10.0.0.9")
		self.assertEqual([throttle.hit(self.name, "10.0.0.9", 30) for _count in range(3)], [1, 2, 3])
		throttle.reset(self.name, "10.0.0.9")
		self.assertEqual(throttle.hit(self.name, "10.0.0.9", 30), 1)
