frappe.ui.form.on("Item", {
    refresh: function(frm) {
		if (!frm.doc.__islocal) {
			if (!frm.doc.published_in_website) {
				frm.add_custom_button(__("Publish in Website"), function() {
					//// Neoffice multi-site: with several websites, ask which ones the
					//// product goes on. All checked (default) = visible everywhere,
					//// which is the untouched single-site behavior.
					frappe.call({
						method: "webshop.webshop.multi_site.get_active_website_profiles",
						callback: function(pr) {
							const profiles = pr.message || [];
							if (profiles.length < 2) {
								neo_publish_item(null);
								return;
							}
							const site_dialog = new frappe.ui.Dialog({
								title: __("Publish on which sites?"),
								fields: [{
									fieldname: "sites",
									fieldtype: "MultiCheck",
									label: __("Sites"),
									columns: 1,
									options: profiles.map(p => ({
										label: p.is_default ? `${p.title} (${__("default site")})` : p.title,
										value: p.name,
										checked: 1,
									})),
								}],
								primary_action_label: __("Publish"),
								primary_action(values) {
									const sites = values.sites || [];
									if (!sites.length) {
										frappe.msgprint(__("Select at least one site."));
										return;
									}
									site_dialog.hide();
									// every site checked = no restriction rows (base behavior)
									neo_publish_item(sites.length === profiles.length ? null : sites);
								},
							});
							site_dialog.show();
						}
					});

					function neo_publish_item(selected_sites) {
					// Get warehouses with stock
					frappe.call({
						method: "webshop.webshop.doctype.website_item.website_item.get_item_warehouses",
						args: {
							item_code: frm.doc.item_code,
						},
						callback: function(warehouse_result) {
							// Create website item
							frappe.call({
								method: "webshop.webshop.doctype.website_item.website_item.make_website_item",
								args: {
									doc: frm.doc,
								},
								freeze: true,
								freeze_message: __("Creating Website Item..."),
								callback: function(result) {
									//// Neoffice multi-site: restrict to the selected sites
									if (selected_sites && selected_sites.length) {
										frappe.call({
											method: "webshop.webshop.multi_site.set_website_item_sites",
											args: { website_item: result.message[0], sites: selected_sites },
										});
									}
									let warehouses = warehouse_result.message || [];
									let selected_warehouse = warehouses.length > 0 ? warehouses[0].warehouse : "";
									let warehouse_options = "";
									
									// Create warehouse options for the dialog
									if (warehouses.length > 0) {
										warehouse_options = "<div class='warehouse-options'>";
										warehouses.forEach(wh => {
											warehouse_options += `<div class='warehouse-option' data-warehouse='${wh.warehouse}'>
													<span>${wh.warehouse}</span>
													<span class='text-muted'>(${wh.actual_qty} ${frm.doc.stock_uom})</span>
												</div>`;
										});
										warehouse_options += "</div>";
									}
									
									// Confirmation message with warehouse information
									let message = __("The product {0} has been published on the website.", 
										[repl('<a href="/app/website-item/%(item_encoded)s" class="strong">%(item)s</a>', {
											item_encoded: encodeURIComponent(result.message[0]),
											item: result.message[1]
										})]
									);
									
									if (selected_warehouse) {
										message += `<br><br>${__("The product's warehouse is")} <strong>${selected_warehouse}</strong>`;
									}
									
									if (warehouses.length > 0) {
										message += `<br><br>${warehouse_options}`;
										
										// Add action buttons
										message += `<div class='dialog-actions' style='margin-top: 15px;display: flex;justify-content: space-between;'>
											<button class='btn btn-default btn-sm change-warehouse'>${__("Change Warehouse")}</button>
											<button class='btn btn-primary btn-sm view-item'>${__("View Product")}</button>
										</div>`;
									}
									
									let d = frappe.msgprint({
										message: message,
										title: __("Published"),
										indicator: "green",
										wide: true
									});
									
									// Add event handlers for buttons
									setTimeout(() => {
										// Button to view product
										$(d.msg_area).find('.view-item').on('click', function() {
											frappe.set_route("Form", "Website Item", result.message[0]);
											d.hide();
										});
										
										// Button to change warehouse
										$(d.msg_area).find('.change-warehouse').on('click', function() {
											d.hide();
											
											// Create a dialog to select warehouse
											let warehouse_dialog = new frappe.ui.Dialog({
												title: __("Select Warehouse"),
												fields: [{
													label: __("Warehouse"),
													fieldname: "warehouse",
													fieldtype: "Select",
													options: warehouses.map(wh => wh.warehouse),
													default: selected_warehouse
												}],
												primary_action_label: __("Update"),
												primary_action: function() {
													let new_warehouse = warehouse_dialog.get_values().warehouse;
													
													// Update the warehouse of the product
													frappe.call({
														method: "frappe.client.set_value",
														args: {
															doctype: "Website Item",
															name: result.message[0],
															fieldname: "website_warehouse",
															value: new_warehouse
														},
														callback: function() {
															frappe.show_alert({
																message: __("Warehouse updated successfully"),
																indicator: "green"
															});
															warehouse_dialog.hide();
														}
													});
												}
											});
											
											warehouse_dialog.show();
										});
										
										// Event handler for warehouse options
										$(d.msg_area).find('.warehouse-option').on('click', function() {
											let warehouse = $(this).data('warehouse');
											
											// Update the warehouse of the product
											frappe.call({
												method: "frappe.client.set_value",
												args: {
													doctype: "Website Item",
													name: result.message[0],
													fieldname: "website_warehouse",
													value: warehouse
												},
												callback: function() {
													frappe.show_alert({
														message: __("Warehouse updated successfully"),
														indicator: "green"
													});
												}
											});
										});
									}, 100);
								}
							});
						}
					});
					}
				});
			} else {
				frm.add_custom_button(__("View Website Item"), function() {
					frappe.db.get_value("Website Item", {item_code: frm.doc.name}, "name", (d) => {
						if (!d.name) frappe.throw(__("Website Item not found"));
						frappe.set_route("Form", "Website Item", d.name);
					});
				});
			}
		}
	}
});

