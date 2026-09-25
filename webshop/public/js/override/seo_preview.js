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

if (!webshop.seo.preview.registered) {
	webshop.seo.preview.registered = true;
	for (const doctype of ["Website Item", "Item Group", "Brand"]) {
		frappe.ui.form.on(doctype, {
			refresh(frm) {
				webshop.seo.preview.load(frm);
				if (frm.doctype === "Website Item") {
					webshop.seo.description.draw(frm);
					webshop.seo.pictures.draw(frm);
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
