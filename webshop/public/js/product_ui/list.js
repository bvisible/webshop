webshop.ProductList = class {
	/* Options:
		- items: Items
		- settings: Webshop Settings
		- products_section: Products Wrapper
		- preference: If preference is not list view, render but hide
		//// Neoffice — no_render: the infinite scroll builds a view only to call
		//// get_item_html on it, without rendering (2591df1013, 2025-12-14).
		- no_render: If true, don't render on construction (for infinite scroll)
	*/
	constructor(options) {
		Object.assign(this, options);

		//// Neoffice — see no_render above: the constructor returns before touching the
		//// DOM.
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
		let me = this;
		let html = `<br><br>`;

		this.items.forEach(item => {
			//// Neoffice — the card markup is moved into get_item_html so the infinite scroll
			//// can render one item at a time; upstream builds it inline in this loop
			//// (2591df1013, 2025-12-14).
			html += me.get_item_html(item);
		});

		let $product_wrapper = this.products_section;
		$product_wrapper.append(html);
	}

	//// Neoffice — added: one card, extracted from the loop above (see #3).
	get_item_html(item) {
		let title = item.web_item_name || item.item_name || item.item_code || "";
		title = title.length > 200 ? title.substr(0, 200) + "..." : title;

		let html = `<div class='row list-row w-100 mb-4'>`;
		html += this.get_image_html(item, title, this.settings);
		html += this.get_row_body_html(item, title, this.settings);
		html += `</div>`;

		return html;
	}

	get_image_html(item, title, settings) {
		let image = item.website_image;
		let wishlist_enabled = !item.has_variants && settings.enable_wishlist;
		let image_html = ``;

		// Add discount badge if item has discount
		let discount_badge = '';
		if (item.discount_percent && item.discount_percent > 0) {
			discount_badge = `
				<div class="discount-badge">
					<span>- ${Math.round(item.discount_percent)}%</span>
				</div>
			`;
		}

		//// Neoffice — second-hand: a used or refurbished unit is badged like a
		//// discount, so a customer never mistakes it for new.
		let condition_badge = '';
		if (item.item_condition && item.item_condition !== 'New') {
			const t = window.product_translations || {};
			condition_badge = `<div class="condition-badge"><span>${t[item.item_condition] || item.item_condition}</span></div>`;
		}

		const fit = (settings && settings.product_image_fit) || 'Contain';
		const focus_map = {
			'Center': 'center center',
			'Top': 'center top',
			'Bottom': 'center bottom',
			'Left': 'left center',
			'Right': 'right center',
			'Top Left': 'left top',
			'Top Right': 'right top',
			'Bottom Left': 'left bottom',
			'Bottom Right': 'right bottom',
		};
		const img_style = fit === 'Cover'
			? ` style="object-fit: cover; object-position: ${focus_map[item.image_focus] || 'center center'};"`
			: '';

		if (image) {
			//// Neoffice — the row image gets the badges (discount, second-hand condition) and
			//// the Cover/Contain fit styles, like the grid card (31feefcae6, 2026-04-19;
			//// d984eff855, 2026-09-03).
			//// Neoffice — the fit styles on the image itself (see above).
			image_html += `
				<div class="col-2 border text-center rounded list-image" style="position: relative; overflow: hidden;">
					${discount_badge}${condition_badge}
					<a class="product-link product-list-link" href="/${ item.route || '#' }">
						<img itemprop="image" class="website-image h-100 w-100" alt="${ title }"
							src="${ image }"${img_style}>
					</a>
					${ wishlist_enabled ? this.get_wishlist_icon(item): '' }
				</div>
			`;
		} else {
			//// Neoffice — same badges and overflow on the no-image row (see above).
			image_html += `
				<div class="col-2 border text-center rounded list-image" style="position: relative; overflow: hidden;">
					${discount_badge}${condition_badge}
					<a class="product-link product-list-link" href="/${ item.route || '#' }"
						style="text-decoration: none">
						<div class="card-img-top no-image-list">
							${ frappe.get_abbr(title) }
						</div>
					</a>
					${ wishlist_enabled ? this.get_wishlist_icon(item): '' }
				</div>
			`;
		}

		return image_html;
	}

	get_row_body_html(item, title, settings) {
		let body_html = `<div class='col-10 text-left'>`;
		body_html += this.get_title_html(item, title, settings);
		body_html += this.get_item_details(item, settings);
		body_html += `</div>`;
		return body_html;
	}

	get_title_html(item, title, settings) {
		let title_html = `<div style="display: flex; margin-left: -15px;">`;
		title_html += `
			<div class="col-8" style="margin-right: -15px;">
				<a class="" href="/${ item.route || '#' }"
					style="color: var(--gray-800); font-weight: 500;">
					${ title }
				</a>
			</div>
		`;

		if (settings.enabled) {
			title_html += `<div class="col-4 cart-action-container ${item.in_cart ? 'd-flex' : ''}">`;
			title_html += this.get_primary_button(item, settings);
			title_html += `</div>`;
		}
		title_html += `</div>`;

		return title_html;
	}

	get_item_details(item, settings) {
		//// Neoffice — upstream prints one block: code, then description. Ours splits on
		//// whether the line is a gift card (no stock, no price to show) and otherwise
		//// puts the stock status on the same line as the category, so the row keeps its
		//// height on a phone (0d17ac8d40, 2026-08-26). "Item Code" is translated through
		//// window.product_translations because __() is not loaded in this bundle
		//// (dd08553e88, 2025-12-15).
		let details = '';
		if (item.is_gift_card) {
			details = `
				<p class="product-code">
					${ item.item_group } | ${ window.product_translations && window.product_translations["Item Code"] || "Item Code" } : ${ item.item_code }
				</p>
				<div class="mt-2" style="color: var(--gray-600) !important; font-size: 13px;">
					${ item.short_description || '' }
				</div>
			`;
			return details;
		} else {
			// Show category and stock info on same line
			let stock_info = '';
			if (settings.show_stock_availability && !item.has_variants) {
				stock_info = this.get_inline_stock_info(item);
			}
			
			details = `
				<div class="product-category-stock">
					<p class="product-code" style="margin-bottom: 0.5rem;">
						${ item.item_group } | ${ window.product_translations && window.product_translations["Item Code"] || "Item Code" } : ${ item.item_code }
						${stock_info ? ' | ' + stock_info : ''}
					</p>
				</div>
				<div class="mt-2" style="color: var(--gray-600) !important; font-size: 13px;">
					${ item.short_description || '' }
				</div>
				<div class="product-price" itemprop="offers" itemscope itemtype="https://schema.org/AggregateOffer">
					${ item.formatted_price || '' }
			`;

		if (item.formatted_mrp) {
			details += `
				<small class="striked-price">
					<s>${ item.formatted_mrp ? item.formatted_mrp.replace(/ +/g, "") : "" }</s>
				</small>
				<small class="ml-1 product-info-green">
					- ${ item.discount }
				</small>
			`;
		}
//// Neoffice — the stock line is no longer appended here (it is inline with the
//// category, see #8).

		details += `</div>`;
		//// Neoffice — the loyalty-points badge; upstream has no loyalty programme
		//// (6fea19b1fe, 2025-06-17).
		
		// Add loyalty points if available
		if (item.loyalty_points_html) {
			details += `
				<div class="loyalty-points-info">
					<span class="loyalty-points-badge loyalty-badge-small">
						<img src="/assets/webshop/icons/loyalty_icon.svg" class="loyalty-icon" alt="Points de fidélité">
						${item.loyalty_points_html}
					</span>
				</div>
			`;
		}
		}
		return details;
	}
	
	get_inline_stock_info(item) {
		let stockClass = '';
		let stockText = '';
		let stockQty = '';
		let tooltipText = '';
		
		if (item.on_backorder) {
			stockClass = 'on-backorder';
			stockText = window.product_translations && window.product_translations["On backorder"] || "On backorder";
			tooltipText = window.product_translations && window.product_translations["On backorder"] || "On backorder";
		} else if (!item.in_stock) {
			stockClass = 'out-of-stock';
			//// Neoffice — a second-hand unit is one of a kind: gone means sold.
			const sold = item.item_condition && item.item_condition !== "New";
			stockText = sold
				? (window.product_translations && window.product_translations["Sold"] || "Sold")
				: (window.product_translations && window.product_translations["Out of stock"] || "Out of stock");
			tooltipText = stockText;
		} else if (item.stock_qty && parseFloat(item.stock_qty) <= 5) {
			stockClass = 'low-stock';
			stockText = window.product_translations && window.product_translations["Low stock"] || "Low stock";
			stockQty = `(${Math.floor(item.stock_qty)})`;
			tooltipText = (window.product_translations && window.product_translations["Low stock"] || "Low stock") + `: ${Math.floor(item.stock_qty)} ${window.product_translations && window.product_translations["available"] || "available"}`;
		} else {
			stockClass = 'in-stock';
			stockText = window.product_translations && window.product_translations["In stock"] || "In stock";
			// Toujours afficher la quantité si elle existe et est > 0
			if (item.stock_qty !== undefined && item.stock_qty !== null && parseFloat(item.stock_qty) > 0) {
				stockQty = `(${Math.floor(item.stock_qty)})`;
				tooltipText = (window.product_translations && window.product_translations["In stock"] || "In stock") + `: ${Math.floor(item.stock_qty)} ${window.product_translations && window.product_translations["available"] || "available"}`;
			} else {
				tooltipText = window.product_translations && window.product_translations["In stock"] || "In stock";
			}
		}
		
		//// Neoffice — stockText was computed and then never rendered: the tile
		//// showed a bare coloured dot, so the status was carried by colour
		//// alone (invisible to a colour-blind shopper, and to a screen reader).
		//// The wording is out in the open now, and the whole thing is labelled.
		return `
			<span class="stock-info" role="status" aria-label="${tooltipText}" title="${tooltipText}">
				<span class="stock-badge ${stockClass}" aria-hidden="true"></span>
				<span class="stock-text">${stockText}</span>
				${stockQty ? `<span class="stock-qty">${stockQty}</span>` : ''}
				<span class="stock-tooltip">${tooltipText}</span>
			</span>
		`;
	}

	get_stock_availability(item, settings) {
		//// Neoffice — emptied: the stock status is rendered inline with the category,
		//// next to it, by get_inline_stock_info() (0d17ac8d40, 2026-08-26). Upstream's
		//// body used to sit below the `return ``;` where nothing could ever reach it;
		//// deleted 2026-09-04 — `git show frappe/webshop:webshop/public/js/product_ui/
		//// list.js` has it if the inline rendering is ever dropped.
		return ``;
	}

	get_wishlist_icon(item) {
		let icon_class = item.wished ? "wished" : "not-wished";

		return `
			<div class="like-action-list ${ item.wished ? "like-action-wished" : ''}"
				data-item-code="${ item.item_code }">
				<svg class="icon sm">
					<use class="${ icon_class } wish-icon" href="#icon-heart"></use>
				</svg>
			</div>
		`;
	}

	get_primary_button(item, settings) {
		//// Neoffice — Une prestation réservable ne s'ajoute pas au panier d'ici :
		// le panier recevrait une heure de cours SANS heure. Aucun créneau retenu,
		// rien au planning, et le même créneau revendu le soir même. La vignette
		// renvoie donc à la fiche, où l'on choisit son moment.
		if (item.bookable) {
			return `
				<a href="/${ item.route || '#' }">
					<div class="btn btn-sm btn-explore-variants w-100 mt-4">
						${ window.product_translations && window.product_translations["Book a slot"] || "Book a slot" }
					</div>
				</a>
			`;
		}
		if (item.has_variants || item.is_gift_card || settings.enable_guest_cart == 0 && frappe.session.user == "Guest") {
			//// Neoffice — upstream calls frappe's __(); this file is a bundle served to the
			//// shop, where __() is not loaded, so the string came out in English on a French
			//// shop. Translations come from window.product_translations (dd08553e88,
			//// 2025-12-15).
			return `
				<a href="/${ item.route || '#' }">
					<div class="btn btn-sm btn-explore-variants btn mb-0 mt-0">
						${ window.product_translations && window.product_translations["Explore"] || "Explore" }
					</div>
				</a>
			`;
		} else if (settings.enabled && (settings.allow_items_not_in_stock || item.in_stock)) {
			return `
				<div id="${ item.name }" class="btn
					btn-sm btn-primary btn-add-to-cart-list mb-0
					${ item.in_cart ? 'hidden' : '' }"
					data-item-code="${ item.item_code }"
					style="margin-top: 0px !important; max-height: 30px; float: right;
						padding: 0.25rem 1rem; min-width: 135px;">
					<span class="mr-2">
						<svg class="icon icon-md">
							<use href="#icon-assets"></use>
						</svg>
					</span>
					${ settings.enable_checkout ? (window.product_translations && window.product_translations["Add to Cart"] || "Add to Cart") :  (window.product_translations && window.product_translations["Add to Quote"] || "Add to Quote") }
				</div>

				<div class="cart-indicator list-indicator ${item.in_cart ? '' : 'hidden'}">
					1
				</div>

				<a href="/cart">
					<div id="${ item.name }" class="btn
						btn-sm btn-primary btn-add-to-cart-list
						ml-4 go-to-cart mb-0 mt-0
						${ item.in_cart ? '' : 'hidden' }"
						data-item-code="${ item.item_code }"
						style="padding: 0.25rem 1rem; min-width: 135px;">
						${ settings.enable_checkout ? (window.product_translations && window.product_translations["Go to Cart"] || "Go to Cart") :  (window.product_translations && window.product_translations["Go to Quote"] || "Go to Quote") }
					</div>
				</a>
			`;
		} else {
			return ``;
		}
	}

};
