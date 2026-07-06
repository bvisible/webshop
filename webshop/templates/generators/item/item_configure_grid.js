class ItemConfigureGrid {
	constructor(item_code, item_name) {
		this.item_code = item_code;
		this.item_name = item_name;
		this.selected_variant = null;
		this.variants_data = null;
		this.container = document.getElementById('variant-grid-container');
		this.loading = document.getElementById('variant-loading');
		
		this.init();
	}
	
	init() {
		this.fetch_variants_data();
	}
	
	fetch_variants_data() {
		frappe.call({
			method: "webshop.webshop.api.get_all_variants_info",
			args: {
				item_code: this.item_code
			},
			callback: (r) => {
				if (r.message && r.message.variants && r.message.variants.length > 0) {
					this.variants_data = r.message;
					this.show_variant_grid();
				} else {
					this.show_no_variants_message();
				}
			},
			error: (r) => {
				this.show_error_message();
				console.error('Error loading variants:', r);
			}
		});
	}
	
	show_variant_grid() {
		// Hide loading spinner
		if (this.loading) {
			this.loading.style.display = 'none';
		}
		
		// Show container
		if (this.container) {
			this.container.style.display = 'block';
		}
		
		// Show price range if available
		if (this.variants_data.price_range) {
			const priceRangeEl = this.container.querySelector('.price-range');
			if (priceRangeEl) {
				priceRangeEl.textContent = this.variants_data.price_range.formatted;
				priceRangeEl.style.display = 'inline-block';
			}
		}
		
		this.render_grid();
		this.setup_events();
	}
	
	show_no_variants_message() {
		if (this.loading) {
			this.loading.innerHTML = `
				<div class="alert alert-warning">
					${__('No variants available for this product')}
				</div>
			`;
		}
	}
	
	show_error_message() {
		if (this.loading) {
			this.loading.innerHTML = `
				<div class="alert alert-danger">
					${__('Error loading variants. Please try again.')}
				</div>
			`;
		}
	}
	
	render_grid() {
		const grid_container = document.getElementById('variant-grid');
		if (!grid_container) return;
		
		grid_container.innerHTML = '';
		
		// Group variants by first attribute for better organization
		const variants = this.variants_data.variants;
		const attributes = this.variants_data.attributes;
		
		// Create Bootstrap row
		const row = document.createElement('div');
		row.className = 'row';
		
		// Render each variant
		variants.forEach(variant => {
			const card = this.create_variant_card(variant, attributes);
			row.appendChild(card);
		});
		
		grid_container.appendChild(row);
	}
	
	create_variant_card(variant, attributes) {
		const col = document.createElement('div');
		col.className = 'col-lg-3 col-md-4 col-sm-6 mt-1';
		
		const card = document.createElement('div');
		card.className = 'variant-card';
		card.dataset.variantId = variant.item_code;
		card.dataset.inStock = variant.in_stock ? '1' : '0';
		
		// Add disabled class if out of stock, no website item, or doesn't exist
		if (!variant.in_stock || !variant.website_item || !variant.exists) {
			card.classList.add('disabled');
		}
		
		// Build attributes HTML - show attribute name and value for multiple attributes
		let attributes_html = '<div class="variant-attributes">';
		const attributeValues = [];
		
		// If only one attribute, show just the value. If multiple, show "Name: Value"
		const hasMultipleAttributes = attributes.filter(attr => variant.attributes[attr.attribute]).length > 1;
		
		attributes.forEach(attr => {
			const value = variant.attributes[attr.attribute];
			if (value) {
				if (hasMultipleAttributes) {
					attributeValues.push(`<span class="attr-label">${attr.attribute}:</span> <span class="attr-value">${value}</span>`);
				} else {
					attributeValues.push(`<span class="attr-value">${value}</span>`);
				}
			}
		});
		attributes_html += attributeValues.join(', ');
		attributes_html += '</div>';
		
		// Store additional info as data attributes for showing on click
		card.dataset.price = variant.price ? JSON.stringify(variant.price) : '';
		card.dataset.stockQty = variant.stock_qty || 0;
		card.dataset.exists = variant.exists !== false;
		
		// Build stock indicator with quantity
		let stock_indicator = '';
		if (variant.in_stock && variant.stock_qty) {
			// Show green indicator with stock count
			stock_indicator = `<div class="stock-indicator available" title="${variant.stock_qty} in stock">${variant.stock_qty}</div>`;
		} else if (!variant.in_stock || !variant.exists) {
			// Show red indicator for unavailable
			stock_indicator = '<div class="stock-indicator unavailable" title="Not available"></div>';
		}
		
		// Combine HTML
		card.innerHTML = attributes_html + stock_indicator;
		col.appendChild(card);
		
		return col;
	}
	
	setup_events() {
		const self = this;
		const grid = document.getElementById('variant-grid');
		if (!grid) return;
		
		// Click handler for variant cards
		grid.addEventListener('click', function(e) {
			const card = e.target.closest('.variant-card');
			if (!card || card.classList.contains('disabled')) return;
			
			const variant_id = card.dataset.variantId;
			if (!variant_id || variant_id === 'null') return; // Don't select non-existent variants
			
			// Remove previous selection
			grid.querySelectorAll('.variant-card').forEach(c => {
				c.classList.remove('selected');
			});
			
			// Add selection to clicked card
			card.classList.add('selected');
			
			// Find the selected variant data
			self.selected_variant = self.variants_data.variants.find(v => v.item_code === variant_id);
			
			// Update footer with selected variant info
			self.update_selected_info();
		});
		
		// Add to cart handler
		const addToCartBtn = document.querySelector('.btn-add-to-cart');
		if (addToCartBtn) {
			addToCartBtn.addEventListener('click', function() {
				if (self.selected_variant) {
					self.add_to_cart();
				}
			});
		}
	}
	
	getVariantDisplayName() {
		if (!this.selected_variant) return '';
		
		// Get base item name
		const baseItemName = this.item_name || '';
		
		// Build variant attributes string
		const attrs = this.variants_data.attributes;
		const variant_parts = [];
		attrs.forEach(attr => {
			const value = this.selected_variant.attributes[attr.attribute];
			if (value) {
				variant_parts.push(`${value}`);
			}
		});
		
		// Combine base name with variant attributes
		if (variant_parts.length > 0) {
			return `${baseItemName} - ${variant_parts.join(' ')}`;
		}
		return baseItemName;
	}
	
	update_selected_info() {
		const footer = document.querySelector('.variant-grid-footer');
		if (!footer) return;
		
		if (this.selected_variant) {
			// Build variant name from attributes
			const attrs = this.variants_data.attributes;
			const variant_name_parts = [];
			attrs.forEach(attr => {
				const value = this.selected_variant.attributes[attr.attribute];
				if (value) {
					variant_name_parts.push(`${attr.attribute}: ${value}`);
				}
			});
			
			const nameElement = footer.querySelector('.selected-variant-name');
			if (nameElement) {
				nameElement.textContent = variant_name_parts.join(', ');
			}
			
			// Update price
			const priceElement = footer.querySelector('.selected-variant-price');
			if (priceElement) {
				if (this.selected_variant.price && this.selected_variant.price.formatted_price) {
					let priceHtml = this.selected_variant.price.formatted_price;
					if (this.selected_variant.price.formatted_mrp && this.selected_variant.price.discount_percent) {
						priceHtml += ` <small class="text-muted"><del>${this.selected_variant.price.formatted_mrp}</del></small>`;
						priceHtml += ` <span class="badge badge-success">${this.selected_variant.price.discount_percent}% off</span>`;
					}
					priceElement.innerHTML = priceHtml;
				} else {
					priceElement.innerHTML = '<span class="text-muted">Not Available</span>';
				}
			}
			
			// Update stock info
			let stockInfoHtml = '';
			if (this.selected_variant.in_stock) {
				stockInfoHtml = `<span class="badge badge-success">{{ _("In Stock") }}</span>`;
				if (this.selected_variant.stock_qty && this.selected_variant.stock_qty < 10) {
					stockInfoHtml += ` <small class="text-warning">${'{{ _("Only {0} left") }}'.replace('{0}', this.selected_variant.stock_qty)}</small>`;
				}
			} else if (this.selected_variant.exists !== false) {
				stockInfoHtml = `<span class="badge badge-secondary">{{ _("Out of Stock") }}</span>`;
			} else {
				stockInfoHtml = `<span class="badge badge-dark">{{ _("Not Available") }}</span>`;
			}
			
			// Add stock info to footer
			const stockContainer = footer.querySelector('.selected-variant-stock');
			if (!stockContainer) {
				const priceElement = footer.querySelector('.selected-variant-price');
				if (priceElement) {
					const stockDiv = document.createElement('div');
					stockDiv.className = 'selected-variant-stock mt-2';
					stockDiv.innerHTML = stockInfoHtml;
					priceElement.parentNode.insertBefore(stockDiv, priceElement.nextSibling);
				}
			} else {
				stockContainer.innerHTML = stockInfoHtml;
			}
			
			// Show/hide add to cart button based on availability
			const addToCartBtn = footer.querySelector('.btn-add-to-cart');
			if (addToCartBtn) {
				if (this.selected_variant.in_stock && this.selected_variant.exists !== false && this.selected_variant.website_item) {
					addToCartBtn.style.display = 'inline-block';
				} else {
					addToCartBtn.style.display = 'none';
				}
			}
			
			// Show footer
			footer.style.display = 'block';
		} else {
			footer.style.display = 'none';
		}
	}
	
	add_to_cart() {
		if (!this.selected_variant) return;
		
		const btn = document.querySelector('.btn-add-to-cart');
		if (btn) {
			btn.disabled = true;
			btn.textContent = __('Adding...');
		}
		
		// Check if shopping cart object exists
		const shopping_cart = window.erpnext?.shopping_cart || window.webshop?.shopping_cart;
		
		if (shopping_cart && shopping_cart.update_cart) {
			shopping_cart.update_cart({
				item_code: this.selected_variant.item_code,
				qty: 1,
				callback: (r) => {
					if (!r.exc) {
						// Show mini cart notification if function exists
						if (typeof showMiniCartNotification === 'function') {
							// Get variant details for notification
							const variantName = this.getVariantDisplayName();
							const variantImage = this.selected_variant.image || '';
							
							showMiniCartNotification(
								this.selected_variant.item_code,
								1,
								variantName,
								variantImage
							);
						} else {
							// Fallback to simple alert
							frappe.show_alert({
								message: __('Added to cart'),
								indicator: 'green'
							});
						}
						
						// Update cart icon
						if (r.message && r.message.shopping_cart_menu) {
							const cartMenu = document.querySelector('.shopping-cart-menu');
							if (cartMenu) {
								cartMenu.outerHTML = r.message.shopping_cart_menu;
							}
						}
						
						// Open side cart after refreshing cart data
						if (typeof refreshCart === 'function') {
							refreshCart(() => {
								if (typeof openCart === 'function') {
									setTimeout(() => {
										openCart();
									}, 300);
								}
							});
						} else if (typeof openCart === 'function') {
							setTimeout(() => {
								openCart();
							}, 300);
						}
						
						// Reset button
						if (btn) {
							btn.disabled = false;
							btn.textContent = __('Add to Cart');
						}
					} else {
						if (btn) {
							btn.disabled = false;
							btn.textContent = __('Add to Cart');
						}
					}
				}
			});
		} else {
			// Fallback to direct API call
			frappe.call({
				method: "webshop.webshop.shopping_cart.cart.update_cart",
				args: {
					item_code: this.selected_variant.item_code,
					qty: 1
				},
				callback: (r) => {
					if (!r.exc) {
						// Show mini cart notification if function exists
						if (typeof showMiniCartNotification === 'function') {
							// Get variant details for notification
							const variantName = this.getVariantDisplayName();
							const variantImage = this.selected_variant.image || '';
							
							showMiniCartNotification(
								this.selected_variant.item_code,
								1,
								variantName,
								variantImage
							);
						} else {
							// Fallback to simple alert
							frappe.show_alert({
								message: __('Added to cart'),
								indicator: 'green'
							});
						}
						
						// Update cart icon
						if (r.message && r.message.shopping_cart_menu) {
							const cartMenu = document.querySelector('.shopping-cart-menu');
							if (cartMenu) {
								cartMenu.outerHTML = r.message.shopping_cart_menu;
							}
						}
						
						// Open side cart after refreshing cart data
						if (typeof refreshCart === 'function') {
							refreshCart(() => {
								if (typeof openCart === 'function') {
									setTimeout(() => {
										openCart();
									}, 300);
								}
							});
						} else if (typeof openCart === 'function') {
							setTimeout(() => {
								openCart();
							}, 300);
						}
						
						// Reset button
						if (btn) {
							btn.disabled = false;
							btn.textContent = __('Add to Cart');
						}
					} else {
						if (btn) {
							btn.disabled = false;
							btn.textContent = __('Add to Cart');
						}
					}
				}
			});
		}
	}
}