//// Neoffice — added file (cross-sell offers, no upstream equivalent).
frappe.ui.form.on("Cross Sell Offer", {
	refresh(frm) {
		if (frm.doc.pricing_rule) {
			frm.add_custom_button(__("Pricing Rule"), () =>
				frappe.set_route("Form", "Pricing Rule", frm.doc.pricing_rule)
			);
		}
		if (!frm.is_new()) {
			frm.dashboard.add_indicator(
				__("{0} shown · {1} accepted", [frm.doc.impressions || 0, frm.doc.acceptances || 0]),
				frm.doc.enabled ? "blue" : "gray"
			);
		}
		frm.set_query("offer_item", () => ({ filters: { published_in_website: 1, has_variants: 0 } }));
	},
	trigger_item(frm) {
		if (frm.doc.trigger_item && !frm.doc.title) {
			frappe.db.get_value("Item", frm.doc.trigger_item, "item_name").then((r) => {
				if (r.message && !frm.doc.title) frm.set_value("title", r.message.item_name);
			});
		}
	},
});
