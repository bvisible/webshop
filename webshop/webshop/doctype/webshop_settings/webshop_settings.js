// Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Webshop Settings", {
	onload: function(frm) {
		if(frm.doc.__onload && frm.doc.__onload.quotation_series) {
			frm.fields_dict.quotation_series.df.options = frm.doc.__onload.quotation_series;
			frm.refresh_field("quotation_series");
		}

		frm.set_query('payment_gateway_account', function() {
			return { 'filters': { 
				'payment_channel': ['in', ["Email", "Phone"]] 
			 } };
		});
	},
	refresh: function(frm) {
		if (frm.doc.enabled) {
			frm.get_field('store_page_docs').$wrapper.removeClass('hide-control').html(
				`<div>${__("Follow these steps to create a landing page for your store")}:
					<a href="https://docs.erpnext.com/docs/user/manual/en/website/store-landing-page"
						style="color: var(--gray-600)">
						docs/store-landing-page
					</a>
				</div>`
			);
		}

		// Add sitemap view button
		frm.add_custom_button(__('View Sitemap'), function() {
			window.open('/sitemap_index.xml', '_blank');
		}, __('Sitemap'));
		
		// Update sitemap info with actual domain
		if (frm.fields_dict.sitemap_info) {
			const domain = window.location.origin;
			frm.set_df_property('sitemap_info', 'options', 
				`<p>The sitemap is automatically generated and cached for 6 hours. You can access it at:</p>
				<ul>
					<li><a href="${domain}/sitemap_index.xml" target="_blank">${domain}/sitemap_index.xml</a> - Main sitemap index</li>
					<li><a href="${domain}/sitemap.xml" target="_blank">${domain}/sitemap.xml</a> - All content</li>
					<li><a href="${domain}/sitemap_products.xml" target="_blank">${domain}/sitemap_products.xml</a> - Products only</li>
					<li><a href="${domain}/sitemap_categories.xml" target="_blank">${domain}/sitemap_categories.xml</a> - Categories only</li>
					<li><a href="${domain}/sitemap_brands.xml" target="_blank">${domain}/sitemap_brands.xml</a> - Brands only</li>
					<li><a href="${domain}/sitemap_blog.xml" target="_blank">${domain}/sitemap_blog.xml</a> - Blog posts only</li>
					<li><a href="${domain}/sitemap_pages.xml" target="_blank">${domain}/sitemap_pages.xml</a> - Pages only</li>
				</ul>`
			);
		}

		// Add button for calculating frequently bought together
		if (frm.doc.enable_frequently_bought_together && !frm.is_new()) {
			frm.add_custom_button(__('Calculate Frequently Bought Together'), function() {
				frappe.call({
					method: 'calculate_frequently_bought_together_items',
					doc: frm.doc,
					freeze: true,
					freeze_message: __('Calculating frequently bought together items...'),
					callback: function(r) {
						if (r.message && r.message.success) {
							frappe.msgprint(r.message.message);
						} else if (r.message && !r.message.success) {
							frappe.msgprint(r.message.message);
						}
					}
				});
			});
		}

		// Add button for importing gift cards
		if (frm.doc.enable_gift_cards && !frm.is_new()) {
			frm.add_custom_button(__('Import Gift Cards'), function() {
				// Option to download template
				const d = new frappe.ui.Dialog({
					title: __('Import Gift Cards from Excel'),
					fields: [
						{
							fieldtype: 'HTML',
							fieldname: 'instructions',
							options: `
								<p>${__('Upload an Excel file with gift card data.')}</p>
								<p>${__('Required columns: code, value')}</p>
								<p>${__('Optional columns: name, owner, client_email, valid_until')}</p>
							`
						},
						{
							fieldtype: 'Button',
							fieldname: 'download_template',
							label: __('Download Template'),
							click: function() {
								frappe.call({
									method: 'webshop.webshop.utils.import_gift_cards.get_gift_card_import_template',
									callback: function(r) {
										if (r.message) {
											const blob = new Blob([Uint8Array.from(atob(r.message.file_content), c => c.charCodeAt(0))], {
												type: r.message.type
											});
											const url = window.URL.createObjectURL(blob);
											const a = document.createElement('a');
											a.href = url;
											a.download = r.message.filename;
											document.body.appendChild(a);
											a.click();
											window.URL.revokeObjectURL(url);
											document.body.removeChild(a);
										}
									}
								});
							}
						},
						{
							fieldtype: 'Column Break'
						},
						{
							fieldtype: 'Attach',
							fieldname: 'excel_file',
							label: __('Excel File'),
							reqd: 1,
							options: {
								restrictions: {
									allowed_file_types: ['.xlsx', '.xls']
								}
							}
						},
						{
							fieldtype: 'Check',
							fieldname: 'dry_run',
							label: __('Dry Run (Validate Only)'),
							default: 1,
							description: __('Check this to validate data without creating gift cards')
						},
						{
							fieldtype: 'Link',
							fieldname: 'default_customer',
							label: __('Default Customer'),
							options: 'Customer',
							description: __('Customer to use when none is specified or found')
						},
						{
							fieldtype: 'Date',
							fieldname: 'default_validity_date',
							label: __('Default Validity Date'),
							description: __('Default expiry date (uses 2999-12-31 if not set)')
						}
					],
					primary_action_label: __('Import'),
					primary_action: function(values) {
						if (!values.excel_file) {
							frappe.msgprint(__('Please upload an Excel file'));
							return;
						}

						// Read the file
						frappe.dom.freeze(__('Processing file...'));
						
						fetch(values.excel_file)
							.then(response => response.blob())
							.then(blob => {
								const reader = new FileReader();
								reader.onload = function(e) {
									// Convert ArrayBuffer to base64
									const arrayBuffer = e.target.result;
									const bytes = new Uint8Array(arrayBuffer);
									let binary = '';
									bytes.forEach(byte => binary += String.fromCharCode(byte));
									const base64 = window.btoa(binary);
									
									frappe.call({
										method: 'webshop.webshop.utils.import_gift_cards.import_gift_cards_from_excel',
										args: {
											file_content: base64,
											dry_run: values.dry_run,
											default_customer: values.default_customer,
											default_validity_date: values.default_validity_date
										},
										callback: function(r) {
											frappe.dom.unfreeze();
											if (r.message) {
												show_import_results(r.message, values.dry_run);
											}
										},
										error: function() {
											frappe.dom.unfreeze();
										}
									});
								};
								reader.readAsArrayBuffer(blob);
							})
							.catch(error => {
								frappe.dom.unfreeze();
								frappe.msgprint(__('Error reading file: {0}', [error.message]));
							});
					}
				});
				d.show();
			}, __('Gift Cards'));

			// Helper function to show import results
			function show_import_results(results, is_dry_run) {
				let message = `<h4>${is_dry_run ? __('Validation Results') : __('Import Results')}</h4>`;
				message += `<p>${__('Total rows')}: ${results.total}</p>`;
				
				if (results.success && results.success.length > 0) {
					message += `<p style="color: green;">${__('Successful')}: ${results.success.length}</p>`;
					if (!is_dry_run) {
						message += '<details><summary>' + __('Show successful imports') + '</summary><ul>';
						results.success.forEach(item => {
							message += `<li>${__('Row')} ${item.row}: ${item.code} - ${item.amount} ${frm.doc.default_currency || 'CHF'}</li>`;
						});
						message += '</ul></details>';
					}
				}
				
				if (results.errors && results.errors.length > 0) {
					message += `<p style="color: red;">${__('Errors')}: ${results.errors.length}</p>`;
					message += '<details open><summary>' + __('Show errors') + '</summary><ul>';
					results.errors.forEach(item => {
						message += `<li style="color: red;">${__('Row')} ${item.row}: ${item.code} - ${item.error}</li>`;
					});
					message += '</ul></details>';
				}
				
				if (is_dry_run && results.errors.length === 0) {
					message += `<p style="color: green; font-weight: bold;">${__('All data is valid. You can proceed with the actual import.')}</p>`;
				}
				
				frappe.msgprint({
					title: is_dry_run ? __('Validation Complete') : __('Import Complete'),
					message: message,
					indicator: results.errors.length > 0 ? 'red' : 'green'
				});
			}
		}

		frappe.model.with_doctype("Website Item", () => {
			const web_item_meta = frappe.get_meta('Website Item');

			const valid_fields = web_item_meta.fields.filter(df =>
				["Link", "Table MultiSelect"].includes(df.fieldtype) && !df.hidden
			).map(df =>
				({ label: df.label, value: df.fieldname })
			);

			frm.get_field("filter_fields").grid.update_docfield_property(
				'fieldname', 'options', valid_fields
			);
		});
	},
	enabled: function(frm) {
		if (frm.doc.enabled === 1) {
			frm.set_value('enable_variants', 1);
		}
		else {
			frm.set_value('company', '');
			frm.set_value('price_list', '');
			frm.set_value('default_customer_group', '');
			frm.set_value('quotation_series', '');
		}
	},
	enable_checkout_page: function(frm) {
		if (frm.doc.enable_checkout_page) {
			frm.set_value('redirect_on_action', '/cart');
			frm.set_df_property('redirect_on_action', 'read_only', 1);
		} else {
			frm.set_df_property('redirect_on_action', 'read_only', 0);
		}
	},
	maintenance_website: function(frm) {
		if (!frm.doc.maintenance_website && frm.doc.maintenance_webshop) {
			frm.set_value('maintenance_webshop', 0);
			frappe.msgprint(__('Webshop maintenance mode cannot be enabled without website maintenance mode'));
		}
	},
	maintenance_webshop: function(frm) {
		if (frm.doc.maintenance_webshop && !frm.doc.maintenance_website) {
			frm.set_value('maintenance_website', 1);
			frappe.msgprint(__('Website maintenance mode has been automatically enabled'));
		}
	},
	regenerate_sitemap: function(frm) {
		frappe.confirm(
			__('This will clear the sitemap cache and force regeneration. Continue?'),
			function() {
				frm.call({
					method: 'regenerate_sitemap',
					freeze: true,
					freeze_message: __('Clearing sitemap cache...'),
					callback: function(r) {
						if (r.message) {
							frm.reload_doc();
						}
					}
				});
			}
		);
	},
	hide_variants: function(frm) {
		// Hide Variants and Enable Attribute Filters are mutually exclusive
		if (frm.doc.hide_variants && frm.doc.enable_attribute_filters && frm.doc.filter_attributes && frm.doc.filter_attributes.length > 0) {
			frm.set_value('enable_attribute_filters', 0);
			frappe.msgprint({
				title: __('Configuration Conflict'),
				message: __("'Enable Attribute Filters' has been automatically disabled. These two features are mutually exclusive: Attribute filters allow customers to filter by variant attributes (like Size, Color), which requires variants to be visible."),
				indicator: 'orange'
			});
		}
	},
	enable_attribute_filters: function(frm) {
		// Hide Variants and Enable Attribute Filters are mutually exclusive
		if (frm.doc.enable_attribute_filters && frm.doc.hide_variants) {
			frm.set_value('hide_variants', 0);
			frappe.msgprint({
				title: __('Configuration Conflict'),
				message: __("'Hide Variants' has been automatically disabled. These two features are mutually exclusive: Attribute filters allow customers to filter by variant attributes (like Size, Color), which requires variants to be visible."),
				indicator: 'orange'
			});
		}
	}
});