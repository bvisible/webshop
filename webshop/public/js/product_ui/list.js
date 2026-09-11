//// Neoffice — rewritten. Upstream built the row here from template strings, a
//// copy of the card the grid, the carousel and the wishlist each drew their own
//// way. The listing endpoint now renders the row of every item it returns with the
//// one product_card macro (templates/includes/product_card.html, variant "list",
//// utils/product_card.py) and this class only appends it. The bodies upstream had
//// here are gone, not merely unreachable:
//// `git show frappe/webshop:webshop/public/js/product_ui/list.js` has them.
webshop.ProductList = class {
	/* Options:
		- items: Items, each carrying the `list_html` the server rendered for it
		- settings: Webshop Settings
		- products_section: Products Wrapper
		- preference: If preference is not list view, render but hide
		- no_render: If true, don't render on construction (for infinite scroll)
	*/
	constructor(options) {
		Object.assign(this, options);

		if (this.no_render) {
			return; // Don't render, just create instance for get_item_html
		}

		if (this.preference !== "List View") {
			this.products_section.addClass("hidden");
		}

		this.products_section.empty();
		this.make();
	}

	make() {
		let html = `<br><br>`;
		this.items.forEach((item) => {
			html += this.get_item_html(item);
		});
		this.products_section.append(html);
	}

	get_item_html(item) {
		return item.list_html || "";
	}
};
