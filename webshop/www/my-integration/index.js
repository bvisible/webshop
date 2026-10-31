// //// Neoffice — added file (the reseller's integration page, no upstream equivalent).
// Asks for the partner API, shows where the request stands and makes the key. Nothing the server sends goes
// through innerHTML: it is written with textContent or as a property of an element. The secret of a key is
// shown once, from the answer that made it, and is not kept in the page after a reload.
(function () {
	"use strict";

	const configNode = document.getElementById("wsp-integration-config");
	if (!configNode) return;
	const L = JSON.parse(configNode.textContent).labels;
	const API = "webshop.webshop.partner_api.portal_api.";
	const $ = (id) => document.getElementById(id);
	const fmt = (text, ...args) => String(text || "").replace(/\{(\d+)\}/g, (m, i) => (args[i] == null ? "" : args[i]));

	function call(method, args, type) {
		return new Promise((resolve, reject) => {
			frappe.call({ method: API + method, type: type || "POST", args: args || {}, callback: (r) => resolve(r.message), error: (e) => reject(e) });
		});
	}

	function el(tag, text, className) {
		const node = document.createElement(tag);
		if (text != null) node.textContent = text;
		if (className) node.className = className;
		return node;
	}

	function showError(message) {
		$("wsp-int-error").textContent = message || "";
		$("wsp-int-error").classList.toggle("d-none", !message);
	}

	function clearFormErrors() {
		document.querySelectorAll("#wsp-int-form [data-error-for]").forEach((node) => (node.textContent = ""));
		$("wsp-int-form-status").textContent = "";
	}

	function action(text, className, handler) {
		const button = el("button", text, className);
		button.type = "button";
		button.addEventListener("click", handler);
		return button;
	}

	function apply(state, secret) {
		showError("");
		const access = state.access;
		const status = $("wsp-int-status");
		status.textContent = access ? L["status_" + access.status] || access.status : "—";
		$("wsp-int-when").textContent = access && access.requested_on ? fmt(L.asked_on, access.requested_on.slice(0, 10)) : "";
		const note = $("wsp-int-note");
		note.textContent = access && access.decision_note ? L.note + " : " + access.decision_note : "";

		const canAsk = !access || access.status === "Refused";
		$("wsp-int-form").classList.toggle("d-none", !canAsk);
		if (access && access.status === "Refused") $("wsp-int-note").textContent = (note.textContent ? note.textContent + " " : "") + L.refused_again;

		const active = access && access.status === "Active";
		$("wsp-int-active").classList.toggle("d-none", !active);
		if (!active) return;

		const scopes = $("wsp-int-scopes");
		scopes.textContent = "";
		if (access.scope_products) scopes.appendChild(el("li", L.scope_products));
		if (access.scope_orders) scopes.appendChild(el("li", L.scope_orders + " — " + (access.submit_orders ? L.submit_orders : L.drafts)));
		scopes.appendChild(el("li", fmt(L.allowance, access.calls_per_minute)));

		$("wsp-int-key-info").textContent = access.key_id ? fmt(L.key_info, access.key_id, (access.key_created_on || "").slice(0, 16)) : L.no_key;
		$("wsp-int-key-used").textContent = access.key_id ? (access.last_used_on ? fmt(L.key_used, access.last_used_on.slice(0, 16)) : L.key_never_used) : "";

		const box = $("wsp-int-secret-box");
		box.classList.toggle("d-none", !secret);
		$("wsp-int-secret").value = secret || "";

		const actions = $("wsp-int-key-actions");
		actions.textContent = "";
		const hasKey = !!access.key_id;
		actions.appendChild(
			action(hasKey ? L.replace_key : L.make_key, "btn btn-sm btn-primary mr-2 mb-1", () => {
				if (hasKey && !window.confirm(L.replace_confirm)) return;
				call("new_key").then((answer) => (answer.ok ? apply(answer, answer.key) : showError(answer.message))).catch(() => showError(L.failed));
			})
		);
		if (hasKey) {
			actions.appendChild(
				action(L.revoke_key, "btn btn-sm btn-light mb-1", () => {
					if (!window.confirm(L.revoke_confirm)) return;
					call("revoke_key").then((answer) => apply(answer)).catch(() => showError(L.failed));
				})
			);
		}

		$("wsp-int-base").textContent = state.base_url;
		$("wsp-int-contract").href = state.contract_url;
		$("wsp-int-example").textContent = 'curl -H "X-API-Key: ' + (secret || "wsk_…") + '" ' + state.base_url + "/products?page_size=10";
	}

	$("wsp-int-copy").addEventListener("click", () => {
		const input = $("wsp-int-secret");
		input.select();
		const done = () => {
			$("wsp-int-copy").textContent = L.copied;
			setTimeout(() => ($("wsp-int-copy").textContent = L.copy), 1500);
		};
		if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(input.value).then(done, () => document.execCommand("copy") && done());
		else if (document.execCommand("copy")) done();
	});

	$("wsp-int-form").addEventListener("submit", (event) => {
		event.preventDefault();
		clearFormErrors();
		$("wsp-int-send").disabled = true;
		call("request_access", {
			use_case: $("wsp-int-use-case").value,
			expected_volume: $("wsp-int-volume").value,
			wants_orders: $("wsp-int-orders").checked ? 1 : 0,
		})
			.then((answer) => {
				$("wsp-int-send").disabled = false;
				if (answer.ok) return apply(answer);
				const node = answer.field && document.querySelector('#wsp-int-form [data-error-for="' + answer.field + '"]');
				if (node) node.textContent = answer.message;
				else $("wsp-int-form-status").textContent = answer.message;
			})
			.catch(() => {
				$("wsp-int-send").disabled = false;
				$("wsp-int-form-status").textContent = L.failed;
			});
	});

	call("get_integration", {}, "GET").then((state) => apply(state)).catch(() => showError(L.failed));
})();
