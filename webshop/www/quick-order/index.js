//// Neoffice — added file (the quick order, no upstream equivalent).
//// Plain JS, loaded with the page only. Everything it says comes from the server's
//// labels; everything it knows about the customer comes from the session behind
//// the requests. The draft lives here, in localStorage, until "send to cart".
(function () {
	const configNode = document.getElementById("wsh-qo-config");
	const root = document.getElementById("wsh-qo");
	if (!configNode || !root) return;

	const config = JSON.parse(configNode.textContent || "{}");
	const L = config.labels || {};
	const STORAGE_KEY = `webshop:quick-order:${config.site}:${config.user}`;
	const STORAGE_VERSION = 1;
	const DRAFT_DAYS = 7;
	const DEBOUNCE_MS = 150;

	const el = {
		input: root.querySelector(".wsh-qo__input"),
		suggestions: root.querySelector(".wsh-qo__suggestions"),
		notice: root.querySelector(".wsh-qo__notice"),
		models: root.querySelector(".wsh-qo__models"),
		empty: root.querySelector(".wsh-qo__empty"),
		pieces: root.querySelector(".wsh-qo__pieces"),
		lines: root.querySelector(".wsh-qo__lines"),
		amount: root.querySelector(".wsh-qo__amount"),
		send: root.querySelector(".wsh-qo__send"),
		clear: root.querySelector(".wsh-qo__clear"),
		report: root.querySelector(".wsh-qo__report"),
		resume: root.querySelector(".wsh-qo__resume"),
		resumeText: root.querySelector(".wsh-qo__resume-text"),
		resumeYes: root.querySelector(".wsh-qo__resume-yes"),
		resumeNo: root.querySelector(".wsh-qo__resume-no"),
		//// Neoffice — added fullscreen and fullscreenLabel node refs, for the new fullscreen toggle (42c10358d1 "fix(quick-order): produits simples tarifés par le serveur, steppers, plein écran")
		fullscreen: root.querySelector(".wsh-qo__fullscreen"),
		fullscreenLabel: root.querySelector(".wsh-qo__fullscreen-label"),
	};

	// ------------------------------------------------------------------
	// state: the draft. models = the open grids, in order; lines = qty per variant.
	// ------------------------------------------------------------------
	const state = {
		models: [], // [{template, data, dim3}]
		lines: new Map(), // item_code -> {qty, template, price, name, attrs}
	};

	const money = (value) => {
		try {
			const locale = config.lang === "fr" ? "fr-CH" : config.lang || "fr-CH";
			return new Intl.NumberFormat(locale, { style: "currency", currency: config.currency || "CHF" }).format(value);
		} catch (e) {
			return `${(value || 0).toFixed(2)} ${config.currency || ""}`;
		}
	};
	const fmt = (text, ...args) => String(text || "").replace(/\{(\d+)\}/g, (m, i) => (args[i] == null ? "" : args[i]));
	const escape = (text) =>
		String(text == null ? "" : text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

	function call(method, args) {
		return new Promise((resolve, reject) => {
			frappe.call({ method, type: "POST", args: args || {}, callback: (r) => resolve(r.message), error: (e) => reject(e) });
		});
	}

	// ------------------------------------------------------------------
	// persistence
	// ------------------------------------------------------------------
	function save() {
		try {
			const payload = {
				version: STORAGE_VERSION,
				saved_at: Date.now(),
				models: state.models.map((m) => ({ template: m.template, dim3: m.dim3 })),
				lines: [...state.lines.entries()].map(([item_code, line]) => ({ item_code, ...line })),
			};
			localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
		} catch (e) {
			// a full or blocked storage only means no resume after a reload
		}
	}

	function loadDraft() {
		try {
			const raw = localStorage.getItem(STORAGE_KEY);
			if (!raw) return null;
			const draft = JSON.parse(raw);
			if (!draft || draft.version !== STORAGE_VERSION) return null;
			if (Date.now() - (draft.saved_at || 0) > DRAFT_DAYS * 86400000) return null;
			if (!(draft.lines || []).length) return null;
			return draft;
		} catch (e) {
			return null;
		}
	}

	function forgetDraft() {
		try {
			localStorage.removeItem(STORAGE_KEY);
		} catch (e) {
			// nothing to forget
		}
	}

	// ------------------------------------------------------------------
	// totals
	// ------------------------------------------------------------------
	function totals() {
		let pieces = 0, amount = 0, priced = true;
		state.lines.forEach((line) => {
			pieces += line.qty;
			if (line.price == null) priced = false;
			else amount += line.qty * line.price;
		});
		return { pieces, amount, priced, lines: state.lines.size };
	}

	function renderTotals() {
		const t = totals();
		el.pieces.textContent = t.pieces;
		el.lines.textContent = t.lines;
		el.amount.textContent = t.pieces ? money(t.amount) + (t.priced ? "" : " *") : "—";
		el.send.disabled = !t.pieces;
		el.empty.hidden = state.models.length > 0;
	}

	function setQty(item_code, qty, meta) {
		qty = Math.max(0, Math.floor(Number(qty) || 0));
		if (qty > 0) {
			const previous = state.lines.get(item_code) || {};
			state.lines.set(item_code, { ...previous, ...(meta || {}), qty });
		} else {
			state.lines.delete(item_code);
		}
		renderTotals();
		//// Neoffice — keeps the grid's own "add to cart" button in sync with its quantities (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille")
		const template = (meta && meta.template) || (state.lines.get(item_code) || {}).template;
		if (template) {
			const node = el.models.querySelector(`[data-template="${CSS.escape(template)}"]`);
			const model = state.models.find((m) => m.template === template);
			if (node && model) refreshModelButton(node, model);
		}
		save();
	}

	//// Neoffice — added modelLines()/refreshModelButton() (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): each grid now has its own "add to cart (N)" button, so it needs its own subset of the draft and its own label.
	function modelLines(model) {
		return [...state.lines.entries()].filter(([, line]) => line.template === model.template).map(([item_code, line]) => ({ item_code, qty: line.qty }));
	}

	function refreshModelButton(node, model) {
		const button = node.querySelector(".wsh-qo-model__add");
		if (!button) return;
		const pieces = modelLines(model).reduce((sum, l) => sum + l.qty, 0);
		button.disabled = !pieces;
		button.textContent = pieces ? `${L.add_model} (${pieces})` : L.add_model;
	}

	// ------------------------------------------------------------------
	// the grid of one model
	// ------------------------------------------------------------------
	function variantKey(values) {
		return values.map((v) => String(v)).join("|~|");
	}

	async function openModel(template, focusItem) {
		let model = state.models.find((m) => m.template === template);
		if (!model) {
			let data;
			try {
				data = await call("webshop.webshop.quick_order.api.get_matrix", { template });
			} catch (e) {
				notice(L.error);
				return null;
			}
			if (!data || !(data.variants || []).length) {
				notice(L.none);
				return null;
			}
			model = { template, data, dim3: null };
			if (data.attributes.length >= 3) model.dim3 = data.attributes[2].values[0];
			state.models.unshift(model);
			renderModel(model, true);
		}
		if (focusItem) {
			const variant = model.data.variants.find((v) => v.item_code === focusItem);
			if (variant && model.data.attributes.length >= 3) {
				const dim3 = variant.attrs[model.data.attributes[2].attribute];
				if (dim3 && dim3 !== model.dim3) {
					model.dim3 = dim3;
					renderModel(model, false);
				}
			}
		}
		save();
		renderTotals();
		return model;
	}

	function closeModel(template) {
		state.models = state.models.filter((m) => m.template !== template);
		const node = el.models.querySelector(`[data-template="${CSS.escape(template)}"]`);
		if (node) node.remove();
		state.lines.forEach((line, item_code) => {
			if (line.template === template) state.lines.delete(item_code);
		});
		renderTotals();
		save();
	}

	function cellHtml(variant) {
		if (!variant) return `<td class="wsh-qo-cell wsh-qo-cell--none" title="${escape(L.none)}">—</td>`;
		const line = state.lines.get(variant.item_code);
		const qty = line ? line.qty : "";
		let stockText, stockClass;
		if (variant.stock == null) {
			stockText = L.unlimited;
			stockClass = "is-unlimited";
		} else if (variant.stock > 0) {
			stockText = fmt(L.available, variant.stock);
			stockClass = "has-stock";
		} else {
			stockText = L.out_of_stock;
			stockClass = "is-out";
		}
		//// Neoffice — struck-through list price alongside the customer's price (6696be727a "feat(quick-order): le prix du client, et la commande en Excel")
		const price = variant.formatted_price
			? (variant.formatted_list_price ? `<s>${escape(variant.formatted_list_price)}</s> ${escape(variant.formatted_price)}` : escape(variant.formatted_price))
			: escape(L.price_on_request);
		//// Neoffice — a cell is not orderable when the item has no price on the
		//// customer's list ("Prix sur demande") or when a stock item is out of stock
		//// (stock === 0; null = non-stock = unlimited). No input then, so nothing can be
		//// typed or sent; the server refuses these too. (2026-09-07)
		const noPrice = variant.price == null;
		const outOfStock = variant.stock === 0;
		if (noPrice || outOfStock) {
			return `<td class="wsh-qo-cell wsh-qo-cell--off" title="${escape(variant.item_code)}">
				<span class="wsh-qo-off">${escape(noPrice ? L.price_on_request : L.out_of_stock)}</span>
				${noPrice ? "" : `<span class="wsh-qo-cell__meta"><span class="wsh-qo-price">${price}</span></span>`}
			</td>`;
		}
		// available cap: a stock item is limited to its available qty; null = unlimited
		const maxAttr = variant.stock == null ? "" : ` max="${variant.stock}"`;
		const over = variant.stock != null && qty > variant.stock ? " is-over" : "";
		// //// Neoffice — the returned markup below now carries a wsh-qo-price span, using the `price` computed above (6696be727a "feat(quick-order): le prix du client, et la commande en Excel"); not marked inline since it sits inside this template literal
		// //// Neoffice — the qty input below now carries the max attribute so the browser itself refuses more than the available stock (eb91b0ba75 "fix(quick-order): un article sans prix ou épuisé n'est pas commandable, quantité plafonnée au stock"); not marked inline since it sits inside this template literal
		return `<td class="wsh-qo-cell${over}" data-item="${escape(variant.item_code)}" data-stock="${variant.stock == null ? "" : variant.stock}">
			<span class="wsh-qo-cell-controls">
				<button type="button" class="wsh-qo-step wsh-qo-minus" tabindex="-1" aria-label="-">\u2212</button>
				<input type="number" class="wsh-qo-qty" min="0" step="1"${maxAttr} inputmode="numeric" placeholder="0" value="${qty}"
					data-item="${escape(variant.item_code)}" aria-label="${escape(variant.item_name)}" title="${escape(variant.item_code)}">
				<button type="button" class="wsh-qo-step wsh-qo-plus" tabindex="-1" aria-label="+">+</button>
			</span>
			<span class="wsh-qo-cell__meta"><span class="wsh-qo-stock ${stockClass}">${escape(stockText)}</span><span class="wsh-qo-price">${price}</span></span>
		</td>`;
	}

	function renderModel(model, prepend) {
		const data = model.data;
		const attrs = data.attributes;
		const byCombo = {};
		data.variants.forEach((v) => {
			byCombo[variantKey(attrs.map((a) => v.attrs[a.attribute]))] = v;
		});

		let dim3Html = "";
		if (attrs.length >= 3) {
			const options = attrs[2].values
				.map((v) => `<option value="${escape(v)}"${v === model.dim3 ? " selected" : ""}>${escape(v)}</option>`)
				.join("");
			dim3Html = `<label class="wsh-qo-dim3"><span>${escape(attrs[2].attribute)}</span><select class="form-control form-control-sm wsh-qo-dim3-select">${options}</select></label>`;
		}

		let table;
		//// Neoffice — added the data.simple branch: a simple item now renders as one clean line instead of the old double "Qté / Qté" header (42c10358d1 "fix(quick-order): produits simples tarifés par le serveur, steppers, plein écran")
		if (data.simple || attrs.length === 0) {
			// a simple item: name + one qty cell, no attribute table (which showed a
			// confusing "Qté / Qté" double header)
			const v = data.variants[0];
			table = `<table class="wsh-qo-table wsh-qo-table--single"><tbody><tr><th scope="row">${escape(v ? v.item_name : "")}</th>${cellHtml(v)}</tr></tbody></table>`;
		} else if (attrs.length === 1) {
			const rows = attrs[0].values
				.map((v1) => `<tr><th scope="row">${escape(v1)}</th>${cellHtml(byCombo[variantKey([v1])])}</tr>`)
				.join("");
			table = `<table class="wsh-qo-table"><thead><tr><th>${escape(attrs[0].attribute)}</th><th>${escape(L.qty)}</th></tr></thead><tbody>${rows}</tbody></table>`;
		} else {
			const cols = attrs[1].values;
			const head = cols.map((v) => `<th>${escape(v)}</th>`).join("");
			const rows = attrs[0].values
				.map((v1) => {
					const cells = cols
						.map((v2) => cellHtml(byCombo[variantKey(attrs.length >= 3 ? [v1, v2, model.dim3] : [v1, v2])]))
						.join("");
					return `<tr><th scope="row">${escape(v1)}</th>${cells}</tr>`;
				})
				.join("");
			table = `<table class="wsh-qo-table"><thead><tr><th class="wsh-qo-corner">${escape(attrs[0].attribute)} \\ ${escape(attrs[1].attribute)}</th>${head}</tr></thead><tbody>${rows}</tbody></table>`;
		}

		const image = data.template.image ? `<img src="${escape(data.template.image)}" alt="">` : "";
		//// Neoffice — the markup below adds a wsh-qo-model__add button: each grid now has its own "add to cart" (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille")
		//// Neoffice — see also below: the variant-count span hides its count for a simple item (42c10358d1 "fix(quick-order): produits simples tarifés par le serveur, steppers, plein écran")
		const html = `
			<header class="wsh-qo-model__head">
				${image}
				<div class="wsh-qo-model__title">
					<a href="${escape("/" + (data.template.route || ""))}" target="_blank" rel="noopener">${escape(data.template.name)}</a>
					<span class="text-muted">${escape(data.template.item_code)}${data.simple ? "" : " · " + escape(fmt(L.variants, data.variants.length))}</span>
				</div>
				${dim3Html}
				<button type="button" class="btn btn-sm btn-light wsh-qo-model__reset">${escape(L.reset_model)}</button>
				<button type="button" class="btn btn-sm btn-primary wsh-qo-model__add" disabled>${escape(L.add_model)}</button>
				<button type="button" class="btn btn-sm btn-light wsh-qo-model__close" aria-label="${escape(L.close)}">×</button>
			</header>
			<div class="wsh-qo-model__scroll">${table}</div>`;

		let node = el.models.querySelector(`[data-template="${CSS.escape(model.template)}"]`);
		if (!node) {
			node = document.createElement("section");
			node.className = "wsh-qo-model";
			node.dataset.template = model.template;
			if (prepend) el.models.insertBefore(node, el.empty.nextSibling);
			else el.models.appendChild(node);
		}
		node.innerHTML = html;
		bindModel(node, model);
	}

	function bindModel(node, model) {
		node.querySelectorAll(".wsh-qo-qty").forEach((input) => {
			input.addEventListener("input", () => {
				const variant = model.data.variants.find((v) => v.item_code === input.dataset.item);
				// //// Neoffice — capping the typed quantity to the available stock, with an alert (eb91b0ba75 "fix(quick-order): un article sans prix ou épuisé n'est pas commandable, quantité plafonnée au stock")
				const cell = input.closest(".wsh-qo-cell");
				const stock = cell.dataset.stock === "" ? null : Number(cell.dataset.stock);
				// can't order more than what's available; null stock = unlimited
				if (stock != null && (parseFloat(input.value) || 0) > stock) {
					input.value = stock > 0 ? stock : "";
					if (window.frappe && frappe.show_alert) {
						frappe.show_alert({ message: fmt(L.capped_to_stock, stock), indicator: "orange" });
					}
				}
				if ((parseFloat(input.value) || 0) < 0) input.value = "";
				setQty(input.dataset.item, input.value, {
					template: model.template,
					price: variant ? variant.price : null,
					name: variant ? variant.item_name : input.dataset.item,
					attrs: variant ? variant.attrs : {},
				});
				// //// Neoffice — clears the over-stock highlight now that typing past it is capped rather than just flagged (eb91b0ba75 "fix(quick-order): un article sans prix ou épuisé n'est pas commandable, quantité plafonnée au stock")
				cell.classList.remove("is-over");
			});
			input.addEventListener("focus", () => input.select());
			input.addEventListener("keydown", (e) => {
				if (e.key === "Enter" && !e.ctrlKey && !e.metaKey) {
					e.preventDefault();
					focusNextCell(input);
				} else if (e.key === "Escape") {
					e.preventDefault();
					el.input.focus();
				}
			});
		});
		//// - / + steppers around each qty input; a step triggers the same input handler
		node.querySelectorAll(".wsh-qo-step").forEach((step) => {
			step.addEventListener("click", () => {
				const input = step.parentElement.querySelector(".wsh-qo-qty");
				if (!input) return;
				const delta = step.classList.contains("wsh-qo-plus") ? 1 : -1;
				// //// Neoffice — the stepper caps to the available stock too, same rule as typing directly (eb91b0ba75 "fix(quick-order): un article sans prix ou épuisé n'est pas commandable, quantité plafonnée au stock")
				const cell = input.closest(".wsh-qo-cell");
				const stock = cell.dataset.stock === "" ? null : Number(cell.dataset.stock);
				let next = Math.max(0, (parseFloat(input.value) || 0) + delta);
				if (stock != null && next > stock) next = stock;
				input.value = next > 0 ? next : "";
				input.dispatchEvent(new Event("input", { bubbles: true }));
			});
		});
		const dim3 = node.querySelector(".wsh-qo-dim3-select");
		if (dim3) {
			dim3.addEventListener("change", () => {
				model.dim3 = dim3.value;
				renderModel(model, false);
				save();
			});
		}
		node.querySelector(".wsh-qo-model__close").addEventListener("click", () => closeModel(model.template));
		//// Neoffice — added the grid's own send button (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille")
		// this grid alone goes to the cart: the customer who works model by model does not wait for the end
		node.querySelector(".wsh-qo-model__add").addEventListener("click", () => sendModel(model));
		refreshModelButton(node, model);
		node.querySelector(".wsh-qo-model__reset").addEventListener("click", () => {
			model.data.variants.forEach((v) => state.lines.delete(v.item_code));
			renderModel(model, false);
			renderTotals();
			save();
		});
	}

	function focusNextCell(input) {
		const inputs = [...input.closest(".wsh-qo-model").querySelectorAll(".wsh-qo-qty")];
		const index = inputs.indexOf(input);
		const next = inputs[index + 1];
		if (next) next.focus();
		else el.input.focus();
	}

	function focusCell(item_code, increment) {
		const input = el.models.querySelector(`.wsh-qo-qty[data-item="${CSS.escape(item_code)}"]`);
		if (!input) return false;
		if (increment) {
			input.value = (Number(input.value) || 0) + 1;
			input.dispatchEvent(new Event("input", { bubbles: true }));
			input.classList.add("is-flash");
			setTimeout(() => input.classList.remove("is-flash"), 600);
		}
		input.focus();
		input.scrollIntoView({ block: "nearest" });
		return true;
	}

	// ------------------------------------------------------------------
	// search
	// ------------------------------------------------------------------
	let searchTimer = null, activeIndex = -1, lastResults = [];

	function notice(text) {
		if (!text) {
			el.notice.hidden = true;
			el.notice.textContent = "";
			return;
		}
		el.notice.textContent = text;
		el.notice.hidden = false;
	}

	function closeSuggestions() {
		el.suggestions.hidden = true;
		el.suggestions.innerHTML = "";
		el.input.setAttribute("aria-expanded", "false");
		activeIndex = -1;
		lastResults = [];
	}

	function renderSuggestions(results) {
		lastResults = results;
		activeIndex = results.length ? 0 : -1;
		if (!results.length) {
			closeSuggestions();
			notice(L.no_results);
			return;
		}
		notice("");
		el.suggestions.innerHTML = results
			.map((r, i) => {
				const image = r.image ? `<img src="${escape(r.image)}" alt="">` : `<span class="wsh-qo-sugg__abbr">${escape((r.name || "?").slice(0, 2))}</span>`;
				const detail =
					r.kind === "variant"
						? Object.values(r.attrs || {}).join(" · ")
						: r.kind === "template"
							? fmt(L.variants, r.variant_count)
							: "";
				return `<li role="option" data-index="${i}" class="wsh-qo-sugg${i === activeIndex ? " is-active" : ""}" aria-selected="${i === activeIndex}">
					${image}<span class="wsh-qo-sugg__text"><b>${escape(r.name)}</b><small>${escape(r.item_code)}${detail ? " · " + escape(detail) : ""}</small></span></li>`;
			})
			.join("");
		el.suggestions.hidden = false;
		el.input.setAttribute("aria-expanded", "true");
		el.suggestions.querySelectorAll(".wsh-qo-sugg").forEach((li) => {
			li.addEventListener("mousedown", (e) => {
				e.preventDefault();
				choose(results[Number(li.dataset.index)]);
			});
		});
	}

	function moveActive(delta) {
		if (!lastResults.length) return;
		activeIndex = (activeIndex + delta + lastResults.length) % lastResults.length;
		el.suggestions.querySelectorAll(".wsh-qo-sugg").forEach((li, i) => {
			li.classList.toggle("is-active", i === activeIndex);
			li.setAttribute("aria-selected", i === activeIndex);
		});
	}

	async function search(query) {
		if (query.length < 2) {
			closeSuggestions();
			notice("");
			return;
		}
		let results;
		try {
			results = await call("webshop.webshop.quick_order.api.search_references", { query });
		} catch (e) {
			notice(L.error);
			return;
		}
		if (el.input.value.trim() !== query) return; // a newer query is on its way
		renderSuggestions(results || []);
	}

	async function choose(result) {
		closeSuggestions();
		el.input.value = "";
		if (!result) return;
		if (result.kind === "variant") {
			const model = await openModel(result.template, result.item_code);
			if (model) focusCell(result.item_code, true);
			return;
		}
		if (result.kind === "template") {
			const model = await openModel(result.item_code);
			if (model) {
				const first = el.models.querySelector(`[data-template="${CSS.escape(result.item_code)}"] .wsh-qo-qty`);
				if (first) first.focus();
			}
			return;
		}
		//// Neoffice — added the simple-item branch below: it now opens through get_matrix like any model, instead of a client-side path that never fetched a price (42c10358d1 "fix(quick-order): produits simples tarifés par le serveur, steppers, plein écran")
		// a simple item: the server prices it too (get_matrix returns a one-cell grid),
		// so it goes through the same path as a model — no client-side price guessing
		const model = await openModel(result.item_code);
		if (model) focusCell(result.item_code, true);
	}

	async function submitQuery() {
		const query = el.input.value.trim();
		if (!query) return;
		if (activeIndex >= 0 && lastResults[activeIndex]) {
			choose(lastResults[activeIndex]);
			return;
		}
		// no suggestion chosen: an exact code (a scanner that typed into the bar ends here)
		let found;
		try {
			found = await call("webshop.webshop.quick_order.api.resolve_code", { code: query });
		} catch (e) {
			notice(L.error);
			return;
		}
		if (!found || found.unknown) {
			notice(fmt(L.unknown_code, query));
			el.input.select();
			return;
		}
		el.input.value = "";
		closeSuggestions();
		if (found.template) {
			const model = await openModel(found.template, found.item_code);
			if (model) focusCell(found.item_code, true);
		} else {
			choose({ kind: "item", item_code: found.item_code, name: found.item_name, route: found.route });
		}
	}

	el.input.addEventListener("input", () => {
		clearTimeout(searchTimer);
		const query = el.input.value.trim();
		searchTimer = setTimeout(() => search(query), DEBOUNCE_MS);
	});
	el.input.addEventListener("keydown", (e) => {
		if (e.key === "ArrowDown") {
			e.preventDefault();
			moveActive(1);
		} else if (e.key === "ArrowUp") {
			e.preventDefault();
			moveActive(-1);
		} else if (e.key === "Enter") {
			e.preventDefault();
			clearTimeout(searchTimer);
			submitQuery();
		} else if (e.key === "Escape") {
			closeSuggestions();
			notice("");
		}
	});
	el.input.addEventListener("blur", () => setTimeout(closeSuggestions, 150));

	// ------------------------------------------------------------------
	// sending
	// ------------------------------------------------------------------
	function report(html) {
		el.report.innerHTML = html;
		el.report.hidden = !html;
	}

	//// Neoffice — added sendModel() (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): the customer working model by model sends this grid's lines without waiting for the whole draft; it disables/restores its own grid button rather than the global "send" one.
	// One model's lines go to the cart now; the rest of the draft stays.
	async function sendModel(model) {
		const lines = modelLines(model);
		if (!lines.length) return;
		const node = el.models.querySelector(`[data-template="${CSS.escape(model.template)}"]`);
		const button = node && node.querySelector(".wsh-qo-model__add");
		if (button) {
			button.disabled = true;
			button.textContent = L.sending;
		}
		//// Neoffice — removed the el.send disable/label lines here (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): this function only touches the grid's own button, above, not the page's global "send" button
		let out;
		try {
			out = await call("webshop.webshop.quick_order.api.add_lines", { lines: JSON.stringify(lines) });
		} catch (e) {
			//// Neoffice — restores the grid's own button, not a shared "send" one (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille")
			if (button) refreshModelButton(node, model);
			report(`<p class="text-danger">${escape(L.error)}</p>`);
			return;
		}
		//// Neoffice — see the block marker above: clears sent lines, keeps refused ones
		const refused = new Set((out.refused || []).map((r) => r.item_code));
		lines.forEach((l) => {
			if (!refused.has(l.item_code)) state.lines.delete(l.item_code);
		});
		renderModel(model, false);
		renderTotals();
		save();
		report(reportHtml(out));
	}

	function reportHtml(out) {
		const added = (out.added || []).reduce((sum, l) => sum + l.qty, 0);
		let html = `<p class="wsh-qo__report-ok">${escape(fmt(L.report_added, added))}</p>`;
		if ((out.capped || []).length) {
			html += `<p>${escape(L.report_capped)}</p><ul>${out.capped
				.map((c) => `<li>${escape(fmt(L.report_capped_line, c.item_code, c.asked, c.kept, c.available))}</li>`)
				.join("")}</ul>`;
		}
		if ((out.refused || []).length) {
			html += `<p>${escape(L.report_refused)}</p><ul>${out.refused
				.map((r) => `<li><b>${escape(r.item_code)}</b> × ${r.qty} — ${escape(r.reason)}</li>`)
				.join("")}</ul>`;
		}
		html += `<a class="btn btn-primary btn-block mt-3" href="${escape((out.cart && out.cart.url) || config.cart_url)}">${escape(L.see_cart)}</a>`;
		//// Neoffice — reportHtml() is now shared by sendModel() and send() (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"); send() below still owns the global "send" button, sendModel() above owns its grid's own button
		return html;
	}

	async function send() {
		const lines = [...state.lines.entries()].map(([item_code, line]) => ({ item_code, qty: line.qty }));
		if (!lines.length) {
			report(`<p>${escape(L.nothing_to_send)}</p>`);
			return;
		}
		el.send.disabled = true;
		const label = el.send.textContent;
		el.send.textContent = L.sending;
		let out;
		try {
			out = await call("webshop.webshop.quick_order.api.add_lines", { lines: JSON.stringify(lines) });
		} catch (e) {
			el.send.disabled = false;
			el.send.textContent = label;
			report(`<p class="text-danger">${escape(L.error)}</p>`);
			return;
		}
		el.send.textContent = label;
		report(reportHtml(out));
		// what went into the cart leaves the draft; what was refused stays for a second try
		const refused = new Set((out.refused || []).map((r) => r.item_code));
		state.lines.forEach((line, item_code) => {
			if (!refused.has(item_code)) state.lines.delete(item_code);
		});
		if (!refused.size) {
			state.models = [];
			el.models.querySelectorAll(".wsh-qo-model").forEach((n) => n.remove());
			forgetDraft();
		} else {
			state.models.forEach((m) => renderModel(m, false));
			save();
		}
		renderTotals();
		if (!refused.size && !(out.capped || []).length) {
			setTimeout(() => {
				window.location.href = (out.cart && out.cart.url) || config.cart_url;
			}, 1200);
		}
	}

	el.send.addEventListener("click", send);
	el.clear.addEventListener("click", () => {
		if (!state.lines.size && !state.models.length) return;
		if (!window.confirm(L.clear_confirm)) return;
		state.lines.clear();
		state.models = [];
		el.models.querySelectorAll(".wsh-qo-model").forEach((n) => n.remove());
		forgetDraft();
		renderTotals();
		report("");
		el.input.focus();
	});
	document.addEventListener("keydown", (e) => {
		if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
			e.preventDefault();
			if (!el.send.disabled) send();
		} else if (e.key === "/" && document.activeElement !== el.input && !/input|textarea|select/i.test(document.activeElement.tagName)) {
			e.preventDefault();
			el.input.focus();
		}
	});

	// ------------------------------------------------------------------
	// resume a draft
	// ------------------------------------------------------------------
	async function restore(draft) {
		for (const m of draft.models || []) {
			const model = await openModel(m.template);
			if (model && m.dim3 && model.data.attributes.length >= 3) {
				model.dim3 = m.dim3;
				renderModel(model, false);
			}
		}
		for (const line of draft.lines || []) {
			if (!state.models.find((m) => m.template === line.template)) await openModel(line.template);
			const model = state.models.find((m) => m.template === line.template);
			const variant = model && model.data.variants.find((v) => v.item_code === line.item_code);
			if (!variant) continue;
			setQty(line.item_code, line.qty, { template: line.template, price: variant.price, name: variant.item_name, attrs: variant.attrs });
		}
		state.models.forEach((m) => renderModel(m, false));
		renderTotals();
		save();
	}

	const draft = loadDraft();
	if (draft) {
		const pieces = (draft.lines || []).reduce((sum, l) => sum + (l.qty || 0), 0);
		const when = new Date(draft.saved_at);
		const stamp = `${when.toLocaleDateString(config.lang === "fr" ? "fr-CH" : undefined)} ${when.toLocaleTimeString(config.lang === "fr" ? "fr-CH" : undefined, { hour: "2-digit", minute: "2-digit" })}`;
		el.resumeText.textContent = fmt(L.resume, stamp, draft.lines.length, pieces);
		el.resume.hidden = false;
		el.resumeYes.addEventListener("click", async () => {
			el.resume.hidden = true;
			await restore(draft);
			el.input.focus();
		});
		el.resumeNo.addEventListener("click", () => {
			el.resume.hidden = true;
			forgetDraft();
			el.input.focus();
		});
	}

	//// Neoffice ▼▼▼ — added the fullscreen toggle block below: variant grids are wide, so a fullscreen button (native, with a CSS-only fallback) gives the grid the whole window (42c10358d1 "fix(quick-order): produits simples tarifés par le serveur, steppers, plein écran")
	// ------------------------------------------------------------------
	// fullscreen: variant grids are wide; the whole window gives room to see them
	// ------------------------------------------------------------------
	const fsTarget = root; // the app container goes fullscreen, header and recap included
	//// Neoffice — the CSS fallback is tracked in its own flag, and `is-fullscreen` is derived
	//// from the state instead of being part of it. isFullscreen() used to OR the native state
	//// with the presence of that very class; since entering natively adds the class, leaving
	//// natively could never remove it — the class kept isFullscreen() true and re-applied
	//// itself. The button was one-way on every browser with native fullscreen (measured
	//// headless: after exitFullscreen() document.fullscreenElement was null and the grid stayed
	//// full-window).
	let fallbackOn = false;
	function nativeOn() {
		return document.fullscreenElement === fsTarget;
	}
	function isFullscreen() {
		return nativeOn() || fallbackOn;
	}
	function reflectFullscreen() {
		const on = isFullscreen();
		root.classList.toggle("is-fullscreen", on);
		if (el.fullscreen) el.fullscreen.setAttribute("aria-pressed", on ? "true" : "false");
		if (el.fullscreenLabel) el.fullscreenLabel.textContent = on ? (L.exit_fullscreen || "") : (L.fullscreen || "");
	}
	if (el.fullscreen) {
		el.fullscreen.addEventListener("click", async () => {
			try {
				if (nativeOn()) {
					await document.exitFullscreen();
				} else if (fallbackOn) {
					//// Neoffice — leave the CSS fallback the way we entered it: without this
					//// branch, a browser that refuses native fullscreen (an iframe with no
					//// allowfullscreen, a denied permission) took you in through the fallback
					//// and then only ever retried requestFullscreen, with no way back out.
					fallbackOn = false;
				} else if (fsTarget.requestFullscreen) {
					await fsTarget.requestFullscreen();
				} else {
					// no native fullscreen: a CSS-only full-window fallback
					fallbackOn = true;
				}
			} catch (e) {
				fallbackOn = !fallbackOn;
			}
			reflectFullscreen();
		});
		document.addEventListener("fullscreenchange", reflectFullscreen);
	}
	//// Neoffice ▲▲▲

	renderTotals();
	el.input.focus();
})();
