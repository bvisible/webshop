//// Neoffice — added file (no upstream equivalent): the Search engines fields of Website Item,
//// Item Group and Brand — the Google result they make, and how long they are (#691 lot 6). The
//// page's own title and description come from the server (seo/page_meta.py seo_preview), so an
//// empty field shows, in grey, what the page already says.
frappe.provide("webshop.seo");

webshop.seo.preview = webshop.seo.preview || {
	defaults: {},

	key(frm) {
		return `${frm.doctype}:${frm.doc.name}`;
	},

	load(frm) {
		if (frm.is_new() || !frm.fields_dict.seo_preview) return;
		frappe.call({
			method: "webshop.webshop.seo.page_meta.seo_preview",
			args: { doctype: frm.doctype, name: frm.doc.name },
			callback: (r) => {
				this.defaults[this.key(frm)] = r.message || {};
				this.hint(frm);
				this.draw(frm);
			},
		});
	},

	// the page's own values, as the empty fields' placeholders
	hint(frm) {
		const d = this.defaults[this.key(frm)] || {};
		const pairs = [["seo_title", d.title], ["seo_description", d.description]];
		for (const [fieldname, value] of pairs) {
			const field = frm.fields_dict[fieldname];
			if (!field || !field.$input) continue;
			field.$input.attr("placeholder", value || "");
			field.$input.off("input.wspSeo").on("input.wspSeo", () => this.draw(frm));
		}
	},

	value(frm, fieldname) {
		const field = frm.fields_dict[fieldname];
		const typed = field && field.$input ? field.$input.val() : null;
		return ((typed !== null && typed !== undefined ? typed : frm.doc[fieldname]) || "").trim();
	},

	draw(frm) {
		const field = frm.fields_dict.seo_preview;
		const d = this.defaults[this.key(frm)];
		if (!field) return;
		if (!d) {
			field.$wrapper.html("");
			return;
		}
		const title_budget = d.title_budget || 60;
		const description_budget = d.description_budget || 160;
		const own_title = this.value(frm, "seo_title");
		const own_description = this.value(frm, "seo_description");
		const title = own_title || d.title || "";
		const tab = d.shop && !title.toLowerCase().includes(d.shop.toLowerCase()) ? `${title} | ${d.shop}` : title;
		const description = own_description || d.description || "";
		const own = own_title || own_description;
		field.$wrapper.html(`
			${this.result(d.url || __("No page on the site yet"), this.cut(tab, title_budget + 10), this.cut(description, description_budget))}
			<div class="small text-muted" style="margin-top: 8px; max-width: 620px;">
				${this.counters(tab, description, title_budget, description_budget)}${
					own ? "" : " · " + __("Nothing written: this is what the page says on its own")
				}
			</div>
			${frm.perm && frm.perm[0] && frm.perm[0].write ? `<button type="button" class="btn btn-xs btn-default wsp-seo-suggest" style="margin-top: 8px;">${__("Propose with Nora")}</button>` : ""}`);
		field.$wrapper.find(".wsp-seo-suggest").on("click", () => this.suggest(frm));
	},

	cut(text, budget) {
		return text.length > budget ? text.slice(0, budget - 1).trimEnd() + "…" : text;
	},

	counters(title, description, title_budget, description_budget) {
		const count = (text, budget) =>
			`<span class="${text.length > budget ? "text-danger" : "text-muted"}">${text.length} / ${budget}</span>`;
		return `${__("Title")} ${count(title, title_budget)} · ${__("Description")} ${count(description, description_budget)}`;
	},

	// A result as Google's page draws it: its white and its colours whatever the desk's theme — the
	// dark theme turned the blue title unreadable
	result(url, title, description) {
		const esc = frappe.utils.escape_html;
		return `
			<div class="wsp-seo-preview" style="max-width: 620px; padding: 12px 14px; border: 1px solid #dadce0; border-radius: 8px; background: #fff; font-family: arial, sans-serif;">
				<div style="font-size: 12px; color: #202124; word-break: break-all;">${esc(url)}</div>
				<div style="font-size: 18px; line-height: 1.35; margin-top: 2px; color: #1a0dab;">${esc(title)}</div>
				<div style="font-size: 13px; line-height: 1.5; margin-top: 4px; color: #4d5156;">${esc(description)}</div>
			</div>`;
	},

	// Nora proposes, the merchant decides: nothing reaches the fields unless asked, and the
	// document then remembers that its words were written with AI assistance
	suggest(frm) {
		frappe.call({
			method: "webshop.webshop.seo.suggestions.suggest",
			args: { doctype: frm.doctype, name: frm.doc.name },
			freeze: true,
			freeze_message: __("Nora is writing…"),
			callback: (r) => {
				const proposal = r.message;
				if (!proposal) return;
				const d = this.defaults[this.key(frm)] || {};
				const title_budget = d.title_budget || 60;
				const description_budget = d.description_budget || 160;
				// shown and counted as the page will print it, the shop's name included: the proposal
				// alone fitted here and overflowed on the page
				const page_title = proposal.page_title || proposal.title;
				const dialog = new frappe.ui.Dialog({
					title: __("Nora's proposal"),
					fields: [
						{
							fieldtype: "HTML",
							fieldname: "proposal",
							options: `
								${this.result(d.url || "", this.cut(page_title, title_budget + 10), this.cut(proposal.description, description_budget))}
								<div class="small text-muted" style="margin-top: 8px;">${this.counters(page_title, proposal.description, title_budget, description_budget)}</div>
								<p class="small text-muted" style="margin-top: 12px;">${__("Nora only uses what the page says: check every word before saving.")}</p>`,
						},
					],
					primary_action_label: __("Use this proposal"),
					primary_action: () => {
						frm.set_value("seo_title", proposal.title);
						frm.set_value("seo_description", proposal.description);
						frm.set_value("seo_ai_assisted", 1);
						frm.set_value("seo_ai_assisted_on", frappe.datetime.now_datetime());
						dialog.hide();
						frappe.show_alert({ message: __("The fields are filled: read them, then save."), indicator: "blue" });
						this.draw(frm);
					},
				});
				dialog.show();
			},
		});
	},
};

