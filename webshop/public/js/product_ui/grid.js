//// Neoffice — rewritten. Upstream built the tile here from template strings, a
//// second copy of the card the carousel and the wishlist drew in Jinja, and the
//// shop kept three tiles in step by hand. The listing endpoint now renders the
//// tile of every item it returns with the one product_card macro
//// (templates/includes/product_card.html, utils/product_card.py) and this class
//// only appends it. The bodies upstream had here are gone, not merely unreachable:
//// `git show frappe/webshop:webshop/public/js/product_ui/grid.js` has them.
webshop.ProductGrid = class {
	/* Options:
		- items: Items, each carrying the `card_html` the server rendered for it
		- settings: Webshop Settings
		- products_section: Products Wrapper
		- preference: If preference is not grid view, render but hide
		- no_render: If true, don't render on construction (for infinite scroll)
	*/
	constructor(options) {
		Object.assign(this, options);

		if (this.no_render) {
			return; // Don't render, just create instance for get_item_html
		}

		if (this.preference !== "Grid View") {
			this.products_section.addClass("hidden");
		}

		this.products_section.empty();
		this.make();
	}

	make() {
		let html = ``;
		this.items.forEach((item) => {
			html += this.get_item_html(item);
		});
		this.products_section.append(html);
	}

	get_item_html(item) {
		return item.card_html || "";
	}
};
