webshop.ProductList = class {
	/* Options:
		- items: Items
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
		let me = this;
		let html = `<br><br>`;

		this.items.forEach(item => {
			html += me.get_item_html(item);
		});

		let $product_wrapper = this.products_section;
		$product_wrapper.append(html);
	}

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

		if (image) {
			image_html += `
				<div class="col-2 border text-center rounded list-image" style="position: relative; overflow: hidden;">
					${discount_badge}
					<a class="product-link product-list-link" href="/${ item.route || '#' }">
						<img itemprop="image" class="website-image h-100 w-100" alt="${ title }"
							src="${ image }">
					</a>
					${ wishlist_enabled ? this.get_wishlist_icon(item): '' }
				</div>
			`;
		} else {
			image_html += `
				<div class="col-2 border text-center rounded list-image" style="position: relative; overflow: hidden;">
					${discount_badge}
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

		details += `</div>`;
		
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
			stockText = window.product_translations && window.product_translations["Out of stock"] || "Out of stock";
			tooltipText = window.product_translations && window.product_translations["Out of stock"] || "Out of stock";
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
		
		return `
			<span class="stock-info">
				<span class="stock-badge ${stockClass}"></span>
				${stockQty ? `<span class="stock-qty">${stockQty}</span>` : ''}
				<span class="stock-tooltip">${tooltipText}</span>
			</span>
		`;
	}

	get_stock_availability(item, settings) {
		// Remove stock availability from here since we show it inline with category
		return ``;
		if (settings.show_stock_availability && !item.has_variants) {
			if (item.on_backorder) {
				return `
					<br>
					<span class="out-of-stock mt-2" style="color: var(--primary-color)">
						${ window.product_translations && window.product_translations["Available on backorder"] || "Available on backorder" }
					</span>
				`;
			} else if (!item.in_stock) {
				return `
					<br>
					<span class="out-of-stock mt-2">${ window.product_translations && window.product_translations["Out of stock"] || "Out of stock" }</span>
				`;
			} else if (item.is_stock) {
				return `
					<br>
					<span class="in-stock in-green has-stock mt-2"
						style="font-size: 14px;">${ window.product_translations && window.product_translations["In stock"] || "In stock" }</span>
				`;
			}
		}
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
		if (item.has_variants || item.is_gift_card || settings.enable_guest_cart == 0 && frappe.session.user == "Guest") {
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
