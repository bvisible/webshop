$(() => {
	class ProductListing {
		constructor() {
			let me = this;
			let is_item_group_page = $(".item-group-content").data("item-group");
			this.item_group = is_item_group_page || null;

			let view_type = localStorage.getItem("product_view") || "List View";

			// Render Product Views, Filters & Search
			new webshop.ProductView({
				view_type: view_type,
				products_section: $('#product-listing'),
				item_group: me.item_group
			});

			this.bind_card_actions();
			this.bind_hierarchical_category_actions();
		}

		bind_card_actions() {
			webshop.webshop.shopping_cart.bind_add_to_cart_action();
			webshop.webshop.wishlist.bind_wishlist_action();
		}

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
