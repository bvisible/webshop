//// Neoffice — added file (cross-sell offers, no upstream equivalent).
// An offer can be triggered by a whole item group or brand: the button to
// create one lives on those forms too, next to the one on Item.
["Item Group", "Brand"].forEach((doctype) => {
	frappe.ui.form.on(doctype, {
		refresh(frm) {
			if (frm.is_new()) return;
			const field = doctype === "Item Group" ? "trigger_item_group" : "trigger_brand";
			frm.add_custom_button(
				__("Cross-sell Offer"),
				() =>
					frappe.new_doc("Cross Sell Offer", {
						trigger_type: doctype,
						[field]: frm.doc.name,
						title: frm.doc.name,
					}),
				__("Webshop")
			);
		},
	});
});
