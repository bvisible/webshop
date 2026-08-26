frappe.listview_settings['Website Item'] = {
	add_fields: ["item_name", "web_item_name", "published", "website_image", "has_variants", "variant_of"],
	filters: [["published", "=", "1"]],

	get_indicator: function(doc) {
		if (doc.has_variants && doc.published) {
			return [__("Template"), "orange", "has_variants,=,Yes|published,=,1"];
		} else if (doc.has_variants && !doc.published) {
			return [__("Template"), "grey", "has_variants,=,Yes|published,=,0"];
		} else if (doc.variant_of  && doc.published) {
			return [__("Variant"), "blue", "published,=,1|variant_of,=," + doc.variant_of];
		} else if (doc.variant_of  && !doc.published) {
			return [__("Variant"), "grey", "published,=,0|variant_of,=," + doc.variant_of];
		} else if (doc.published) {
			return [__("Published"), "green", "published,=,1"];
		} else {
			return [__("Not Published"), "grey", "published,=,0"];
		}
	},

	//// Neoffice — multi-warehouse: bulk "add/remove a stock source" on the
	//// selected items, for the shops that pick their items by hand instead of
	//// using the source's "auto-enable when in stock" switch.
	onload: function(listview) {
		listview.page.add_actions_menu_item(__('Stock Source'), function() {
			const selected = listview.get_checked_items(true);
			if (!selected.length) {
				frappe.msgprint(__('Please select at least one Website Item'));
				return;
			}

			frappe.call({
				method: 'webshop.webshop.multi_warehouse.sources.get_configured_sources',
				callback: function(r) {
					const sources = (r.message || []);
					if (!sources.length) {
						frappe.msgprint(__('No warehouse source is configured in Webshop Settings'));
						return;
					}

					const dialog = new frappe.ui.Dialog({
						title: __('Stock Source'),
						fields: [
							{
								fieldname: 'warehouse',
								fieldtype: 'Select',
								label: __('Warehouse Source'),
								reqd: 1,
								options: sources.map(s => ({label: `${s.label} (${s.warehouse})`, value: s.warehouse})),
							},
							{
								fieldname: 'action',
								fieldtype: 'Select',
								label: __('Action'),
								reqd: 1,
								default: 'add',
								options: [
									{label: __('Show this source on the selected items'), value: 'add'},
									{label: __('Stop showing it on the selected items'), value: 'remove'},
								],
							},
							{
								fieldname: 'info',
								fieldtype: 'HTML',
								options: `<div class="text-muted small">${__('Sets the items to "Custom" mode: they display exactly the sources listed on them, ignoring the auto-enable switch.')}</div>`,
							},
						],
						primary_action_label: __('Apply'),
						primary_action(values) {
							dialog.hide();
							frappe.call({
								method: 'webshop.webshop.multi_warehouse.sources.bulk_set_item_source',
								args: {
									website_items: selected,
									warehouse: values.warehouse,
									action: values.action,
								},
								freeze: true,
								freeze_message: __('Updating stock sources...'),
								callback: function(res) {
									const count = (res.message || {}).updated || 0;
									frappe.show_alert({
										message: __('{0} item(s) updated', [count]),
										indicator: 'green',
									});
									listview.refresh();
								},
							});
						},
					});
					dialog.show();
				},
			});
		}, false);
	}
};
