# //// Neoffice — added file (no upstream equivalent).
"""What the assistant's bubble turns into a link (lot A of the 2026-10-30 security audit).

The bubble escapes everything, so the markup it draws cannot carry a script. What it could still do is send the
customer away: a model that was asked to, or that read an instruction in a product page, writes `[Voir](//host/x)` and
the bubble drew a link to that host. Only the shop's own addresses are links now; anything else stays text.

The real `assistant.js` is run by Node in a bare sandbox (no browser): this test FAILS, it does not skip, when Node is
missing, because a skipped test reads exactly like a passing one.
"""

import json
import shutil
import subprocess
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

ASSISTANT_JS = Path(frappe.get_app_path("webshop", "public", "js", "assistant.js"))

RUNNER = r"""
const vm = require("vm");
const fs = require("fs");
const sandbox = {
	frappe: { provide() {}, ready() {} },
	webshop: {},
	document: {},
	sessionStorage: {},
	URL,
	location: { origin: "https://shop.example", host: "shop.example" },
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), sandbox);
const drawn = JSON.parse(process.argv[2]).map((text) => sandbox.webshop.assistant.markdown(text));
console.log(JSON.stringify(drawn));
"""


def draw(*texts):
	node = shutil.which("node")
	if not node:
		raise AssertionError("Node is needed to run assistant.js: install it, this test does not skip")
	run = subprocess.run(
		[node, "-e", RUNNER, str(ASSISTANT_JS), json.dumps(list(texts))], capture_output=True, text=True, timeout=60
	)
	if run.returncode:
		raise AssertionError(run.stderr)
	return json.loads(run.stdout)


API_RUNNER = r"""
const vm = require("vm");
const fs = require("fs");
const wanted = JSON.parse(process.argv[2]);
const calls = [];
const sandbox = {
	frappe: { provide() {}, ready() {}, csrf_token: "tok123" },
	webshop: {},
	document: {},
	sessionStorage: {},
	URL,
	URLSearchParams,
	location: { origin: "https://shop.example", host: "shop.example" },
	fetch: async (url, options) => {
		options = options || {};
		calls.push({ url, method: options.method || "GET", headers: options.headers || {}, body: options.body ? String(options.body) : null });
		return {
			ok: wanted.status < 400,
			status: wanted.status,
			json: async () => {
				if (wanted.body === null) throw new SyntaxError("not json");
				return wanted.body;
			},
		};
	},
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), sandbox);
sandbox.webshop.assistant
	.api("webshop.x.y", wanted.args, wanted.verb)
	.then(
		(message) => console.log(JSON.stringify({ resolved: message, calls })),
		(error) => console.log(JSON.stringify({ rejected: { status: error.status, json: error.responseJSON }, calls }))
	);
"""


def call_api(status, body, verb="POST", args=None):
	"""What the bubble's own request does when the server answers `status` with `body` (None: not JSON)."""
	node = shutil.which("node")
	if not node:
		raise AssertionError("Node is needed to run assistant.js: install it, this test does not skip")
	run = subprocess.run(
		[node, "-e", API_RUNNER, str(ASSISTANT_JS), json.dumps({"status": status, "body": body, "verb": verb, "args": args or {}})],
		capture_output=True,
		text=True,
		timeout=60,
	)
	if run.returncode:
		raise AssertionError(run.stderr)
	return json.loads(run.stdout)


class TestAssistantRequests(FrappeTestCase):
	"""The bubble talks to the server with its own fetch.

	`frappe.call` never ends its promise on a 429 (its error callback is not called: measured on a shop page, only
	`always` fires), so a visitor who met a limit saw "typing…" for ever, under a Frappe dialog in the middle of the page.
	"""

	def test_a_refusal_ends_the_request_with_its_status(self):
		out = call_api(429, {"exc_type": "RateLimitExceededError"})
		self.assertEqual(out["rejected"]["status"], 429)
		self.assertEqual(out["rejected"]["json"]["exc_type"], "RateLimitExceededError")

	def test_a_server_error_that_is_not_json_still_ends_the_request(self):
		out = call_api(502, None)
		self.assertEqual(out["rejected"]["status"], 502)

	def test_an_answer_resolves_with_the_message(self):
		out = call_api(200, {"message": {"reply": "Bonjour"}})
		self.assertEqual(out["resolved"], {"reply": "Bonjour"})

	def test_a_post_carries_the_csrf_token_and_the_form(self):
		out = call_api(200, {"message": {}}, "POST", {"message": "é & ?", "page_route": "a", "email": None})
		(call,) = out["calls"]
		self.assertEqual(call["url"], "/api/method/webshop.x.y")
		self.assertEqual(call["method"], "POST")
		self.assertEqual(call["headers"]["X-Frappe-CSRF-Token"], "tok123")
		self.assertEqual(call["body"], "message=%C3%A9+%26+%3F&page_route=a")

	def test_a_get_puts_its_arguments_in_the_address(self):
		out = call_api(200, {"message": {}}, "GET", {"page_route": "all-products"})
		(call,) = out["calls"]
		self.assertEqual(call["url"], "/api/method/webshop.x.y?page_route=all-products")
		self.assertEqual(call["method"], "GET")
		self.assertIsNone(call["body"])


class TestAssistantLinks(FrappeTestCase):
	def test_a_path_of_the_shop_is_a_link(self):
		(html,) = draw("[Voir](/orders/BC-1)")
		self.assertIn('<a href="/orders/BC-1">Voir</a>', html)

	def test_a_bare_path_is_a_link(self):
		(html,) = draw("Votre commande : /orders/BC-1")
		self.assertIn('<a href="/orders/BC-1">/orders/BC-1</a>', html)

	def test_an_absolute_address_on_the_shop_s_own_origin_is_a_link(self):
		(html,) = draw("[Voir](https://shop.example/orders/BC-1)")
		self.assertIn('<a href="https://shop.example/orders/BC-1">Voir</a>', html)

	def test_a_protocol_relative_address_is_not_a_link(self):
		(html,) = draw("[Voir](//evil.example/phish)")
		self.assertNotIn("<a ", html)
		self.assertIn("//evil.example/phish", html)  # still readable, as text

	def test_another_site_is_not_a_link(self):
		for text in ("[Voir](https://evil.example/phish)", "Offre : https://evil.example/phish", "[Voir](http://shop.example.evil.example/x)"):
			with self.subTest(text):
				(html,) = draw(text)
				self.assertNotIn("<a ", html)

	def test_a_backslash_cannot_turn_a_path_into_another_host(self):
		(html,) = draw("[Voir](/\\evil.example)")
		self.assertNotIn("<a ", html)

	def test_a_script_address_is_never_a_link_and_markup_stays_escaped(self):
		(html,) = draw("[x](javascript:alert(1)) <img src=x onerror=alert(1)>")
		self.assertNotIn("<a ", html)
		self.assertNotIn("<img", html)
		self.assertIn("&lt;img", html)

	def test_a_quote_cannot_leave_the_attribute(self):
		(html,) = draw('[a](/orders/BC-1" onmouseover="alert(1))')
		self.assertNotIn(' onmouseover="', html)
