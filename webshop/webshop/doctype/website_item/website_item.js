// Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on('Website Item', {
	onload: (frm) => {
		// should never check Private
		frm.fields_dict["website_image"].df.is_private = 0;
	},

	refresh: (frm) => {
		frm.add_custom_button(__("Prices"), function() {
			frappe.set_route("List", "Item Price", {"item_code": frm.doc.item_code});
		}, __("View"));

		frm.add_custom_button(__("Stock"), function() {
			frappe.route_options = {
				"item_code": frm.doc.item_code
			};
			frappe.set_route("query-report", "Stock Balance");
		}, __("View"));

		frm.add_custom_button(__("Webshop Settings"), function() {
			frappe.set_route("Form", "Webshop Settings");
		}, __("View"));

		//// Neoffice — what Google Shopping gets of this product, and what would make its listing
		//// better: the report Catalogue Ready for Google, on this item (#691 lot 6)
		if (!frm.is_new()) {
			frm.add_custom_button(__("Google Shopping"), function() {
				frappe.set_route("query-report", "Catalogue Ready for Google", { website_item: frm.doc.name });
			}, __("View"));
		}
	},

	copy_from_item_group: (frm) => {
		return frm.call({
			doc: frm.doc,
			method: "copy_specification_from_item_group"
		});
	},

	set_meta_tags: (frm) => {
		frappe.utils.set_meta_tag(frm.doc.route);
	}
});