// The product page's description: Nora proposes, the merchant decides, and the document remembers
// that its words were written with AI assistance (description_ai_assisted, #691 lot 6). A product the page says too little
// about gets no proposal: the server refuses rather than let a model invent.
webshop.seo.description = webshop.seo.description || {
	draw(frm) {
		const field = frm.fields_dict.web_long_description;
		if (!field || frm.is_new() || !(frm.perm && frm.perm[0] && frm.perm[0].write)) return;
		field.$wrapper.find(".wsp-describe").remove();
		$(`<button type="button" class="btn btn-xs btn-default wsp-describe" style="margin-top: 8px;">${__("Propose a description with Nora")}</button>`)
			.appendTo(field.$wrapper)
			.on("click", () => this.suggest(frm));
	},

	suggest(frm) {
		frappe.call({
			method: "webshop.webshop.seo.suggestions.describe",
			args: { name: frm.doc.name },
			freeze: true,
			freeze_message: __("Nora is writing…"),
			callback: (r) => {
				const proposal = r.message;
				if (!proposal) return;
				// the server sends escaped paragraphs in <p>: nothing else reaches the dialog
				const current = (frm.doc.web_long_description || "").replace(/<[^>]*>/g, "").trim();
				const dialog = new frappe.ui.Dialog({
					title: __("Nora's description"),
					fields: [
						{
							fieldtype: "HTML",
							fieldname: "proposal",
							options: `
								<div class="wsp-describe-proposal" style="max-width: 620px;">${proposal.html}</div>
								<div class="small text-muted" style="margin-top: 8px;">${__("{0} words", [proposal.words])}</div>
								${current ? `<p class="small text-warning" style="margin-top: 8px;">${__("It replaces the current description.")}</p>` : ""}
								<p class="small text-muted" style="margin-top: 12px;">${__("Nora only uses what the page says: check every word before saving.")}</p>`,
						},
					],
					primary_action_label: __("Use this description"),
					primary_action: () => {
						frm.set_value("web_long_description", proposal.html);
						// the feed declares it to Google Shopping (seo/feeds/google.py structured_description)
						frm.set_value("description_ai_assisted", 1);
						dialog.hide();
						frappe.show_alert({ message: __("The fields are filled: read them, then save."), indicator: "blue" });
					},
				});
				dialog.show();
			},
		});
	},
};

