// //// Neoffice — added file (the reseller's catalogues page, no upstream equivalent).
// Picks what goes in a catalogue (categories, brands, single products), asks the server for it and follows
// it while it is made. Nothing the server sends goes through innerHTML: it is written with textContent or as
// a property of an element. The page never computes a price and never sends one: it sends a title, a
// selection and three options.
(function () {
	"use strict";

	const configNode = document.getElementById("wsp-catalogues-config");
	if (!configNode) return;
	const L = JSON.parse(configNode.textContent).labels;
	const API = "webshop.webshop.catalogue.catalogue_api.";
	const POLL_MS = 2000;
	const $ = (id) => document.getElementById(id);
	const form = $("wsp-cat-form");

	const picked = { item_groups: new Set(), brands: new Set(), items: new Map() }; // items: code -> name
	let state = null;
	let countTimer = null;
	let countSeq = 0;
	let searchTimer = null;
	let searchSeq = 0;
	let pollTimer = null;

	const fmt = (text, ...args) => String(text || "").replace(/\{(\d+)\}/g, (m, i) => (args[i] == null ? "" : args[i]));

	function call(method, args, type) {
		return new Promise((resolve, reject) => {
			frappe.call({ method: API + method, type: type || "POST", args: args || {}, callback: (r) => resolve(r.message), error: (e) => reject(e) });
		});
	}

	function setStatus(text) {
		$("wsp-cat-status").textContent = text || "";
	}

	function clearErrors() {
		form.querySelectorAll("[data-error-for]").forEach((node) => (node.textContent = ""));
	}

	function showError(field, message) {
		const node = field && form.querySelector('[data-error-for="' + field + '"]');
		if (node) node.textContent = message;
		else setStatus(message);
	}

	function el(tag, text, className) {
		const node = document.createElement(tag);
		if (text != null) node.textContent = text;
		if (className) node.className = className;
		return node;
	}

	function option(value, text) {
		const node = document.createElement("option");
		node.value = value;
		node.textContent = text;
		return node;
	}

	function selection() {
		return {
			item_groups: Array.from(picked.item_groups),
			brands: Array.from(picked.brands),
			items: Array.from(picked.items.keys()),
		};
	}

	function isEmptySelection() {
		return !picked.item_groups.size && !picked.brands.size && !picked.items.size;
	}

	// --- the lists of categories and brands -----------------------------------------------------

	function checkList(container, entries, set, filterNode) {
		const render = () => {
			const needle = (filterNode.value || "").trim().toLowerCase();
			container.textContent = "";
			entries.forEach((entry) => {
				if (needle && entry.name.toLowerCase().indexOf(needle) === -1) return;
				const label = el("label", null, "d-flex align-items-center mb-1");
				label.style.paddingLeft = (entry.depth || 0) * 1.25 + "rem";
				const box = document.createElement("input");
				box.type = "checkbox";
				box.className = "mr-2";
				box.checked = set.has(entry.name);
				box.addEventListener("change", () => {
					if (box.checked) set.add(entry.name);
					else set.delete(entry.name);
					selectionChanged();
				});
				label.appendChild(box);
				label.appendChild(el("span", entry.name));
				label.appendChild(el("span", String(entry.count), "text-muted small ml-2"));
				container.appendChild(label);
			});
		};
		filterNode.addEventListener("input", render);
		render();
	}

	// --- the picker of single products ----------------------------------------------------------

	function renderChosen() {
		const list = $("wsp-cat-chosen");
		list.textContent = "";
		if (!picked.items.size) {
			list.appendChild(el("li", L.none_chosen, "text-muted"));
			return;
		}
		picked.items.forEach((name, code) => {
			const item = el("li", null, "d-flex align-items-center mb-1");
			item.appendChild(el("span", name, "mr-2"));
			item.appendChild(el("span", code, "text-muted small mr-2"));
			const remove = el("button", L.remove, "btn btn-sm btn-link p-0");
			remove.type = "button";
			remove.addEventListener("click", () => {
				picked.items.delete(code);
				renderChosen();
				selectionChanged();
			});
			item.appendChild(remove);
			list.appendChild(item);
		});
	}

	function renderResults(products) {
		const list = $("wsp-cat-results");
		list.textContent = "";
		products.forEach((product) => {
			const item = el("li", null, "list-group-item d-flex align-items-center py-1");
			item.appendChild(el("span", product.name, "mr-2"));
			item.appendChild(el("span", [product.item_code, product.brand].filter(Boolean).join(" · "), "text-muted small mr-auto"));
			const add = el("button", L.add, "btn btn-sm btn-light");
			add.type = "button";
			add.disabled = picked.items.has(product.item_code);
			add.addEventListener("click", () => {
				picked.items.set(product.item_code, product.name);
				add.disabled = true;
				renderChosen();
				selectionChanged();
			});
			item.appendChild(add);
			list.appendChild(item);
		});
	}

	function searchProducts() {
		const text = $("wsp-cat-search").value.trim();
		const seq = ++searchSeq;
		if (text.length < 2) {
			$("wsp-cat-results").textContent = "";
			return;
		}
		call("search_products", { text }, "GET")
			.then((answer) => {
				if (seq !== searchSeq) return;
				if (!answer.products.length) {
					const list = $("wsp-cat-results");
					list.textContent = "";
					list.appendChild(el("li", L.search_none, "list-group-item text-muted py-1"));
					return;
				}
				renderResults(answer.products);
			})
			.catch(() => {});
	}

	// --- how many products the choices bring ----------------------------------------------------

	function selectionChanged() {
		clearTimeout(countTimer);
		const node = $("wsp-cat-count");
		if (isEmptySelection()) {
			countSeq++;
			node.textContent = L.count_zero;
			return;
		}
		countTimer = setTimeout(() => {
			const seq = ++countSeq;
			call("count_products", { picked: JSON.stringify(selection()) })
				.then((answer) => {
					if (seq !== countSeq) return;
					node.textContent = answer.too_many
						? fmt(L.count_too_many, state ? state.limits.products : "")
						: answer.count
						? fmt(L.count_n, answer.count)
						: L.count_none_offered;
				})
				.catch(() => {});
		}, 250);
	}

	// --- the catalogues made --------------------------------------------------------------------

	function statusText(row) {
		if (row.status === "Running" && row.stage && L["stage_" + row.stage]) {
			return L["status_Running"] + " · " + L["stage_" + row.stage] + " · " + (row.progress || 0) + " %";
		}
		return L["status_" + row.status] || row.status;
	}

	function actionButton(text, className, handler) {
		const button = el("button", text, className);
		button.type = "button";
		button.addEventListener("click", handler);
		return button;
	}

	function renderRows() {
		const body = $("wsp-cat-rows");
		body.textContent = "";
		$("wsp-cat-empty").textContent = state.catalogues.length ? "" : L.none_yet;
		state.catalogues.forEach((row) => {
			const tr = document.createElement("tr");
			const title = el("td", row.title);
			if (row.status === "Failed" && row.error) title.appendChild(el("div", row.error, "text-danger small"));
			if (row.status === "Ready" && row.prices_as_of) {
				title.appendChild(el("div", fmt(L.kept, row.prices_as_of, row.expires_on), "text-muted small"));
			}
			tr.appendChild(title);
			tr.appendChild(el("td", (row.creation || "").slice(0, 16)));
			tr.appendChild(el("td", row.item_count ? String(row.item_count) : "", "text-right"));
			tr.appendChild(el("td", row.page_count ? String(row.page_count) : "", "text-right"));
			tr.appendChild(el("td", statusText(row)));
			const actions = el("td", null, "text-right text-nowrap");
			if (row.status === "Ready") {
				const link = el("a", L.download, "btn btn-sm btn-primary mr-1");
				link.href = "/api/method/" + API + "download_catalogue?name=" + encodeURIComponent(row.name);
				actions.appendChild(link);
			}
			if (!row.active) {
				const remake = actionButton(L.remake, "btn btn-sm btn-light mr-1", () => remakeCatalogue(row.name));
				remake.title = L.remake_hint;
				remake.disabled = state.busy;
				actions.appendChild(remake);
				actions.appendChild(actionButton(L.delete, "btn btn-sm btn-light", () => deleteCatalogue(row.name)));
			}
			tr.appendChild(actions);
			body.appendChild(tr);
		});
	}

	function applyState(next) {
		state = next;
		$("wsp-cat-brand-needed").classList.toggle("d-none", state.brand_saved);
		$("wsp-cat-no-engine").classList.toggle("d-none", state.engine !== false);
		$("wsp-cat-create").disabled = state.busy || !state.brand_saved || state.engine === false;
		if (state.busy) setStatus(L.busy);
		else if ($("wsp-cat-status").textContent === L.busy) setStatus("");
		renderRows();
		if (state.busy) schedulePoll();
	}

	function schedulePoll() {
		clearTimeout(pollTimer);
		pollTimer = setTimeout(refresh, POLL_MS);
	}

	function refresh() {
		call("get_catalogues", {}, "GET")
			.then(applyState)
			.catch(() => schedulePoll());
	}

	function remakeCatalogue(name) {
		setStatus("");
		call("remake_catalogue", { name })
			.then((answer) => (answer.ok ? applyState(answer) : setStatus(answer.message)))
			.catch(() => setStatus(L.failed));
	}

	function deleteCatalogue(name) {
		if (!window.confirm(L.delete_confirm)) return;
		call("delete_catalogue", { name })
			.then((answer) => (answer.ok ? applyState(answer) : setStatus(answer.message)))
			.catch(() => setStatus(L.failed));
	}

	// --- sending the request --------------------------------------------------------------------

	form.addEventListener("submit", (event) => {
		event.preventDefault();
		clearErrors();
		setStatus("");
		$("wsp-cat-create").disabled = true;
		call("create_catalogue", {
			title: $("wsp-cat-title").value,
			picked: JSON.stringify(selection()),
			options: JSON.stringify({
				markup_percent: $("wsp-cat-markup").value,
				prices: $("wsp-cat-prices").value,
				layout: $("wsp-cat-layout").value,
			}),
		})
			.then((answer) => {
				if (!answer.ok) {
					showError(answer.field, answer.message);
					$("wsp-cat-create").disabled = false;
					return;
				}
				$("wsp-cat-title").value = "";
				applyState(answer);
			})
			.catch(() => {
				setStatus(L.failed);
				$("wsp-cat-create").disabled = false;
			});
	});

	$("wsp-cat-search").addEventListener("input", () => {
		clearTimeout(searchTimer);
		searchTimer = setTimeout(searchProducts, 250);
	});

	// --- start ----------------------------------------------------------------------------------

	[["prices", [["customers", L.prices_customers], ["none", L.prices_none]]], ["layout", [["grid", L.layout_grid], ["list", L.layout_list]]]].forEach(
		([name, choices]) => {
			const select = $("wsp-cat-" + name);
			choices.forEach(([value, text]) => select.appendChild(option(value, text)));
		}
	);
	renderChosen();
	$("wsp-cat-count").textContent = L.count_zero;
	$("wsp-cat-rows").appendChild(el("tr", null)).appendChild(el("td", L.loading));

	Promise.all([call("get_catalogues", {}, "GET"), call("get_choices", {}, "GET")])
		.then(([next, choices]) => {
			$("wsp-cat-markup").value = next.default_markup;
			checkList($("wsp-cat-groups"), choices.groups, picked.item_groups, $("wsp-cat-filter-groups"));
			checkList($("wsp-cat-brands"), choices.brands, picked.brands, $("wsp-cat-filter-brands"));
			applyState(next);
		})
		.catch(() => setStatus(L.failed));
})();
