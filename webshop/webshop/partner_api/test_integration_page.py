# //// Neoffice — added file (no upstream equivalent).
"""The reseller's integration page keeps answering when the server is busy (reseller catalogue, lot 4).

The page first asked the server through `frappe.call`, whose promise never ends on a 429 or a 502 (the error
callback is not called): the "Make a key" button then stayed mute, no message, nothing to tell the reseller
whether a key had been made. It asks with its own `fetch` now, and a request always ends.

The real `index.js` is run by Node in a bare sandbox, with a `frappe.call` that never answers (as on a 429): the
test FAILS, it does not skip, when Node is missing, because a skipped test reads exactly like a passing one.
"""

import json
import shutil
import subprocess
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

PAGE_JS = Path(frappe.get_app_path("webshop", "www", "my-integration", "index.js"))

LABELS = [
	"failed",
	"asked_on",
	"note",
	"refused_again",
	"scope_products",
	"scope_orders",
	"submit_orders",
	"drafts",
	"allowance",
	"key_info",
	"no_key",
	"key_used",
	"key_never_used",
	"make_key",
	"replace_key",
	"replace_confirm",
	"revoke_key",
	"revoke_confirm",
	"copy",
	"copied",
	"status_Active",
]

RUNNER = r"""
const vm = require("vm");
const fs = require("fs");
const wanted = JSON.parse(process.argv[2]);
const calls = [];

function node(id) {
	const handlers = {};
	const element = {
		id,
		textContent: "",
		value: "",
		checked: false,
		disabled: false,
		href: "",
		children: [],
		handlers,
		classes: new Set(),
		classList: {
			toggle(name, on) { on ? element.classes.add(name) : element.classes.delete(name); },
			add(name) { element.classes.add(name); },
			remove(name) { element.classes.delete(name); },
		},
		addEventListener(type, callback) { handlers[type] = callback; },
		appendChild(child) { element.children.push(child); return child; },
		select() {},
	};
	// writing "" to textContent empties a list the page fills, as a browser does
	return new Proxy(element, {
		set(target, key, value) {
			target[key] = value;
			if (key === "textContent" && value === "") target.children = [];
			return true;
		},
	});
}

const nodes = {};
const labels = {};
wanted.labels.forEach((key) => (labels[key] = "L:" + key));
labels.failed = "FAILED";
const sandbox = {
	// as on a 429: frappe.call never calls anything back
	frappe: { call() {}, csrf_token: "tok123" },
	document: {
		getElementById(id) {
			if (!nodes[id]) nodes[id] = node(id);
			if (id === "wsp-integration-config") nodes[id].textContent = JSON.stringify({ labels });
			return nodes[id];
		},
		createElement: (tag) => node(tag),
		querySelectorAll: () => [],
		querySelector: () => null,
	},
	window: { confirm: () => true },
	navigator: {},
	setTimeout,
	URLSearchParams,
	fetch: async (url, options) => {
		options = options || {};
		calls.push({ url, method: options.method || "GET", headers: options.headers || {}, body: options.body ? String(options.body) : null });
		const answer = wanted.answers[calls.length - 1] || wanted.answers[wanted.answers.length - 1];
		return {
			ok: answer.status < 400,
			status: answer.status,
			json: async () => {
				if (answer.body === null) throw new SyntaxError("not json");
				return answer.body;
			},
		};
	},
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), sandbox);

const settle = () => new Promise((resolve) => setTimeout(resolve, 30));
const get = (id) => sandbox.document.getElementById(id);
(async () => {
	await settle();
	const out = { calls: calls.slice(), error: get("wsp-int-error").textContent, errorHidden: get("wsp-int-error").classes.has("d-none") };
	if (wanted.press !== null && wanted.press !== undefined) {
		const buttons = get("wsp-int-key-actions").children;
		out.buttons = buttons.map((b) => b.textContent);
		const pressed = calls.length;
		if (buttons[wanted.press]) buttons[wanted.press].handlers.click();
		await settle();
		out.pressed = calls.slice(pressed);
		out.errorAfter = get("wsp-int-error").textContent;
		out.secret = get("wsp-int-secret").value;
	}
	console.log(JSON.stringify(out));
})();
"""

ACTIVE = {
	"message": {
		"access": {"status": "Active", "scope_products": 1, "scope_orders": 1, "calls_per_minute": 60, "key_id": "wsk_0123456789ab"},
		"base_url": "https://shop.example/partner/v1",
		"contract_url": "https://shop.example/partner/v1/openapi.yaml",
	}
}


def run_page(answers, press=None):
	node = shutil.which("node")
	if not node:
		raise AssertionError("Node is needed to run the page's script: install it, this test does not skip")
	run = subprocess.run(
		[node, "-e", RUNNER, str(PAGE_JS), json.dumps({"labels": LABELS, "answers": answers, "press": press})],
		capture_output=True,
		text=True,
		timeout=60,
	)
	if run.returncode:
		raise AssertionError(run.stderr)
	return json.loads(run.stdout)


class TestIntegrationPage(FrappeTestCase):
	def test_the_page_reads_its_state_with_its_own_get_and_a_busy_server_is_told(self):
		seen = run_page([{"status": 200, "body": ACTIVE}])
		call = seen["calls"][0]
		self.assertEqual(call["method"], "GET")
		self.assertTrue(call["url"].startswith("/api/method/webshop.webshop.partner_api.portal_api.get_integration"))
		self.assertEqual(seen["error"], "")

		for status, body in ((502, None), (429, {"exc_type": "TooManyRequestsError"}), (500, {"exc": "x"})):
			with self.subTest(status=status):
				busy = run_page([{"status": status, "body": body}])
				self.assertEqual(busy["error"], "FAILED", "a state that could not be read is said, not left blank")
				self.assertFalse(busy["errorHidden"])

	def test_a_key_pressed_during_a_busy_moment_ends_with_a_message(self):
		"""Before, frappe.call never answered on these statuses: the button did nothing and said nothing."""
		for status, body in ((502, None), (429, {"exc_type": "TooManyRequestsError"})):
			with self.subTest(status=status):
				seen = run_page([{"status": 200, "body": ACTIVE}, {"status": status, "body": body}], press=0)
				self.assertEqual(seen["errorAfter"], "FAILED")
				self.assertEqual(seen["secret"], "", "no key is shown when none was made")

	def test_a_key_is_asked_with_a_post_that_carries_the_csrf_token_and_its_secret_is_shown(self):
		secret = "wsk_0123456789ab." + "s" * 40
		made = {"message": {**ACTIVE["message"], "ok": True, "key": secret}}
		seen = run_page([{"status": 200, "body": ACTIVE}, {"status": 200, "body": made}], press=0)
		self.assertEqual(seen["buttons"], ["L:replace_key", "L:revoke_key"])
		(post,) = seen["pressed"]
		self.assertEqual(post["method"], "POST")
		self.assertTrue(post["url"].endswith("portal_api.new_key"))
		self.assertEqual(post["headers"]["X-Frappe-CSRF-Token"], "tok123")
		self.assertEqual(seen["secret"], secret)
		self.assertEqual(seen["errorAfter"], "")

	def test_a_refusal_the_server_words_is_shown_as_it_is(self):
		refused = {"message": {**ACTIVE["message"], "ok": False, "message": "The key was made a moment ago."}}
		seen = run_page([{"status": 200, "body": ACTIVE}, {"status": 200, "body": refused}], press=0)
		self.assertEqual(seen["errorAfter"], "The key was made a moment ago.")
		self.assertEqual(seen["secret"], "")
