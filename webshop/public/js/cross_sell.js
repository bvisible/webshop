//// Neoffice — added file (cross-sell offers, no upstream equivalent).
//// One renderer for every placement: the product page, the cart page, the
//// cart drawer and the checkout. The server says what to show and in which
//// words (webshop.webshop.utils.cross_sell.get_offers); this file only draws
//// and clicks. Website pages have no __() catalogue, hence the labels ride
//// with the offers.
frappe.provide("webshop.cross_sell");

webshop.cross_sell = {
	load(container, opts = {}) {
		if (!container) return;
		const placement = opts.placement || container.dataset.placement || "cart";
		const item_codes = opts.item_codes || (container.dataset.itemCode ? [container.dataset.itemCode] : []);
		frappe.call({
			method: "webshop.webshop.utils.cross_sell.get_offers",
			args: { placement, item_codes: JSON.stringify(item_codes) },
			callback: (r) => this.render(container, r.message || [], Object.assign({ placement }, opts)),
		});
	},

	render(container, offers, opts) {
		if (!offers.length) {
			container.innerHTML = "";
			container.classList.remove("has-offers");
			return;
		}
		const checkout = opts.placement === "checkout";
		const title = offers[0].labels.title;
		container.innerHTML =
			(checkout ? "" : `<div class="xsell-title">${this.escape(title)}</div>`) +
			offers.map((o) => (checkout ? this.bump_html(o) : this.card_html(o, opts))).join("");
		container.classList.add("has-offers");
		container.querySelectorAll("[data-accept-offer]").forEach((el) => {
			const offer = offers.find((o) => o.name === el.dataset.acceptOffer);
			if (checkout) {
				el.addEventListener("change", () => this.accept(offer, el, { remove: !el.checked, ...opts }));
			} else {
				el.addEventListener("click", (e) => {
					e.preventDefault();
					this.accept(offer, el, opts);
				});
			}
		});
	},

	price_html(o) {
		if (!o.has_advantage) return `<span class="xsell-price">${o.formatted_price}</span>`;
		return (
			`<span class="xsell-price">${o.formatted_offer_price}</span> ` +
			`<s class="xsell-old-price">${o.formatted_price}</s>` +
			(o.advantage ? ` <span class="xsell-badge">${this.escape(o.advantage)}</span>` : "")
		);
	},

	image_html(o) {
		return o.image
			? `<img src="${o.image}" alt="${this.escape(o.web_item_name)}" loading="lazy">`
			: `<span class="xsell-abbr">${this.escape((o.web_item_name || "?")[0]).toUpperCase()}</span>`;
	},

	card_html(o, opts) {
		const button = opts.with_trigger ? o.labels.add_both : o.labels.add;
		return `
			<div class="xsell-card" data-offer="${o.name}">
				<a class="xsell-card__image" href="/${o.route}">${this.image_html(o)}</a>
				<div class="xsell-card__body">
					<div class="xsell-card__headline">${this.escape(o.headline)}</div>
					<a class="xsell-card__name" href="/${o.route}">${this.escape(o.web_item_name)}</a>
					${o.description ? `<div class="xsell-card__desc">${this.escape(o.description)}</div>` : ""}
					<div class="xsell-card__price">${this.price_html(o)}</div>
				</div>
				<button type="button" class="btn btn-sm btn-primary xsell-card__btn" data-accept-offer="${o.name}">${this.escape(button)}</button>
			</div>`;
	},

	bump_html(o) {
		const id = `xsell-bump-${o.name}`;
		return `
			<label class="xsell-bump frappe-card" for="${id}" data-offer="${o.name}">
				<input type="checkbox" id="${id}" class="xsell-bump__check" data-accept-offer="${o.name}">
				<span class="xsell-bump__image">${this.image_html(o)}</span>
				<span class="xsell-bump__text">
					<strong>${this.escape(o.labels.yes_add)}</strong>
					<span class="xsell-bump__headline">${this.escape(o.headline)}</span>
					<span class="xsell-bump__price">${this.price_html(o)}</span>
				</span>
			</label>`;
	},

	accept(offer, el, opts) {
		el.disabled = true;
		frappe.call({
			method: "webshop.webshop.utils.cross_sell.accept_offer",
			args: { offer: offer.name, with_trigger: opts.with_trigger ? 1 : 0, remove: opts.remove ? 1 : 0 },
			callback: (r) => {
				el.disabled = false;
				if (!r.message) return;
				const cart = webshop.webshop && webshop.webshop.shopping_cart;
				if (cart && cart.set_cart_count) cart.set_cart_count(true);
				if (frappe.show_alert) {
					frappe.show_alert({ message: opts.remove ? offer.labels.removed : offer.labels.added, indicator: "green" });
				}
				if (opts.after) opts.after(r.message);
				else if (typeof window.refreshCart === "function") window.refreshCart(true);
			},
			error: () => {
				el.disabled = false;
			},
		});
	},

	escape(text) {
		return String(text == null ? "" : text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
	},
};

frappe.ready(() => {
	document.querySelectorAll(".cross-sell-offers[data-autoload]").forEach((container) => {
		const placement = container.dataset.placement;
		webshop.cross_sell.load(container, {
			placement,
			with_trigger: placement === "product" ? 1 : 0,
			// the cart page draws its lines server side: reload to show the new one
			after: placement === "cart" ? () => window.location.reload() : null,
		});
	});
});
