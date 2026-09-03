//// Neoffice — added file (purchase follow-ups, no upstream equivalent).
frappe.ui.form.on("Purchase Follow-up", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.dashboard.add_indicator(
			__("{0} enrolled · {1} emails sent", [frm.doc.enrolled || 0, frm.doc.sent || 0]),
			frm.doc.enabled ? "blue" : "gray"
		);
		frm.add_custom_button(__("Entries"), () =>
			frappe.set_route("List", "Purchase Follow-up Entry", { flow: frm.doc.name })
		);
	},
});