// What the pictures show, for those who cannot see them (#691 D-11, seo/alt_text.py): a model that
// sees each picture proposes a sentence, the merchant reads, corrects and keeps. The proposals come
// one by one from a background job (realtime), since the first call wakes the model up.
webshop.seo.pictures = webshop.seo.pictures || {
	REASONS: {
		no_vision_model: () => __("No model that sees pictures is available on this site."),
		image_unreadable: () => __("This picture could not be read."),
		model_failed: () => __("The description failed: try again later."),
	},

	draw(frm) {
		const field = frm.fields_dict.website_image;
		if (!field || frm.is_new() || !(frm.perm && frm.perm[0] && frm.perm[0].write)) return;
		if (!frm.doc.website_image && !frm.doc.slideshow) return;
		const show = () => {
			field.$wrapper.find(".wsp-alt-suggest").remove();
			$(`<button type="button" class="btn btn-xs btn-default wsp-alt-suggest" style="margin-top: 8px;">${__("Describe the pictures with Nora")}</button>`)
				.appendTo(field.$wrapper)
				.on("click", () => this.suggest(frm));
		};
		// asked once per session: whether this site has a model that sees at all
		if (webshop.seo.pictures.available === undefined) {
			frappe.call({ method: "webshop.webshop.seo.alt_text.available", callback: (r) => {
				webshop.seo.pictures.available = !!r.message;
				if (webshop.seo.pictures.available) show();
			} });
		} else if (webshop.seo.pictures.available) {
			show();
		}
	},

	suggest(frm) {
		if (frm.is_dirty()) {
			frappe.msgprint(__("Save the item first: the descriptions are written to the saved item."));
			return;
		}
		frappe.call({
			method: "webshop.webshop.seo.alt_text.propose",
			args: { name: frm.doc.name },
			callback: (r) => r.message && this.dialog(frm, r.message),
		});
	},

	dialog(frm, answer) {
		const escape = frappe.utils.escape_html;
		const rows = answer.pictures.map((picture, index) => `
			<div class="wsp-alt-row" data-index="${index}" style="display: flex; gap: 12px; align-items: flex-start; margin-bottom: 14px;">
				<img src="${escape(picture.image)}" alt="" style="width: 96px; height: 96px; object-fit: cover; border-radius: 6px; flex: none;">
				<div style="flex: 1;">
					<textarea class="form-control wsp-alt-text" rows="2" disabled placeholder="${escape(picture.alt || "")}"></textarea>
					<div class="small text-muted wsp-alt-status" style="margin-top: 4px;">${__("Nora is looking at the picture…")}</div>
				</div>
			</div>`).join("");
		const dialog = new frappe.ui.Dialog({
			title: __("Nora's picture descriptions"),
			size: "large",
			fields: [{
				fieldtype: "HTML",
				fieldname: "list",
				options: `${rows}<p class="small text-muted">${__("Each sentence is read aloud to those who cannot see the picture: check it against the picture before keeping it. An empty box keeps the current description.")}</p>`,
			}],
			primary_action_label: __("Use these descriptions"),
			primary_action: () => {
				const descriptions = {};
				dialog.$wrapper.find(".wsp-alt-row").each((_i, row) => {
					const text = $(row).find(".wsp-alt-text").val().trim();
					if (text) descriptions[answer.pictures[$(row).data("index")].image] = text;
				});
				if (!Object.keys(descriptions).length) { dialog.hide(); return; }
				frappe.call({
					method: "webshop.webshop.seo.alt_text.save",
					args: { name: frm.doc.name, descriptions },
					freeze: true,
					callback: (r) => {
						dialog.hide();
						frm.reload_doc();
						frappe.show_alert({ message: __("{0} descriptions kept.", [(r.message && r.message.kept) || 0]), indicator: "green" });
					},
				});
			},
		});
		const handler = (data) => {
			if (!data || data.name !== frm.doc.name) return;
			const reason = data.reason && (this.REASONS[data.reason] || this.REASONS.model_failed)();
			if (data.image) {
				const index = answer.pictures.findIndex((picture) => picture.image === data.image);
				const row = dialog.$wrapper.find(`.wsp-alt-row[data-index="${index}"]`);
				row.find(".wsp-alt-status").text(reason || "");
				if (data.alt) row.find(".wsp-alt-text").val(data.alt);
				row.find(".wsp-alt-text").prop("disabled", false);
			}
			if (data.done) {
				dialog.$wrapper.find(".wsp-alt-text").prop("disabled", false);
				dialog.$wrapper.find(".wsp-alt-status").each((_i, status) => {
					if ($(status).text() === __("Nora is looking at the picture…")) $(status).text(reason || "");
				});
			}
		};
		frappe.realtime.on(answer.event, handler);
		dialog.onhide = () => frappe.realtime.off(answer.event, handler);
		dialog.show();
	},
};