//// Neoffice — second-hand: one button turns a new item into a used unit. A
//// used unit is its own Item (own condition, own photos, own price, a
//// quantity of one), linked to the new item through `condition_of_item`.
//// Server side: webshop.webshop.utils.used_items.create_used_unit.
frappe.ui.form.on("Item", {
	refresh(frm) {
		if (frm.doc.__islocal) return;
		const condition = frm.doc.item_condition || "New";
		if (condition !== "New") {
			if (frm.doc.condition_of_item) {
				frm.dashboard.add_indicator(
					__("Used unit of {0}", [frm.doc.condition_of_item]),
					"orange"
				);
			}
			return;
		}
		if (frm.doc.has_variants) return;
		frm.add_custom_button(
			__("Create Used Unit"),
			() => webshop_used_unit_dialog(frm),
			__("Webshop")
		);
		//// Neoffice — cross-sell: an offer whose trigger is this item
		frm.add_custom_button(
			__("Cross-sell Offer"),
			() => frappe.new_doc("Cross Sell Offer", { trigger_type: "Item", trigger_item: frm.doc.name, title: frm.doc.item_name }),
			__("Webshop")
		);
		frappe.db
			.count("Item", { filters: { condition_of_item: frm.doc.name } })
			.then((n) => {
				if (n) frm.dashboard.add_indicator(__("{0} used units", [n]), "orange");
			});
	},
});

function webshop_used_unit_dialog(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Create Used Unit"),
		fields: [
			{
				fieldname: "condition",
				fieldtype: "Select",
				label: __("Condition"),
				options: "Second-hand\nRefurbished",
				default: "Second-hand",
				reqd: 1,
			},
			{
				fieldname: "grade",
				fieldtype: "Select",
				label: __("Condition Grade"),
				options: "\nLike New\nVery Good\nGood\nFair",
			},
			{
				fieldname: "details",
				fieldtype: "Small Text",
				label: __("Condition Details"),
				description: __(
					"Signs of use, missing accessories, replaced parts. Shown to the customer."
				),
			},
			{ fieldname: "col_1", fieldtype: "Column Break" },
			{ fieldname: "price", fieldtype: "Currency", label: __("Selling price"), reqd: 1 },
			{
				fieldname: "cost",
				fieldtype: "Currency",
				label: __("Cost"),
				default: 0,
				description: __("What the unit cost you; its valuation in stock."),
			},
			{ fieldname: "qty", fieldtype: "Float", label: __("Quantity"), default: 1 },
			{ fieldname: "warranty_days", fieldtype: "Int", label: __("Warranty (days)"), default: 365 },
			{
				fieldname: "warehouse",
				fieldtype: "Link",
				options: "Warehouse",
				label: __("Warehouse"),
				description: __("Empty: the warehouse the shop sells from."),
				get_query: () => ({ filters: { is_group: 0 } }),
			},
			{ fieldname: "publish", fieldtype: "Check", label: __("Publish on the website"), default: 1 },
		],
		primary_action_label: __("Create"),
		primary_action(values) {
			d.hide();
			frappe.call({
				method: "webshop.webshop.utils.used_items.create_used_unit",
				args: Object.assign({ item_code: frm.doc.name }, values),
				freeze: true,
				freeze_message: __("Creating the used unit..."),
				callback(r) {
					const unit = r.message;
					if (!unit) return;
					let message = __("Used unit of {0}", [frm.doc.name]) + ": ";
					message += `<a href="/app/item/${encodeURIComponent(unit.item_code)}"><b>${frappe.utils.escape_html(unit.item_code)}</b></a>`;
					if (unit.route) {
						message += ` · <a href="/${unit.route}" target="_blank">${__("See it in the shop")}</a>`;
					}
					message += `<br><br>${__("Upload this unit's own photos before selling it.")}`;
					frappe.msgprint({ title: __("Used unit created"), message, indicator: "green" });
					frm.reload_doc();
				},
			});
		},
	});
	frappe.db
		.get_value("Item Price", { item_code: frm.doc.name, selling: 1 }, "price_list_rate")
		.then((r) => {
			if (r.message && r.message.price_list_rate) d.set_value("price", r.message.price_list_rate);
		});
	d.show();
}
