$(() => {
	class ProductListing {
		constructor() {
			let me = this;
			let is_item_group_page = $(".item-group-content").data("item-group");
			this.item_group = is_item_group_page || null;

			let view_type = localStorage.getItem("product_view") || "List View";

			//// Neoffice — the stock filter's initial state: the buyer's own preference when they
			//// have one, the shop's default otherwise (8ba1a7ab46, 2025-06-08).
			// Get stock filter settings
			let stock_filter_default = false;
			if (window.stock_filter_settings && window.stock_filter_settings.enabled) {
				// Check if user has a saved preference
				const saved_preference = localStorage.getItem('stock_filter_checked');
				if (saved_preference !== null) {
					// Use saved preference
					stock_filter_default = saved_preference === 'true';
				} else {
					// Use default from settings
					stock_filter_default = window.stock_filter_settings.default_checked;
				}
			}
			
			// Render Product Views, Filters & Search
			new webshop.ProductView({
				view_type: view_type,
				products_section: $('#product-listing'),
				//// Neoffice — see above.
				item_group: me.item_group,
				stock_filter_default: stock_filter_default
			});

			this.bind_card_actions();
			//// Neoffice — the category tree is interactive (see below); upstream's category facet
			//// is a flat list.
			this.bind_hierarchical_category_actions();
		}

		bind_card_actions() {
			webshop.webshop.shopping_cart.bind_add_to_cart_action();
			webshop.webshop.wishlist.bind_wishlist_action();
		}
//// Neoffice — expand/collapse of the hierarchical category filter (6fea19b1fe,
//// 2025-06-17).

		bind_hierarchical_category_actions() {
			// Handle click on +/- buttons to deploy/collapse categories
			$(document).on('click', '.toggle-children', function() {
				const $this = $(this);
				const $childrenContainer = $this.closest('.hierarchical-item-group').find('> .children-container');
				const isExpanded = $this.attr('data-expanded') === 'true';

				if (isExpanded) {
					// Collapse
					$childrenContainer.slideUp(200);
					$this.attr('data-expanded', 'false');
					$this.text('+');
				} else {
					// Deploy
					$childrenContainer.slideDown(200);
					$this.attr('data-expanded', 'true');
					$this.text('-');
				}
			});
		}
	}

	new ProductListing();
});
