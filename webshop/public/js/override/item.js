frappe.ui.form.on("Item", {
    refresh: function(frm) {
		if (!frm.doc.__islocal) {
			if (!frm.doc.published_in_website) {
				frm.add_custom_button(__("Publish in Website"), function() {
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
				}, __('Actions'));
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
