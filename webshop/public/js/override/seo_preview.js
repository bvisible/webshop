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
		const esc = frappe.utils.escape_html;
		const title_budget = d.title_budget || 60;
		const description_budget = d.description_budget || 160;
		const own_title = this.value(frm, "seo_title");
		const own_description = this.value(frm, "seo_description");
		const title = own_title || d.title || "";
		const tab = d.shop && !title.toLowerCase().includes(d.shop.toLowerCase()) ? `${title} | ${d.shop}` : title;
		const description = own_description || d.description || "";
		const cut = (text, budget) => (text.length > budget ? text.slice(0, budget - 1).trimEnd() + "…" : text);
		const count = (text, budget) =>
			`<span class="${text.length > budget ? "text-danger" : "text-muted"}">${text.length} / ${budget}</span>`;
		const own = own_title || own_description;
		field.$wrapper.html(`
			<div class="wsp-seo-preview" style="max-width: 620px; padding: 12px 14px; border: 1px solid var(--border-color); border-radius: var(--border-radius-md); background: var(--card-bg);">
				<div class="text-muted small">${esc(d.url || __("No page on the site yet"))}</div>
				<div style="font-size: 18px; line-height: 1.35; margin-top: 2px; color: #1a0dab;">${esc(cut(tab, title_budget + 10))}</div>
				<div class="small" style="margin-top: 4px;">${esc(cut(description, description_budget))}</div>
				<div class="small text-muted" style="margin-top: 10px;">
					${__("Title")} ${count(tab, title_budget)} · ${__("Description")} ${count(description, description_budget)}${
						own ? "" : " · " + __("Nothing written: this is what the page says on its own")
					}
				</div>
			</div>
			${frm.perm && frm.perm[0] && frm.perm[0].write ? `<button type="button" class="btn btn-xs btn-default wsp-seo-suggest" style="margin-top: 8px;">${__("Propose with Nora")}</button>` : ""}`);
		field.$wrapper.find(".wsp-seo-suggest").on("click", () => this.suggest(frm));
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
				const esc = frappe.utils.escape_html;
				const dialog = new frappe.ui.Dialog({
					title: __("Nora's proposal"),
					fields: [
						{
							fieldtype: "HTML",
							fieldname: "proposal",
							options: `
								<div style="font-size: 16px; color: #1a0dab;">${esc(proposal.title)}</div>
								<div class="small text-muted">${proposal.title.length} / 60</div>
								<div style="margin-top: 8px;">${esc(proposal.description)}</div>
								<div class="small text-muted">${proposal.description.length} / 160</div>
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

if (!webshop.seo.preview.registered) {
	webshop.seo.preview.registered = true;
	for (const doctype of ["Website Item", "Item Group", "Brand"]) {
		frappe.ui.form.on(doctype, {
			refresh(frm) {
				webshop.seo.preview.load(frm);
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
