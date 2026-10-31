// //// Neoffice — added file (the reseller's brand page, no upstream equivalent).
// Fills the form from the server, saves it, sends the logo and shows what a markup does to the prices.
// Nothing the reseller typed ever goes through innerHTML: it is written with textContent or as a
// property of an element. Every price shown comes from the server; the page never computes one.
(function () {
	"use strict";

	const configNode = document.getElementById("wsp-brand-config");
	if (!configNode) return;
	const L = JSON.parse(configNode.textContent).labels;
	const API = "webshop.webshop.catalogue.api.";
	const CATALOGUE_API = "webshop.webshop.catalogue.catalogue_api.";
	const KINDS = ["Item Group", "Brand", "Item"];
	const MAX_LOGO_BYTES = 2 * 1024 * 1024;
	const FIELDS = [
		"brand_name",
		"primary_colour",
		"secondary_colour",
		"contact_email",
		"contact_phone",
		"contact_website",
		"contact_address",
		"vat_number",
		"footer_text",
		"default_markup_percent",
		"price_rounding",
		"price_display",
		"vat_rate",
	];
	// what the price table and the colour sample depend on
	const PREVIEW_FIELDS = [
		["default_markup_percent", "markup_percent"],
		["price_rounding", "price_rounding"],
		["price_display", "price_display"],
		["vat_rate", "vat_rate"],
		["primary_colour", "primary_colour"],
		["secondary_colour", "secondary_colour"],
	];

	const $ = (id) => document.getElementById(id);
	const form = $("wsp-brand-form");
	let previewTimer = null;
	let previewSeq = 0;
	let lastInk = { primary: "#ffffff", secondary: "#ffffff" };
	// the markups of their own, as they stand in the form until the form is saved
	let rules = [];
	let chosenItem = null;
	let searchTimer = null;
	let searchSeq = 0;

	const fmt = (text, ...args) => String(text || "").replace(/\{(\d+)\}/g, (m, i) => (args[i] == null ? "" : args[i]));

	// frappe.call never ends its promise on a 429 or a 502 (its error callback is not called): a button pressed
	// during a busy moment stayed mute. A request here always ends, with the message or with an error.
	async function call(method, args, type, api) {
		const verb = type || "POST";
		const params = new URLSearchParams();
		Object.entries(args || {}).forEach(([key, value]) => {
			if (value !== undefined && value !== null) params.append(key, value);
		});
		const headers = { Accept: "application/json" };
		if (frappe.csrf_token) headers["X-Frappe-CSRF-Token"] = frappe.csrf_token;
		const url = "/api/method/" + (api || API) + method;
		const response =
			verb === "GET"
				? await fetch(url + "?" + params, { headers, credentials: "same-origin" })
				: await fetch(url, {
						method: verb,
						headers: { ...headers, "Content-Type": "application/x-www-form-urlencoded" },
						body: params,
						credentials: "same-origin",
				  });
		const data = await response.json().catch(() => ({}));
		if (!response.ok) {
			const error = new Error("HTTP " + response.status);
			error.status = response.status;
			error.responseJSON = data;
			throw error;
		}
		return data.message;
	}

	function setStatus(text) {
		$("wsp-brand-status").textContent = text || "";
	}

	function clearErrors() {
		form.querySelectorAll("[data-error-for]").forEach((node) => (node.textContent = ""));
	}

	function showError(field, message) {
		const node = field && form.querySelector('[data-error-for="' + field + '"]');
		if (node) node.textContent = message;
		else setStatus(message);
	}

	function option(value, text) {
		const node = document.createElement("option");
		node.value = value;
		node.textContent = text;
		return node;
	}

	function fillSelect(select, choices) {
		select.textContent = "";
		choices.forEach(([value, text]) => select.appendChild(option(value, text)));
	}

	function renderSample() {
		[
			["primary", "primary_colour"],
			["secondary", "secondary_colour"],
		].forEach(([key, field]) => {
			const node = $("wsp-sample-" + key);
			node.textContent = form.elements.brand_name.value || "";
			node.style.background = form.elements[field].value;
			node.style.color = lastInk[key];
		});
	}

	function renderLogo(dataUrl) {
		const box = $("wsp-logo-preview");
		box.textContent = "";
		if (dataUrl) {
			const image = document.createElement("img");
			image.src = dataUrl;
			image.alt = form.elements.brand_name.value || "";
			image.style.maxHeight = "64px";
			image.style.maxWidth = "100%";
			box.appendChild(image);
		} else {
			box.textContent = L.logo_none;
		}
		$("wsp-logo-remove").classList.toggle("d-none", !dataUrl);
	}

	function renderCredit(line) {
		const node = $("wsp-brand-credit");
		node.textContent = line ? fmt(L.credit, line) : "";
		node.classList.toggle("d-none", !line);
	}

	function toggleVat() {
		$("wsp-vat-group").classList.toggle("d-none", form.elements.price_display.value !== "Including VAT");
	}

	function kindLabel(kind) {
		return kind === "Item Group" ? L.rule_group : kind === "Brand" ? L.rule_brand : L.rule_item;
	}

	function renderRules() {
		const body = $("wsp-rule-rows");
		body.textContent = "";
		if (!rules.length) {
			const row = body.insertRow();
			const cell = row.insertCell();
			cell.colSpan = 4;
			cell.className = "text-muted";
			cell.textContent = L.rule_none;
			return;
		}
		rules.forEach((rule, index) => {
			const row = body.insertRow();
			row.insertCell().textContent = kindLabel(rule.rule_type);
			row.insertCell().textContent = rule.label || rule.target;
			const percent = row.insertCell();
			percent.className = "text-right";
			percent.textContent = String(rule.markup_percent) + " %";
			const remove = document.createElement("button");
			remove.type = "button";
			remove.className = "btn btn-sm btn-light";
			remove.textContent = L.rule_remove;
			remove.addEventListener("click", () => {
				rules.splice(index, 1);
				renderRules();
			});
			row.insertCell().appendChild(remove);
		});
	}

	function showKind() {
		const kind = $("wsp-rule-kind").value;
		$("wsp-rule-group").classList.toggle("d-none", kind !== "Item Group");
		$("wsp-rule-brand").classList.toggle("d-none", kind !== "Brand");
		$("wsp-rule-item").classList.toggle("d-none", kind !== "Item");
	}

	function fillRuleChoices(choices) {
		const groups = $("wsp-rule-group");
		groups.textContent = "";
		groups.appendChild(option("", L.rule_pick_group));
		choices.groups.forEach((group) => groups.appendChild(option(group.name, "\u00a0\u00a0".repeat(group.depth) + group.name + " (" + group.count + ")")));
		const brands = $("wsp-rule-brand");
		brands.textContent = "";
		brands.appendChild(option("", L.rule_pick_brand));
		choices.brands.forEach((brand) => brands.appendChild(option(brand.name, brand.name + " (" + brand.count + ")")));
	}

	function chooseItem(item) {
		chosenItem = item;
		$("wsp-rule-chosen").textContent = item ? fmt(L.rule_selected, item.name + " (" + item.item_code + ")") : "";
		$("wsp-rule-results").textContent = "";
	}

	function searchItems() {
		clearTimeout(searchTimer);
		const text = $("wsp-rule-search").value.trim();
		const box = $("wsp-rule-results");
		if (text.length < 2) {
			box.textContent = "";
			return;
		}
		searchTimer = setTimeout(() => {
			const seq = ++searchSeq;
			call("search_products", { text }, "GET", CATALOGUE_API)
				.then((answer) => {
					if (seq !== searchSeq) return;
					box.textContent = "";
					((answer && answer.products) || []).forEach((item) => {
						const button = document.createElement("button");
						button.type = "button";
						button.className = "list-group-item list-group-item-action py-1";
						button.textContent = item.name + " (" + item.item_code + ")";
						button.addEventListener("click", () => chooseItem(item));
						box.appendChild(button);
					});
				})
				.catch(() => setStatus(L.failed));
		}, 300);
	}

	function addRule() {
		showError("markup_rules", "");
		const kind = $("wsp-rule-kind").value;
		const target = kind === "Item Group" ? $("wsp-rule-group").value : kind === "Brand" ? $("wsp-rule-brand").value : chosenItem && chosenItem.item_code;
		if (!target) return showError("markup_rules", L.rule_choose);
		const percent = $("wsp-rule-percent").value;
		if (percent === "") return showError("markup_rules", L.rule_percent_missing);
		if (rules.some((rule) => rule.rule_type === kind && rule.target === target)) return showError("markup_rules", L.rule_twice);
		rules.push({ rule_type: kind, target, markup_percent: Number(percent), label: kind === "Item" ? chosenItem.name + " (" + target + ")" : "" });
		renderRules();
		$("wsp-rule-percent").value = "";
		$("wsp-rule-group").value = "";
		$("wsp-rule-brand").value = "";
		$("wsp-rule-search").value = "";
		chooseItem(null);
	}

	function render(payload) {
		fillSelect(form.elements.price_rounding, payload.roundings.map((value) => [value, L["rounding_" + value] || value]));
		fillSelect(form.elements.price_display, [
			["Excluding VAT", L.display_excluding],
			["Including VAT", L.display_including],
		]);
		FIELDS.forEach((name) => {
			const value = payload.values[name];
			if (form.elements[name] && value != null) form.elements[name].value = value;
		});
		lastInk = payload.ink;
		renderLogo(payload.logo);
		renderCredit(payload.credit_line);
		rules = (payload.values.markup_rules || []).map((rule) => ({ rule_type: rule.rule_type, target: rule.target, markup_percent: rule.markup_percent, label: "" }));
		renderRules();
		renderSample();
		toggleVat();
	}

	function renderPreview(answer) {
		$("wsp-try-list").textContent = fmt(L.try_list, answer.price_list);
		const body = $("wsp-try-rows");
		body.textContent = "";
		if (!answer.rows.length) {
			const row = body.insertRow();
			const cell = row.insertCell();
			cell.colSpan = 3;
			cell.className = "text-muted";
			cell.textContent = L.try_empty;
			return;
		}
		answer.rows.forEach((item) => {
			const row = body.insertRow();
			const name = row.insertCell();
			name.textContent = item.name;
			const cost = row.insertCell();
			cost.className = "text-right";
			cost.textContent = item.cost;
			const price = row.insertCell();
			price.className = "text-right font-weight-bold";
			price.textContent = item.price;
		});
	}

	function refreshPreview() {
		clearTimeout(previewTimer);
		previewTimer = setTimeout(() => {
			const args = {};
			PREVIEW_FIELDS.forEach(([field, argument]) => (args[argument] = form.elements[field].value));
			const seq = ++previewSeq;
			call("preview_prices", args, "GET")
				.then((answer) => {
					if (seq !== previewSeq) return; // a later keystroke already asked again
					["default_markup_percent", "price_rounding", "price_display", "vat_rate", "primary_colour", "secondary_colour"].forEach((field) => showError(field, ""));
					if (!answer.ok) return showError(answer.field, answer.message);
					lastInk = answer.ink;
					renderSample();
					renderPreview(answer);
				})
				.catch(() => setStatus(L.failed));
		}, 350);
	}

	form.addEventListener("submit", (event) => {
		event.preventDefault();
		clearErrors();
		setStatus("");
		const values = {};
		FIELDS.forEach((name) => (values[name] = form.elements[name].value));
		values.markup_rules = rules.map((rule) => ({ rule_type: rule.rule_type, target: rule.target, markup_percent: rule.markup_percent }));
		call("save_my_brand", { values: JSON.stringify(values) })
			.then((answer) => {
				if (!answer.ok) return showError(answer.field, answer.message);
				render(answer);
				setStatus(L.saved);
				refreshPreview();
			})
			.catch(() => setStatus(L.failed));
	});

	form.addEventListener("input", (event) => {
		const name = event.target.name;
		if (name === "brand_name" || name === "primary_colour" || name === "secondary_colour") renderSample();
		if (name === "price_display") toggleVat();
		if (PREVIEW_FIELDS.some(([field]) => field === name)) refreshPreview();
	});

	$("wsp-logo-file").addEventListener("change", (event) => {
		const file = event.target.files && event.target.files[0];
		showError("logo", "");
		if (!file) return;
		if (file.size > MAX_LOGO_BYTES) {
			event.target.value = "";
			return showError("logo", L.logo_too_large);
		}
		const reader = new FileReader();
		reader.onload = () => {
			call("upload_my_logo", { content: reader.result })
				.then((answer) => {
					event.target.value = "";
					if (!answer.ok) return showError("logo", answer.message);
					renderLogo(answer.logo);
				})
				.catch(() => showError("logo", L.failed));
		};
		reader.readAsDataURL(file);
	});

	$("wsp-logo-remove").addEventListener("click", () => {
		call("remove_my_logo")
			.then((answer) => renderLogo(answer.logo))
			.catch(() => showError("logo", L.failed));
	});

	KINDS.forEach((kind) => $("wsp-rule-kind").appendChild(option(kind, kindLabel(kind))));
	$("wsp-rule-kind").addEventListener("change", showKind);
	$("wsp-rule-search").addEventListener("input", searchItems);
	$("wsp-rule-add").addEventListener("click", addRule);
	showKind();
	call("get_choices", {}, "GET", CATALOGUE_API)
		.then(fillRuleChoices)
		.catch(() => setStatus(L.failed));

	setStatus(L.loading);
	call("get_my_brand", {}, "GET")
		.then((payload) => {
			setStatus("");
			render(payload);
			refreshPreview();
		})
		.catch(() => setStatus(L.failed));
})();
