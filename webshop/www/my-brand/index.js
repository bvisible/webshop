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

	const fmt = (text, ...args) => String(text || "").replace(/\{(\d+)\}/g, (m, i) => (args[i] == null ? "" : args[i]));

	function call(method, args, type) {
		return new Promise((resolve, reject) => {
			frappe.call({ method: API + method, type: type || "POST", args: args || {}, callback: (r) => resolve(r.message), error: (e) => reject(e) });
		});
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

	setStatus(L.loading);
	call("get_my_brand", {}, "GET")
		.then((payload) => {
			setStatus("");
			render(payload);
			refreshPreview();
		})
		.catch(() => setStatus(L.failed));
})();
