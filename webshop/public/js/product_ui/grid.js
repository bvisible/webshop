webshop.ProductGrid = class {
	/* Options:
		- items: Items
		- settings: Webshop Settings
		- products_section: Products Wrapper
		- preference: If preference is not grid view, render but hide
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

		if (this.preference !== "Grid View") {
			this.products_section.addClass("hidden");
		}

		this.products_section.empty();
		this.make();
	}

	make() {
		let me = this;
		let html = ``;

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
		title = title.length > 90 ? title.substr(0, 90) + "..." : title;

		let html = `<div class="col-sm-4 item-card"><div class="card text-left">`;
		html += this.get_image_html(item, title);
		html += this.get_card_body_html(item, title, this.settings);
		html += `</div></div>`;

		return html;
	}

	get_image_html(item, title) {
		let image = item.website_image;
		let discount_badge = '';

		// Add discount badge if item has discount
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

		const {
			container_style: container_style,
			anchor_style: anchor_style,
			img_style: img_style,
		} = this.get_image_fit_styles(item);

		if (image) {
			//// Neoffice — added to the image block: the discount and second-hand-condition
			//// badges (d984eff855, 2026-09-03 "produits d'occasion"), and the inline styles
			//// of the Cover/Contain image fit with its per-item focus point (31feefcae6 /
			//// 3eae27c5b3 / 3cec45d8b4, 2026-04-19) — upstream always letterboxes the image.
			return `
				<div class="card-img-container"${container_style ? ` style="${container_style}"` : ''}>
					${discount_badge}${condition_badge}
					<a href="/${ item.route || '#' }" style="text-decoration: none;${anchor_style}">
						<img itemprop="image" class="card-img" src="${ image }" alt="${ title }"${img_style ? ` style="${img_style}"` : ''}>
					</a>
				</div>
			`;
		} else {
			//// Neoffice — same badges and fit styles on the no-image card (see above).
			return `
				<div class="card-img-container"${container_style ? ` style="${container_style}"` : ''}>
					${discount_badge}${condition_badge}
					<a href="/${ item.route || '#' }" style="text-decoration: none;${anchor_style}">
						<div class="card-img-top no-image">
							${ frappe.get_abbr(title) }
						</div>
					</a>
				</div>
			`;
		}
	}

	//// Neoffice — added helper. The comment below says why the styles are inline
	//// rather than in the SCSS bundle (31feefcae6, 2026-04-19).
	// Compute inline styles for Cover/Contain fit + per-item focus.
	// Keeping it here (not SCSS) lets the Webshop Settings toggle take
	// effect without a fresh `bench build`.
	get_image_fit_styles(item) {
		const settings = this.settings || {};
		const fit = settings.product_image_fit || 'Contain';
		if (fit !== 'Cover') {
			return { container_style: '', anchor_style: '', img_style: '' };
		}
		const ratio = (settings.product_image_aspect_ratio || '1/1').trim();
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
		const position = focus_map[item.image_focus] || 'center center';
		return {
			container_style: `aspect-ratio: ${ratio};`,
			// The anchor is inline by default — force it to fill the container so
			// the image's height: 100% resolves to the container's aspect-ratio
			// height instead of the image's intrinsic height.
			anchor_style: 'display: block; width: 100%; height: 100%;',
			img_style: `object-fit: cover; object-position: ${position}; width: 100%; height: 100%; max-height: none;`,
		};
	}

	get_card_body_html(item, title, settings) {
		let body_html = `
			<div class="card-body text-left card-body-flex" style="width:100%">
				<div style="margin-top: 1rem; display: flex;">
		`;
		body_html += this.get_title(item, title);

		// get floating elements
		if (!item.has_variants) {
			if (settings.enable_wishlist) {
				body_html += this.get_wishlist_icon(item);
			}
			if (settings.enabled) {
				body_html += this.get_cart_indicator(item);
			}

		}

		body_html += `</div>`;
		//// Neoffice — category and stock status share one line on the card; upstream puts
		//// the stock message under the price, which pushed the buy button off a phone
		//// screen (0d17ac8d40, 2026-08-26).
		
		// Category and stock info in same line
		body_html += `<div class="product-category-stock">`;
		body_html += `<div class="product-category" itemprop="name">${ item.item_group || '' }</div>`;
		//// Neoffice — the inline stock status (see above).
		
		// Add stock info if settings allow
		if (settings.show_stock_availability && !item.has_variants) {
			body_html += this.get_inline_stock_info(item);
		}
		
		body_html += `</div>`;

		if (item.formatted_price) {
			//// Neoffice — price and loyalty points share a wrapper (6fea19b1fe, 2025-06-17).
			body_html += `<div class="price-loyalty-wrapper">`;
			body_html += this.get_price_html(item);
			//// Neoffice — the loyalty-points badge next to the price; upstream has no loyalty
			//// programme (6fea19b1fe, 2025-06-17).
			
			// Add loyalty points icon next to price
			if (item.loyalty_points_html) {
				body_html += this.get_loyalty_points_html(item);
			}
			
			body_html += `</div>`;
		}

		body_html += this.get_stock_availability(item, settings);
		body_html += this.get_primary_button(item, settings);
		body_html += `</div>`; // close div on line 49

		return body_html;
	}

	get_title(item, title) {
		//// Neoffice — the card title link loses its underline (style only).
		let title_html = `
			<a href="/${ item.route || '#' }" style=" text-decoration: none;">
				<div class="product-title" itemprop="name">
					${ title || '' }
				</div>
			</a>
		`;
		return title_html;
	}

	get_wishlist_icon(item) {
		let icon_class = item.wished ? "wished" : "not-wished";
		return `
			<div class="like-action ${ item.wished ? "like-action-wished" : ''}"
				data-item-code="${ item.item_code }">
				<svg class="icon sm">
					<use class="${ icon_class } wish-icon" href="#icon-heart"></use>
				</svg>
			</div>
		`;
	}

	get_cart_indicator(item) {
		return `
			<div class="cart-indicator ${item.in_cart ? '' : 'hidden'}" data-item-code="${ item.item_code }">
				1
			</div>
		`;
	}

	get_price_html(item) {
		//// Neoffice — a gift card has no list price to show: its amount is chosen by the
		//// buyer on the product page (3bc2d836f1, 2025-02-11).
		if (item.is_gift_card) {
			return '';
		}
		let price_html = `
			<div class="product-price" itemprop="offers" itemscope itemtype="https://schema.org/AggregateOffer">
				${ item.formatted_price || '' }
		`;

		if (item.formatted_mrp) {
			price_html += `
				<small class="striked-price">
					<s>${ item.formatted_mrp ? item.formatted_mrp.replace(/ +/g, "") : "" }</s>
				</small>
				<small class="ml-1 product-info-green">
					- ${ item.discount }
				</small>
			`;
		}
		price_html += `</div>`;
		return price_html;
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

	//// Neoffice — added: the loyalty badge, and get_stock_availability below is
	//// emptied because the status is now rendered inline with the category (see #8).
	//// Upstream's body is gone from here, not merely unreachable — `git show
	//// frappe/webshop:webshop/public/js/product_ui/grid.js` has it.
	get_loyalty_points_html(item) {
		if (!item.loyalty_points_html) return '';
		
		return `
			<span class="loyalty-points-icon-wrapper">
				<img src="/assets/webshop/icons/loyalty_icon.svg" class="loyalty-icon-inline" alt="Loyalty Points">
				<span class="loyalty-tooltip-inline">
					${item.loyalty_points_html}
				</span>
			</span>
		`;
	}

	get_stock_availability(item, settings) {
		// This is now just for the larger stock message below price
		// Keeping empty since we show stock info inline with category
		return ``;
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
					<div class="btn btn-sm btn-explore-variants w-100 mt-4">
						${ window.product_translations && window.product_translations["Explore"] || "Explore" }
					</div>
				</a>
			`;
		} else if (settings.enabled && (settings.allow_items_not_in_stock || item.in_stock)) {
			return `
				<div id="${ item.name }" class="btn
					btn-sm btn-primary btn-add-to-cart-list
					w-100 mt-2 ${ item.in_cart ? 'hidden' : '' }"
					data-item-code="${ item.item_code }">
					<span class="mr-2">
						<svg class="icon icon-md">
							<use href="#icon-assets"></use>
						</svg>
					</span>
					${ settings.enable_checkout ? (window.product_translations && window.product_translations["Add to Cart"] || "Add to Cart") :  (window.product_translations && window.product_translations["Add to Quote"] || "Add to Quote") }
				</div>

				<a href="/cart">
					<div id="${ item.name }" class="btn
						btn-sm btn-primary btn-add-to-cart-list
						w-100 mt-4 go-to-cart-grid
						${ item.in_cart ? '' : 'hidden' }"
						data-item-code="${ item.item_code }">
						${ settings.enable_checkout ? (window.product_translations && window.product_translations["Go to Cart"] || "Go to Cart") :  (window.product_translations && window.product_translations["Go to Quote"] || "Go to Quote") }
					</div>
				</a>
			`;
		} else {
			return ``;
		}
	}
};
