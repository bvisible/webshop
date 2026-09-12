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
		//// Neoffice — the tile is rendered on the server (templates/includes/product_card.html,
		//// utils/product_card.py): upstream built it here from template strings, a third copy
		//// of the card next to the carousel's and the wishlist's (2026-09-11).
		let html = ``;
		this.items.forEach((item) => {
			//// Neoffice — see make(): the listing endpoint sends each item's tile.
			html += this.get_item_html(item);
		});
		//// Neoffice — one append for the whole batch, as before; only the source changed.
		this.products_section.append(html);
	}

	get_item_html(item) {
		//// Neoffice — the server's tile (attach_cards); upstream's 300-line template string is gone.
		return item.card_html || "";
	}
};
