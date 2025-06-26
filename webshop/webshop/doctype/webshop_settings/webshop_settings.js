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
	}
});