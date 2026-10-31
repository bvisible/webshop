// //// Neoffice — added file (the reseller's catalogues page, no upstream equivalent).
// Picks what goes in a catalogue (categories, brands, single products), asks the server for it and follows
// it while it is made. Nothing the server sends goes through innerHTML: it is written with textContent or as
// a property of an element. The page never computes a price and never sends one: it sends a title, a
// selection and the options (a markup, a price mode, a layout) and a format: a PDF, an Excel workbook, a CSV
// file, or a product feed (an address a shop or a script reads).
(function () {
	"use strict";

	const configNode = document.getElementById("wsp-catalogues-config");
	if (!configNode) return;
	const L = JSON.parse(configNode.textContent).labels;
	const API = "webshop.webshop.catalogue.catalogue_api.";
	const FEED_API = "webshop.webshop.catalogue.feed_api.";
	const FORMATS = ["pdf", "xlsx", "csv", "shopify", "feed"];
	// the price modes each format offers, and the label of each
	const PRICES = {
		pdf: [["customers", "prices_customers"], ["none", "prices_none"]],
		xlsx: [["customers", "prices_selling"], ["tariff", "prices_tariff"], ["both", "prices_both"], ["none", "prices_none"]],
		csv: [["customers", "prices_selling"], ["tariff", "prices_tariff"], ["both", "prices_both"], ["none", "prices_none"]],
		shopify: [["customers", "prices_selling"], ["both", "prices_both"]],
		feed: [["customers", "prices_selling"], ["none", "prices_none"]],
	};
	const POLL_MS = 2000;
	const FORMAT_NAMES = { PDF: "PDF", XLSX: "Excel", CSV: "CSV", SHOPIFY: "Shopify" };
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

	// --- the format ------------------------------------------------------------------------------

	const format = () => $("wsp-cat-format").value;
	const isFile = () => format() !== "pdf";

	function applyFormat() {
		const kind = format();
		$("wsp-cat-format-hint").textContent = L["hint_" + kind];
		$("wsp-cat-title-row").classList.toggle("d-none", kind === "feed");
		$("wsp-cat-layout-col").classList.toggle("d-none", kind !== "pdf");
		$("wsp-cat-quality-col").classList.toggle("d-none", kind !== "pdf");
		$("wsp-cat-order-form-col").classList.toggle("d-none", kind !== "pdf");
		const prices = $("wsp-cat-prices");
		const kept = prices.value;
		prices.textContent = "";
		PRICES[kind].forEach(([value, label]) => prices.appendChild(option(value, L[label])));
		if (PRICES[kind].some(([value]) => value === kept)) prices.value = kept;
		$("wsp-cat-create").textContent = kind === "pdf" ? L.create : L["create_" + kind];
		clearErrors();
		selectionChanged();
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

	// --- the language of the texts (lot 5c) ----------------------------------------------------------

	// Offered only where the shop enabled an additional language: the select is hidden otherwise, and the
	// choice the reseller made is kept when the state is read again (a catalogue being made refreshes it).
	function renderLanguages(offered) {
		const select = $("wsp-cat-language");
		const kept = select.value;
		select.textContent = "";
		select.appendChild(option("", L.language_source));
		offered.forEach((language) => select.appendChild(option(language.code, language.name)));
		if (offered.some((language) => language.code === kept)) select.value = kept;
		$("wsp-cat-language-col").classList.toggle("d-none", !offered.length);
	}

	// --- a catalogue started from a page of the shop (lot 5b) ---------------------------------------

	// The listing's "Make a catalogue" link carries the category, the brands and the search it shows. Only names the
	// shop offers are ticked (a name typed in an address is not a choice), and the search brings the products it finds.
	function applyListingLink(choices) {
		const params = new URLSearchParams(window.location.search);
		const known = (entries) => new Set(entries.map((entry) => entry.name));
		const groups = known(choices.groups);
		const brands = known(choices.brands);
		params.getAll("group").forEach((name) => groups.has(name) && picked.item_groups.add(name));
		params.getAll("brand").forEach((name) => brands.has(name) && picked.brands.add(name));
		const text = (params.get("q") || "").trim();
		if (text.length >= 2 && text.length <= 140) {
			call("search_products", { text }, "GET")
				.then((answer) => {
					((answer && answer.products) || []).forEach((product) => picked.items.set(product.item_code, product.name));
					renderChosen();
					selectionChanged();
				})
				.catch(() => {});
		}
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
			call("count_products", { picked: JSON.stringify(selection()), format: isFile() ? "csv" : "pdf" })
				.then((answer) => {
					if (seq !== countSeq) return;
					const lines = answer.unit === "lines";
					node.textContent = answer.too_many
						? fmt(lines ? L.count_lines_too_many : L.count_too_many, answer.limit)
						: answer.count
						? fmt(lines ? L.count_lines : L.count_n, answer.count)
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

	// --- sharing: a link that expires, and an e-mail that carries it (lot 5d) ---------------------------

	const sharing = new Set(); // the catalogues whose sharing panel is open

	function shareRequest(method, args, panel) {
		panel.error.textContent = "";
		return call(method, args)
			.then((answer) => {
				if (!answer.ok) {
					panel.error.textContent = answer.message || L.failed;
					return null;
				}
				applyState(answer);
				return answer;
			})
			.catch(() => {
				panel.error.textContent = L.failed;
				return null;
			});
	}

	function sharePanel(row) {
		const tr = document.createElement("tr");
		const cell = tr.insertCell();
		cell.colSpan = 7;
		cell.className = "bg-light";
		const box = el("div", null, "p-3");
		const panel = { error: el("div", "", "text-danger small mt-2") };
		box.appendChild(el("p", L.share_hint, "text-muted small mb-2"));
		const link = row.share;
		const row1 = el("div", null, "d-flex flex-wrap align-items-center mb-2");
		if (link && !link.expired) {
			const input = document.createElement("input");
			input.className = "form-control form-control-sm";
			input.style.maxWidth = "28rem";
			input.readOnly = true;
			input.value = link.url;
			row1.appendChild(input);
			row1.appendChild(copyButton(input));
			box.appendChild(row1);
			box.appendChild(el("div", fmt(L.share_until, link.expires_on) + " " + (link.opened_on ? fmt(L.share_opened, link.opened_on.slice(0, 16)) : L.share_never), "text-muted small mb-2"));
		} else if (link) {
			box.appendChild(el("p", L.share_expired, "text-warning small mb-2"));
		}
		const days = document.createElement("select");
		days.className = "form-control form-control-sm mr-2";
		days.style.maxWidth = "9rem";
		days.setAttribute("aria-label", L.share_days);
		[["7", L.share_days_7], ["14", L.share_days_14], ["30", L.share_days_30]].forEach(([value, text]) => days.appendChild(option(value, text)));
		days.value = "14";
		const make = actionButton(link && !link.expired ? L.share_new : L.share_make, "btn btn-sm btn-primary mr-2", () => shareRequest("share_catalogue", { name: row.name, days: days.value }, panel));
		if (link && !link.expired) make.title = L.share_new_hint;
		const group = el("div", null, "d-flex flex-wrap align-items-center mb-3");
		group.appendChild(el("span", L.share_days, "mr-2 small"));
		group.appendChild(days);
		group.appendChild(make);
		if (link) group.appendChild(actionButton(L.share_stop, "btn btn-sm btn-light", () => shareRequest("unshare_catalogue", { name: row.name }, panel)));
		box.appendChild(group);

		box.appendChild(el("h3", L.mail_title, "h6"));
		box.appendChild(el("p", L.mail_hint, "text-muted small mb-2"));
		const to = document.createElement("input");
		to.type = "email";
		to.className = "form-control form-control-sm mb-2";
		to.style.maxWidth = "28rem";
		to.maxLength = 254;
		to.placeholder = L.mail_to;
		to.setAttribute("aria-label", L.mail_to);
		to.autocomplete = "off";
		const text = document.createElement("textarea");
		text.className = "form-control form-control-sm mb-2";
		text.style.maxWidth = "28rem";
		text.rows = 3;
		text.maxLength = 500;
		text.placeholder = L.mail_message;
		text.setAttribute("aria-label", L.mail_message);
		const send = actionButton(L.mail_send, "btn btn-sm btn-outline-primary", () => {
			send.disabled = true;
			shareRequest("send_catalogue", { name: row.name, to: to.value, message: text.value }, panel).then((answer) => {
				send.disabled = false;
				if (answer) {
					panel.error.textContent = "";
					panel.done.textContent = L.mail_sent;
					to.value = "";
					text.value = "";
				}
			});
		});
		panel.done = el("div", "", "text-success small mt-2");
		box.appendChild(to);
		box.appendChild(text);
		box.appendChild(send);
		box.appendChild(panel.done);
		box.appendChild(panel.error);
		cell.appendChild(box);
		return tr;
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
			tr.appendChild(el("td", FORMAT_NAMES[row.format] || row.format || ""));
			tr.appendChild(el("td", (row.creation || "").slice(0, 16)));
			tr.appendChild(el("td", row.item_count ? String(row.item_count) : "", "text-right"));
			tr.appendChild(el("td", row.page_count ? String(row.page_count) : "", "text-right"));
			tr.appendChild(el("td", statusText(row)));
			const actions = el("td", null, "text-right text-nowrap");
			if (row.status === "Ready") {
				const link = el("a", L.download, "btn btn-sm btn-primary mr-1");
				link.href = "/api/method/" + API + "download_catalogue?name=" + encodeURIComponent(row.name);
				actions.appendChild(link);
				if (row.sharable) {
					const share = actionButton(L.share, "btn btn-sm btn-light mr-1", () => {
						if (sharing.has(row.name)) sharing.delete(row.name);
						else sharing.add(row.name);
						renderRows();
					});
					share.setAttribute("aria-expanded", sharing.has(row.name) ? "true" : "false");
					actions.appendChild(share);
				}
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
			if (sharing.has(row.name) && row.sharable) body.appendChild(sharePanel(row));
		});
	}

	// a PDF carries the brand; a file or a feed needs it only for a selling price (its markup and rounding)
	function brandNeeded() {
		return format() === "pdf" || ["customers", "both"].indexOf($("wsp-cat-prices").value) !== -1;
	}

	function updateCreate() {
		if (!state) return;
		const kind = format();
		let off;
		if (kind === "feed") off = !!(state.feed && state.feed.active);
		else off = state.busy || (kind === "pdf" && state.engine === false);
		$("wsp-cat-create").disabled = off || (brandNeeded() && !state.brand_saved);
		$("wsp-cat-brand-needed").classList.toggle("d-none", state.brand_saved || !brandNeeded());
		$("wsp-cat-no-engine").classList.toggle("d-none", state.engine !== false || kind !== "pdf");
	}

	function applyState(next) {
		state = next;
		renderLanguages(next.languages || []);
		const particular = $("wsp-cat-markup-particular");
		particular.textContent = next.particular_markups ? fmt(L.markup_particular, next.particular_markups) : "";
		particular.classList.toggle("d-none", !next.particular_markups);
		updateCreate();
		if (state.busy) setStatus(L.busy);
		else if ($("wsp-cat-status").textContent === L.busy) setStatus("");
		renderRows();
		renderFeed();
		if (state.busy || (state.feed && state.feed.active)) schedulePoll();
	}

	// --- the product feed -----------------------------------------------------------------------

	function copyButton(input) {
		const button = el("button", L.copy, "btn btn-sm btn-light ml-2");
		button.type = "button";
		button.addEventListener("click", () => {
			const done = () => {
				button.textContent = L.copied;
				setTimeout(() => (button.textContent = L.copy), 1500);
			};
			input.select();
			if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(input.value).then(done, () => document.execCommand("copy") && done());
			else if (document.execCommand("copy")) done();
		});
		return button;
	}

	function feedAction(method, text, confirmText) {
		return actionButton(text, "btn btn-sm btn-light mr-2 mb-1", () => {
			if (confirmText && !window.confirm(confirmText)) return;
			$("wsp-feed-message").classList.add("d-none");
			call(method, {}, "POST", FEED_API)
				.then((answer) => {
					if (answer.ok) return applyState(answer);
					$("wsp-feed-message").textContent = answer.message;
					$("wsp-feed-message").classList.remove("d-none");
				})
				.catch(() => {
					$("wsp-feed-message").textContent = L.failed;
					$("wsp-feed-message").classList.remove("d-none");
				});
		});
	}

	function renderFeed() {
		const feed = state.feed;
		$("wsp-feed").classList.toggle("d-none", !feed);
		if (!feed) return;
		const status = $("wsp-feed-status");
		status.textContent = (L["feed_status_" + feed.status] || feed.status) + (feed.active && feed.progress ? " · " + Math.round(feed.progress) + " %" : "");
		if (feed.status === "Failed") {
			status.appendChild(el("div", [feed.error, feed.served ? L.feed_kept : ""].filter(Boolean).join(" "), "text-danger small font-weight-normal"));
		}
		const facts = [];
		if (feed.generated_on) facts.push(fmt(L.feed_lines, feed.lines, feed.prices_as_of));
		facts.push(feed.last_fetched ? fmt(L.feed_fetched, feed.last_fetched.slice(0, 16)) : L.feed_never_fetched);
		$("wsp-feed-facts").textContent = facts.join(" · ");
		$("wsp-feed-choices").textContent =
			fmt(L.feed_choices, feed.groups, feed.brands, feed.products, feed.markup_percent) +
			" · " + (feed.prices === "none" ? L.feed_prices_none : L.feed_prices_customers);
		const addresses = $("wsp-feed-addresses");
		addresses.textContent = "";
		["csv", "json"].forEach((kind) => {
			if (!feed.addresses || !feed.addresses[kind]) return;
			const row = el("div", null, "d-flex align-items-center mb-2");
			const input = document.createElement("input");
			input.className = "form-control form-control-sm";
			input.readOnly = true;
			input.value = feed.addresses[kind];
			input.setAttribute("aria-label", L["feed_" + kind]);
			input.addEventListener("focus", () => input.select());
			row.appendChild(el("span", L["feed_" + kind], "text-muted small mr-2 text-nowrap"));
			row.appendChild(input);
			row.appendChild(copyButton(input));
			addresses.appendChild(row);
		});
		const actions = $("wsp-feed-actions");
		actions.textContent = "";
		const refresh = feedAction("refresh_feed", L.feed_refresh);
		refresh.disabled = feed.active;
		actions.appendChild(refresh);
		actions.appendChild(feedAction("new_feed_address", L.feed_rotate, L.feed_rotate_confirm));
		actions.appendChild(feedAction("delete_feed", L.feed_delete, L.feed_delete_confirm));
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
		const kind = format();
		const options = { markup_percent: $("wsp-cat-markup").value, prices: $("wsp-cat-prices").value };
		if (kind === "pdf") {
			options.layout = $("wsp-cat-layout").value;
			if ($("wsp-cat-quality").value !== "standard") options.quality = $("wsp-cat-quality").value;
			if ($("wsp-cat-order-form").checked) options.order_form = 1;
		}
		if ($("wsp-cat-language").value) options.language = $("wsp-cat-language").value;
		const request =
			kind === "feed"
				? call("save_feed", { picked: JSON.stringify(selection()), options: JSON.stringify(options) }, "POST", FEED_API)
				: call("create_catalogue", { title: $("wsp-cat-title").value, picked: JSON.stringify(selection()), options: JSON.stringify(options), format: kind });
		request
			.then((answer) => {
				if (!answer.ok) {
					showError(answer.field, answer.message);
					updateCreate();
					return;
				}
				if (kind !== "feed") $("wsp-cat-title").value = "";
				applyState(answer);
			})
			.catch(() => {
				setStatus(L.failed);
				updateCreate();
			});
	});

	$("wsp-cat-search").addEventListener("input", () => {
		clearTimeout(searchTimer);
		searchTimer = setTimeout(searchProducts, 250);
	});

	// --- start ----------------------------------------------------------------------------------

	FORMATS.forEach((kind) => $("wsp-cat-format").appendChild(option(kind, L["format_" + kind])));
	[
		["layout", [["grid", L.layout_grid], ["list", L.layout_list]]],
		["quality", [["standard", L.quality_standard], ["light", L.quality_light], ["print", L.quality_print]]],
	].forEach(([name, choices]) => {
		const select = $("wsp-cat-" + name);
		choices.forEach(([value, text]) => select.appendChild(option(value, text)));
	});
	$("wsp-cat-format").addEventListener("change", () => {
		applyFormat();
		updateCreate();
	});
	$("wsp-cat-prices").addEventListener("change", updateCreate);
	applyFormat();
	renderChosen();
	$("wsp-cat-count").textContent = L.count_zero;
	$("wsp-cat-rows").appendChild(el("tr", null)).appendChild(el("td", L.loading));

	Promise.all([call("get_catalogues", {}, "GET"), call("get_choices", {}, "GET")])
		.then(([next, choices]) => {
			$("wsp-cat-markup").value = next.default_markup;
			applyListingLink(choices);
			checkList($("wsp-cat-groups"), choices.groups, picked.item_groups, $("wsp-cat-filter-groups"));
			checkList($("wsp-cat-brands"), choices.brands, picked.brands, $("wsp-cat-filter-brands"));
			selectionChanged();
			applyState(next);
		})
		.catch(() => setStatus(L.failed));
})();
