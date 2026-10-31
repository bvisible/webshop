// //// Neoffice — added file (no upstream equivalent). The buttons of a partner API access: what staff decide.
frappe.ui.form.on("Partner API Access", {
	refresh(frm) {
		if (frm.is_new()) return;
		const call = (method, args) =>
			frappe.call({
				method: "webshop.webshop.partner_api.access." + method,
				args: Object.assign({ customer: frm.doc.customer }, args || {}),
				freeze: true,
				callback: () => frm.reload_doc(),
			});

		if (["Requested", "Refused"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Approve"), () => {
				const dialog = new frappe.ui.Dialog({
					title: __("Approve this access"),
					fields: [
						{ fieldtype: "Check", fieldname: "scope_orders", label: __("May place and read orders"), default: frm.doc.wants_orders ? 1 : 0 },
						{ fieldtype: "Check", fieldname: "submit_orders", label: __("Submit orders at once (otherwise drafts)"), depends_on: "scope_orders", default: 0 },
						{ fieldtype: "Int", fieldname: "calls_per_minute", label: __("Calls per minute"), default: 60, reqd: 1 },
						{ fieldtype: "Small Text", fieldname: "note", label: __("Note to the reseller") },
					],
					primary_action_label: __("Approve"),
					primary_action(values) {
						dialog.hide();
						call("approve", values);
					},
				});
				dialog.show();
			}, __("Decision"));
			if (frm.doc.status === "Requested") {
				frm.add_custom_button(__("Refuse"), () => {
					frappe.prompt({ fieldtype: "Small Text", fieldname: "note", label: __("Reason, shown to the reseller") }, (values) => call("refuse", values), __("Refuse this request"));
				}, __("Decision"));
			}
		}
		if (frm.doc.status === "Active") {
			frm.add_custom_button(__("Suspend"), () => {
				frappe.prompt({ fieldtype: "Small Text", fieldname: "note", label: __("Reason, shown to the reseller") }, (values) => call("suspend", values), __("Suspend this access: the key stops working at once"));
			}, __("Decision"));
		}
		if (frm.doc.status === "Suspended") {
			frm.add_custom_button(__("Resume"), () => call("resume"), __("Decision"));
		}
	},
});
