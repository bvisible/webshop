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


def glyph():
	"""The SVG the bubble draws on its button and in its header, as assistant.js builds it."""
	node = shutil.which("node")
	if not node:
		raise AssertionError("Node is needed to run assistant.js: install it, this test does not skip")
	script = RUNNER.replace(
		"const drawn = JSON.parse(process.argv[2]).map((text) => sandbox.webshop.assistant.markdown(text));",
		"const drawn = [sandbox.webshop.assistant.icon()];",
	)
	run = subprocess.run([node, "-e", script, str(ASSISTANT_JS), "[]"], capture_output=True, text=True, timeout=60)
	if run.returncode:
		raise AssertionError(run.stderr)
	return json.loads(run.stdout)[0]


START_RUNNER = r"""
const vm = require("vm");
const fs = require("fs");
const wanted = JSON.parse(process.argv[2]);
const calls = [];
const listeners = {};
const timers = [];
let ready = null;
const sandbox = {
	frappe: { provide() {}, ready(callback) { ready = callback; }, csrf_token: "tok" },
	webshop: {},
	document: { getElementById: () => null },
	window: {
		addEventListener(name, callback) { (listeners[name] = listeners[name] || []).push(callback); },
		removeEventListener(name, callback) { listeners[name] = (listeners[name] || []).filter((c) => c !== callback); },
	},
	sessionStorage: { getItem: (key) => (wanted.stored && key === "wsh-assistant-open" ? "1" : null) },
	setTimeout: (callback, ms) => { timers.push({ callback, ms, cleared: false }); return timers.length - 1; },
	clearTimeout: (id) => { if (timers[id]) timers[id].cleared = true; },
	URL,
	URLSearchParams,
	location: { origin: "https://shop.example", host: "shop.example", pathname: "/" },
	fetch: async (url) => {
		calls.push(url);
		return { ok: true, status: 200, json: async () => ({ message: { enabled: false } }) };
	},
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), sandbox);
const fire = (name) => (listeners[name] || []).slice().forEach((callback) => callback({}));
const asked = () => calls.filter((url) => url.includes("get_config")).length;
(async () => {
	ready();
	const seen = { at_load: asked() };
	for (const step of wanted.steps) {
		if (step === "timer") timers.filter((t) => !t.cleared).forEach((t) => t.callback());
		else fire(step);
		await new Promise((resolve) => setImmediate(resolve));
		seen[step] = asked();
	}
	seen.fallback_ms = timers.map((t) => t.ms);
	seen.listening = Object.keys(listeners).filter((name) => listeners[name].length);
	console.log(JSON.stringify(seen));
})();
"""


def start_page(steps, stored=False):
	"""How many times the page asked the server for the bubble, after each step a visitor (or the clock) took."""
	node = shutil.which("node")
	if not node:
		raise AssertionError("Node is needed to run assistant.js: install it, this test does not skip")
	run = subprocess.run(
		[node, "-e", START_RUNNER, str(ASSISTANT_JS), json.dumps({"steps": steps, "stored": stored})],
		capture_output=True,
		text=True,
		timeout=60,
	)
	if run.returncode:
		raise AssertionError(run.stderr)
	return json.loads(run.stdout)


class TestAssistantStart(FrappeTestCase):
	"""Every page view used to ask the server for the bubble, whether anybody was there or not (lot C of the 2026-10-30 audit).

	A crawler that renders the page, a monitoring probe, a bot reading a thousand product pages: each one cost a
	`get_config`, which looks up a conversation. The bubble now asks once the visitor shows up.
	"""

	def test_a_page_nobody_touches_does_not_ask_the_server_for_the_bubble_at_once(self):
		seen = start_page([])
		self.assertEqual(seen["at_load"], 0)
		# it waits for a sign of the visitor, and for the clock
		self.assertIn("pointermove", seen["listening"])
		self.assertTrue(seen["fallback_ms"])

	def test_the_first_sign_of_a_visitor_asks_once_whatever_comes_after(self):
		seen = start_page(["pointermove", "scroll", "keydown", "timer"])
		self.assertEqual(seen["at_load"], 0)
		self.assertEqual((seen["pointermove"], seen["scroll"], seen["keydown"], seen["timer"]), (1, 1, 1, 1))

	def test_each_kind_of_visitor_is_heard(self):
		for sign in ("pointerdown", "pointermove", "keydown", "scroll", "touchstart", "wheel"):
			with self.subTest(sign=sign):
				seen = start_page([sign])
				self.assertEqual((seen["at_load"], seen[sign]), (0, 1))

	def test_a_visitor_who_only_reads_gets_the_bubble_after_a_quiet_while(self):
		seen = start_page(["timer", "pointermove"])
		self.assertEqual(seen["at_load"], 0)
		self.assertEqual(seen["timer"], 1)
		self.assertTrue(seen["fallback_ms"])
		self.assertEqual(seen["pointermove"], 1)
		self.assertTrue(all(2000 <= ms <= 15000 for ms in seen["fallback_ms"]), seen["fallback_ms"])

	def test_the_page_stops_listening_once_it_has_asked(self):
		self.assertEqual(start_page(["pointermove"])["listening"], [])

	def test_a_visitor_who_had_the_bubble_open_on_the_last_page_finds_it_at_once(self):
		self.assertEqual(start_page([], stored=True)["at_load"], 1)


class TestAssistantGlyph(FrappeTestCase):
	"""The glyph belongs to every shop: it takes its colours from the theme and its size from the stylesheet."""

	def test_the_glyph_is_one_svg_that_takes_the_theme_s_colours(self):
		svg = glyph()
		self.assertTrue(svg.startswith("<svg") and svg.rstrip().endswith("</svg>"))
		self.assertEqual(svg.count("<svg"), 1)
		self.assertIn("currentColor", svg)  # the ink of the button, whatever the shop's colour
		self.assertIn("var(--wsh-assistant-color)", svg)  # the smile is cut out in the button's own colour
		self.assertNotRegex(svg, r"#[0-9a-fA-F]{3,8}\b")  # no colour of ours

	def test_the_size_comes_from_the_stylesheet_not_from_the_glyph(self):
		"""The same glyph is 30px on the button and 22px in the header."""
		opening_tag = glyph().split(">", 1)[0]
		self.assertNotRegex(opening_tag, r"\s(width|height)=")  # `stroke-width` on a path is not the size


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
