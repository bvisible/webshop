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
		// Initialize Category Order Tree
		render_category_order_tree(frm);
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

// Category Order Tree Functions
function render_category_order_tree(frm) {
	const wrapper = frm.fields_dict.category_order_html.$wrapper;
	wrapper.empty();

	// Create container
	const container = $(`
		<div class="category-order-container">
			<div class="category-order-toolbar mb-3">
				<button class="btn btn-primary btn-sm btn-save-order" disabled>
					<i class="fa fa-save"></i> ${__('Save Order')}
				</button>
				<button class="btn btn-default btn-sm btn-refresh-tree ml-2">
					<i class="fa fa-refresh"></i> ${__('Refresh')}
				</button>
				<span class="ml-3 text-muted category-order-help">
					${__('Drag and drop categories to reorder. Higher weightage = displayed first.')}
				</span>
			</div>
			<div class="category-tree-wrapper" style="border: 1px solid var(--border-color); border-radius: 4px; padding: 10px; min-height: 100px; background: var(--fg-color);">
				<div class="category-tree-loading text-center text-muted py-4">
					<i class="fa fa-spinner fa-spin"></i> ${__('Loading categories...')}
				</div>
				<div class="category-tree"></div>
			</div>
		</div>
		<style>
			.category-order-container .category-tree-item {
				padding: 8px 12px;
				margin: 4px 0;
				background: var(--bg-color);
				border: 1px solid var(--border-color);
				border-radius: 4px;
				cursor: move;
				display: flex;
				align-items: center;
				justify-content: space-between;
			}
			.category-order-container .category-tree-item:hover {
				background: var(--hover-bg);
			}
			.category-order-container .category-tree-item.dragging {
				opacity: 0.5;
				border: 2px dashed var(--primary);
			}
			.category-order-container .category-tree-item .item-label {
				flex: 1;
				font-weight: 500;
			}
			.category-order-container .category-tree-item .item-weightage {
				width: 60px;
				text-align: center;
				padding: 2px 6px;
				border: 1px solid var(--border-color);
				border-radius: 3px;
				font-size: 12px;
			}
			.category-order-container .category-tree-item .drag-handle {
				cursor: move;
				color: var(--text-muted);
				margin-right: 10px;
			}
			.category-order-container .category-children {
				margin-left: 25px;
				border-left: 2px solid var(--border-color);
				padding-left: 10px;
			}
			.category-order-container .category-tree-item.is-group .item-label::before {
				content: '📁 ';
			}
			.category-order-container .category-tree-item:not(.is-group) .item-label::before {
				content: '📄 ';
			}
			.category-order-container .drop-zone {
				min-height: 10px;
				transition: all 0.2s;
			}
			.category-order-container .drop-zone.drag-over {
				background: var(--primary-light);
				min-height: 40px;
				border: 2px dashed var(--primary);
				border-radius: 4px;
			}
		</style>
	`);

	wrapper.append(container);

	// Load the tree
	load_category_tree(wrapper);

	// Bind events
	wrapper.find('.btn-refresh-tree').on('click', function() {
		load_category_tree(wrapper);
	});

	wrapper.find('.btn-save-order').on('click', function() {
		save_category_order(wrapper);
	});
}

function load_category_tree(wrapper) {
	const tree_container = wrapper.find('.category-tree');
	const loading = wrapper.find('.category-tree-loading');

	tree_container.empty();
	loading.show();

	frappe.call({
		method: 'webshop.webshop.doctype.webshop_settings.webshop_settings.get_category_tree',
		callback: function(r) {
			loading.hide();
			if (r.message && r.message.length) {
				render_tree_nodes(tree_container, r.message, 0);
				init_drag_and_drop(wrapper);
			} else {
				tree_container.html(`
					<div class="text-center text-muted py-4">
						${__('No categories found. Make sure Item Groups have "Show in Website" enabled.')}
					</div>
				`);
			}
		},
		error: function() {
			loading.hide();
			tree_container.html(`
				<div class="text-center text-danger py-4">
					${__('Error loading categories')}
				</div>
			`);
		}
	});
}