// The product's SEO score (#691 plan note 20, seo/score.py): out of 100, what search engines, Google
// Shopping and assistants read of it, and what to do about the rest. It is computed in a background
// job, because it prices the product as a visitor sees it, which a web request may not do: the form
// draws the stored checklist at once, then redraws it when the job's answer reaches the document's
// room. The headline figure is drawn from the document on every refresh, never from a late callback
// (a dashboard indicator added by a callback dies at the next redraw).
webshop.seo.score = webshop.seo.score || {
	EVENT: "webshop_seo_score",

	colour(score) {
		return score >= 80 ? "green" : score >= 50 ? "orange" : "red";
	},

	load(frm) {
		if (frm.is_new() || !frm.fields_dict.seo_score_html) return;
		if (frm.doc.seo_score_checked_on) this.indicator(frm, frm.doc.seo_score);
		this.fetch(frm, 1);
		this.listen();
	},

	fetch(frm, refresh) {
		frappe.call({
			method: "webshop.webshop.seo.score.checklist",
			args: { name: frm.doc.name, refresh },
			callback: (r) => r.message && this.draw(frm, r.message, refresh),
		});
	},

	// one listener for every form: the answer names its item, and only the form open on it redraws
	listen() {
		if (this.listening) return;
		this.listening = true;
		frappe.realtime.on(this.EVENT, (data) => {
			const frm = window.cur_frm;
			if (!data || !frm || frm.doctype !== "Website Item" || frm.doc.name !== data.name) return;
			this.fetch(frm, 0);
		});
	},

	indicator(frm, score) {
		if (score === null || score === undefined) return;
		const label = __("SEO score: {0} / 100", [score]);
		const existing = frm.dashboard.stats_area_row && frm.dashboard.stats_area_row.find(".wsp-seo-indicator");
		if (existing && existing.length) {
			existing.removeClass("red orange green").addClass(this.colour(score)).text(label);
			return;
		}
		const column = frm.dashboard.add_indicator(label, this.colour(score));
		column.find(".indicator").addClass("wsp-seo-indicator").css("cursor", "pointer")
			.on("click", () => frm.scroll_to_field("seo_score_html"));
	},

	status(status) {
		const pills = {
			good: ["green", __("Good")],
			improve: ["orange", __("To improve")],
			missing: ["red", __("Missing")],
			not_applicable: ["gray", __("Not counted")],
		};
		const [colour, label] = pills[status] || pills.not_applicable;
		return `<span class="indicator-pill ${colour}" style="white-space: nowrap;">${label}</span>`;
	},

	gauge(score) {
		const radius = 26;
		const circle = 2 * Math.PI * radius;
		const filled = (circle * score) / 100;
		return `
			<svg width="64" height="64" viewBox="0 0 64 64" role="img" aria-label="${__("SEO score: {0} / 100", [score])}" style="flex: none;">
				<circle cx="32" cy="32" r="${radius}" fill="none" stroke="var(--gray-300)" stroke-width="6"></circle>
				<circle cx="32" cy="32" r="${radius}" fill="none" stroke="var(--${this.colour(score)}-500)" stroke-width="6"
					stroke-linecap="round" stroke-dasharray="${filled} ${circle}" transform="rotate(-90 32 32)"></circle>
				<text x="32" y="38" text-anchor="middle" font-size="17" font-weight="600" fill="var(--text-color)">${score}</text>
			</svg>`;
	},

	draw(frm, data, refreshing) {
		const field = frm.fields_dict.seo_score_html;
		// an answer for another item (the form moved on while it was computed) draws nothing
		if (!field || data.name !== frm.doc.name) return;
		const esc = frappe.utils.escape_html;
		if (data.score === null || data.score === undefined) {
			field.$wrapper.html(`<div class="small text-muted">${
				refreshing ? __("Computing the SEO score…") : __("No SEO score yet: it is computed after each save and every night.")
			}</div>`);
			return;
		}
		this.indicator(frm, data.score);
		const can_fix = (code) => Boolean(this.FIXES[code]);
		const rows = data.criteria.map((criterion) => `
			<tr>
				<td style="width: 110px; vertical-align: top;">${this.status(criterion.status)}</td>
				<td style="vertical-align: top;">
					<div style="font-weight: 500;">${esc(criterion.label)}</div>
					<div class="small text-muted">${esc(criterion.message || "")}</div>
				</td>
				<td class="small text-muted text-right" style="white-space: nowrap; vertical-align: top;">${
					criterion.status === "not_applicable" ? "" : `${Math.round(criterion.earned * 10) / 10} / ${criterion.points}`
				}</td>
				<td class="text-right" style="width: 90px; vertical-align: top;">${
					["improve", "missing"].includes(criterion.status) && can_fix(criterion.code)
						? `<button type="button" class="btn btn-xs btn-default wsp-seo-fix" data-code="${esc(criterion.code)}">${__("Fix this")}</button>`
						: ""
				}</td>
			</tr>`).join("");
		const informative = (data.informative || []).map((row) => `
			<tr>
				<td style="vertical-align: top;"><span class="indicator-pill gray" style="white-space: nowrap;">${__("For information")}</span></td>
				<td colspan="3" style="vertical-align: top;">
					<div style="font-weight: 500;">${esc(row.label)}</div>
					<div class="small text-muted">${esc(row.message || "")}</div>
				</td>
			</tr>`).join("");
		const checked = data.checked_on ? __("Computed {0}", [frappe.datetime.prettyDate(data.checked_on)]) : "";
		field.$wrapper.html(`
			<div class="wsp-seo-score" style="max-width: 820px; margin-bottom: 16px;">
				<div style="display: flex; gap: 16px; align-items: center; margin-bottom: 12px;">
					${this.gauge(data.score)}
					<div>
						<div style="font-size: var(--text-lg); font-weight: 600;">${__("SEO score")}</div>
						<div class="small text-muted">${esc(checked)}${refreshing ? " · " + __("updating…") : ""}</div>
						<div class="small text-muted">${__("What search engines, Google Shopping and AI assistants read of this product. Only you see it.")}</div>
					</div>
				</div>
				<table class="table table-sm" style="margin: 0;">${rows}${informative}</table>
			</div>`);
		field.$wrapper.find(".wsp-seo-fix").on("click", (event) => {
			const fix = this.FIXES[$(event.currentTarget).data("code")];
			if (fix) fix(frm);
		});
	},

	// Where each criterion is fixed: a field of this form, Nora's proposal, or the record that holds it
	FIXES: {
		title: (frm) => frm.scroll_to_field("seo_title"),
		search_description: (frm) => frm.scroll_to_field("seo_description"),
		long_description: (frm) => frm.scroll_to_field("web_long_description"),
		pictures: (frm) => frm.scroll_to_field("slideshow"),
		alt_text: (frm) =>
			webshop.seo.pictures.available ? webshop.seo.pictures.suggest(frm) : frm.scroll_to_field("slideshow"),
		identifier: (frm) => {
			frappe.route_hooks.after_load = (item) => item.scroll_to_field("barcodes");
			frappe.set_route("Form", "Item", frm.doc.item_code);
		},
		brand: (frm) => frm.scroll_to_field("brand"),
		google_category: (frm) => {
			if (!frm.doc.item_group) return;
			frappe.route_hooks.after_load = (group) => group.scroll_to_field("google_product_category");
			frappe.set_route("Form", "Item Group", frm.doc.item_group);
		},
		specifications: (frm) => frm.scroll_to_field("website_specifications"),
		offer: (frm) => frappe.set_route("List", "Item Price", { item_code: frm.doc.item_code }),
		sent_to_google: (frm) =>
			frappe.set_route("query-report", "Catalogue Ready for Google", { website_item: frm.doc.name }),
	},
};

if (!webshop.seo.preview.registered) {
	webshop.seo.preview.registered = true;
	for (const doctype of ["Website Item", "Item Group", "Brand"]) {
		frappe.ui.form.on(doctype, {
			refresh(frm) {
				webshop.seo.preview.load(frm);
				if (frm.doctype === "Website Item") {
					webshop.seo.description.draw(frm);
					webshop.seo.pictures.draw(frm);
					webshop.seo.score.load(frm);
				}
			},
			seo_title(frm) {
				webshop.seo.preview.draw(frm);
			},
			seo_description(frm) {
				webshop.seo.preview.draw(frm);
			},
		});
	}
}