function render_tree_nodes(container, nodes, level) {
	nodes.forEach((node, index) => {
		// Calculate weightage based on position (higher position = higher weightage)
		const baseWeightage = (nodes.length - index) * 10;

		const item = $(`
			<div class="category-tree-item ${node.is_group ? 'is-group' : ''}"
				 data-name="${node.name}"
				 data-level="${level}"
				 data-weightage="${node.weightage || baseWeightage}"
				 draggable="true">
				<span class="drag-handle">☰</span>
				<span class="item-label">${node.label}</span>
				<input type="number" class="item-weightage" value="${node.weightage || baseWeightage}"
					   title="${__('Weightage - higher values appear first')}" />
			</div>
		`);

		container.append(item);

		// Render children if any
		if (node.children && node.children.length > 0) {
			const children_container = $('<div class="category-children"></div>');
			container.append(children_container);
			render_tree_nodes(children_container, node.children, level + 1);
		}
	});
}

function init_drag_and_drop(wrapper) {
	const items = wrapper.find('.category-tree-item');

	items.each(function() {
		const item = $(this);

		item.on('dragstart', function(e) {
			e.originalEvent.dataTransfer.setData('text/plain', item.data('name'));
			item.addClass('dragging');
			wrapper.find('.category-tree-item').not(item).addClass('drop-zone');
		});

		item.on('dragend', function(e) {
			item.removeClass('dragging');
			wrapper.find('.category-tree-item').removeClass('drop-zone drag-over');
			update_weightages(wrapper);
		});

		item.on('dragover', function(e) {
			e.preventDefault();
			const dragging = wrapper.find('.dragging');
			const target = $(this);

			// Only allow drop on same level
			if (dragging.data('level') === target.data('level') && !target.hasClass('dragging')) {
				target.addClass('drag-over');
			}
		});

		item.on('dragleave', function(e) {
			$(this).removeClass('drag-over');
		});

		item.on('drop', function(e) {
			e.preventDefault();
			const dragging = wrapper.find('.dragging');
			const target = $(this);

			// Only allow drop on same level
			if (dragging.data('level') === target.data('level') && !target.hasClass('dragging')) {
				// Insert before or after based on position
				const rect = this.getBoundingClientRect();
				const midY = rect.top + rect.height / 2;

				if (e.originalEvent.clientY < midY) {
					dragging.insertBefore(target);
				} else {
					// Check if there's a children container after target
					const nextEl = target.next();
					if (nextEl.hasClass('category-children')) {
						dragging.insertAfter(nextEl);
					} else {
						dragging.insertAfter(target);
					}
				}
			}

			target.removeClass('drag-over');
		});
	});

	// Also handle weightage input changes
	wrapper.find('.item-weightage').on('change', function() {
		wrapper.find('.btn-save-order').prop('disabled', false);
	});
}

function update_weightages(wrapper) {
	// Update weightages based on new positions
	const containers = wrapper.find('.category-tree, .category-children');

	containers.each(function() {
		const container = $(this);
		const items = container.children('.category-tree-item');
		const count = items.length;

		items.each(function(index) {
			// Higher position (lower index) = higher weightage
			const newWeightage = (count - index) * 10;
			$(this).find('.item-weightage').val(newWeightage);
			$(this).data('weightage', newWeightage);
		});
	});

	// Enable save button
	wrapper.find('.btn-save-order').prop('disabled', false);
}

function save_category_order(wrapper) {
	const order_data = [];

	wrapper.find('.category-tree-item').each(function() {
		const item = $(this);
		order_data.push({
			name: item.data('name'),
			weightage: parseInt(item.find('.item-weightage').val()) || 0
		});
	});

	frappe.call({
		method: 'webshop.webshop.doctype.webshop_settings.webshop_settings.save_category_order',
		args: {
			order_data: JSON.stringify(order_data)
		},
		freeze: true,
		freeze_message: __('Saving category order...'),
		callback: function(r) {
			if (r.message && r.message.success) {
				frappe.show_alert({
					message: r.message.message,
					indicator: 'green'
				});
				wrapper.find('.btn-save-order').prop('disabled', true);
			}
		}
	});
}