//// Neoffice — added file (no upstream equivalent). Behaviour of the variant selector:
//// loads every variant in one call (prices with Pricing Rules applied, stock, picture)
//// and switches the buy box without a page reload (6fea19b1fe, 2025-06-17; stock labels
//// made translatable by a20e0dd1f8, 2026-07-06).
////
//// Rewritten on 2026-09-13 as one row of chips per attribute — colour, then size — the
//// way a shop sells a garment, instead of one card per combination ("Colour: GREY, Size:
//// M" twelve times over). A chip that no variant in stock can satisfy, given what is
//// already chosen, is struck; a chip that no variant has at all is hidden; a chip whose
//// variants carry their own picture (a colour) shows it and, once chosen, swaps the
//// gallery's first picture for it. The footer (price, stock, add to cart) is unchanged.
class ItemConfigureGrid {
	constructor(item_code, item_name) {
		this.item_code = item_code;
		this.item_name = item_name;
		this.selected_variant = null;
		this.variants_data = null;
		this.selection = {};
		this.container = document.getElementById('variant-grid-container');
		this.loading = document.getElementById('variant-loading');
		this.rows_host = document.getElementById('wsp-variants');

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
		if (this.loading) {
			this.loading.style.display = 'none';
		}
		if (this.container) {
			this.container.style.display = 'block';
		}
		if (this.variants_data.price_range) {
			const priceRangeEl = this.container.querySelector('.price-range');
			if (priceRangeEl) {
				priceRangeEl.textContent = this.variants_data.price_range.formatted;
				priceRangeEl.style.display = 'inline-block';
			}
		}
		this.render_rows();
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

	// ---- the rows -------------------------------------------------------------

	/** The attributes in the template's order, each with its values in the attribute's own
	 *  order (S, M, L, XL — not alphabetical), restricted to what some variant carries. */
	attribute_rows() {
		const attributes = (this.variants_data.attributes || []).map(a => a.attribute);
		const ordered = this.variants_data.attribute_values || {};
		return attributes.map(attribute => {
			const present = new Set(this.variants_data.variants.map(v => v.attributes[attribute]).filter(Boolean));
			const values = (ordered[attribute] || []).filter(v => present.has(v));
			present.forEach(v => { if (!values.includes(v)) values.push(v); });
			return { attribute, values };
		});
	}

	/** A variant the shopper can buy: published, in stock (or the shop sells on backorder). */
	sellable(variant) {
		return variant.exists !== false && variant.website_item && variant.in_stock;
	}

	/** The variants matching a partial selection. */
	matching(selection) {
		return this.variants_data.variants.filter(v => Object.keys(selection).every(attr => !selection[attr] || v.attributes[attr] === selection[attr]));
	}

	/** True when this attribute's values come with their own picture (a colour, usually). */
	values_have_pictures(attribute) {
		const seen = {};
		for (const v of this.variants_data.variants) {
			const value = v.attributes[attribute];
			if (!value || !v.image) continue;
			seen[value] = seen[value] || v.image;
		}
		const pictures = Object.values(seen);
		return pictures.length > 1 && new Set(pictures).size > 1;
	}

	picture_for(attribute, value) {
		const v = this.variants_data.variants.find(x => x.attributes[attribute] === value && x.image);
		return v ? v.image : null;
	}

	render_rows() {
		if (!this.rows_host) return;
		this.rows_host.innerHTML = '';
		this.rows = this.attribute_rows();
		this.rows.forEach(row => {
			const withPictures = this.values_have_pictures(row.attribute);
			const section = document.createElement('div');
			section.className = 'wsp-variants__row' + (withPictures ? ' wsp-variants__row--pictures' : '');
			section.dataset.attribute = row.attribute;
			const label = document.createElement('div');
			label.className = 'wsp-variants__label';
			label.innerHTML = `<span class="wsp-variants__name"></span> <b class="wsp-variants__value"></b>`;
			label.querySelector('.wsp-variants__name').textContent = row.attribute;
			section.appendChild(label);
			const chips = document.createElement('div');
			chips.className = 'wsp-variants__chips';
			chips.setAttribute('role', 'radiogroup');
			chips.setAttribute('aria-label', row.attribute);
			row.values.forEach(value => {
				const chip = document.createElement('button');
				chip.type = 'button';
				chip.className = 'wsp-variants__chip' + (withPictures ? ' wsp-variants__chip--swatch' : '');
				chip.dataset.attribute = row.attribute;
				chip.dataset.value = value;
				chip.setAttribute('role', 'radio');
				chip.setAttribute('aria-checked', 'false');
				const picture = withPictures ? this.picture_for(row.attribute, value) : null;
				if (picture) {
					const img = document.createElement('img');
					img.src = picture; img.alt = ''; img.loading = 'lazy'; img.decoding = 'async';
					chip.appendChild(img);
				}
				const text = document.createElement('span');
				text.className = 'wsp-variants__chip-text';
				text.textContent = value;
				chip.appendChild(text);
				chips.appendChild(chip);
			});
			section.appendChild(chips);
			this.rows_host.appendChild(section);
		});
		// a single choice is no choice: take it
		this.rows.forEach(row => { if (row.values.length === 1) this.selection[row.attribute] = row.values[0]; });
		this.refresh_rows();
	}

	/** Each chip's state, given the current selection of the other attributes. */
	refresh_rows() {
		this.rows.forEach(row => {
			const others = Object.assign({}, this.selection);
			delete others[row.attribute];
			const section = this.rows_host.querySelector(`.wsp-variants__row[data-attribute="${CSS.escape(row.attribute)}"]`);
			section.querySelectorAll('.wsp-variants__chip').forEach(chip => {
				const value = chip.dataset.value;
				const candidates = this.matching(Object.assign({}, others, { [row.attribute]: value }));
				const possible = candidates.length > 0;
				const available = candidates.some(v => this.sellable(v));
				chip.classList.toggle('is-impossible', !possible);
				chip.classList.toggle('is-unavailable', possible && !available);
				chip.classList.toggle('is-selected', this.selection[row.attribute] === value);
				chip.setAttribute('aria-checked', this.selection[row.attribute] === value ? 'true' : 'false');
				chip.title = possible && !available ? __('Sold out') : '';
			});
			const chosen = section.querySelector('.wsp-variants__value');
			if (chosen) chosen.textContent = this.selection[row.attribute] || '';
		});
		this.resolve_selection();
	}

	/** When every attribute is chosen, the variant is known: the footer shows it. */
	resolve_selection() {
		const complete = this.rows.every(row => this.selection[row.attribute]);
		const match = complete ? this.matching(this.selection)[0] : null;
		this.selected_variant = match || null;
		this.update_selected_info();
	}

	choose(attribute, value) {
		if (this.selection[attribute] === value) {
			delete this.selection[attribute];
		} else {
			this.selection[attribute] = value;
			// a choice that leaves another attribute's pick impossible clears that pick
			this.rows.forEach(row => {
				if (row.attribute === attribute || !this.selection[row.attribute]) return;
				if (!this.matching(Object.assign({}, this.selection)).length) delete this.selection[row.attribute];
			});
		}
		this.refresh_rows();
		this.show_picture_for_selection();
	}

	/** The gallery's first picture follows the chosen variant's, when it has one. */
	show_picture_for_selection() {
		if (!window.wspGallery || !window.wspGallery.showImage) return;
		let picture = null;
		if (this.selected_variant && this.selected_variant.image) {
			picture = this.selected_variant.image;
		} else {
			for (const row of this.rows) {
				const value = this.selection[row.attribute];
				if (value && this.values_have_pictures(row.attribute)) { picture = this.picture_for(row.attribute, value); break; }
			}
		}
		window.wspGallery.showImage(picture);
	}

	setup_events() {
		const self = this;
		if (this.rows_host) {
			this.rows_host.addEventListener('click', function(e) {
				const chip = e.target.closest('.wsp-variants__chip');
				if (!chip || chip.classList.contains('is-impossible')) return;
				self.choose(chip.dataset.attribute, chip.dataset.value);
			});
		}
		// Add to cart handler
		//// Neoffice — the footer's own button, not the first .btn-add-to-cart of the
		//// document: the site chrome's cart drawer carries one too, and the grid bound
		//// its handler to that one — the click on "Add to cart" under the variants did
		//// nothing at all (2026-09-12).
		const addToCartBtn = document.querySelector('.variant-grid-footer .btn-add-to-cart');
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
		const baseItemName = this.item_name || '';
		const attrs = this.variants_data.attributes;
		const variant_parts = [];
		attrs.forEach(attr => {
			const value = this.selected_variant.attributes[attr.attribute];
			if (value) {
				variant_parts.push(`${value}`);
			}
		});
		if (variant_parts.length > 0) {
			return `${baseItemName} - ${variant_parts.join(' ')}`;
		}
		return baseItemName;
	}

	update_selected_info() {
		const footer = document.querySelector('.variant-grid-footer');
		if (!footer) return;
		// the chosen variant's code on the button, for whoever reads it (the browser tests do)
		const footerBtn = footer.querySelector('.btn-add-to-cart');
		if (footerBtn) {
			// no attribute at all while nothing is chosen: a code on the button means a
			// purchasable article, and the browser tests read it that way
			if (this.selected_variant) footerBtn.setAttribute('data-item-code', this.selected_variant.item_code);
			else footerBtn.removeAttribute('data-item-code');
		}

		if (this.selected_variant) {
			const attrs = this.variants_data.attributes;
			const variant_name_parts = [];
			attrs.forEach(attr => {
				const value = this.selected_variant.attributes[attr.attribute];
				if (value) {
					variant_name_parts.push(`${value}`);
				}
			});

			const nameElement = footer.querySelector('.selected-variant-name');
			if (nameElement) {
				nameElement.textContent = variant_name_parts.join(' · ');
			}

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
					priceElement.innerHTML = `<span class="text-muted">${__('Not Available')}</span>`;
				}
			}

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

			const addToCartBtn = footer.querySelector('.btn-add-to-cart');
			if (addToCartBtn) {
				if (this.selected_variant.in_stock && this.selected_variant.exists !== false && this.selected_variant.website_item) {
					addToCartBtn.style.display = 'inline-block';
				} else {
					addToCartBtn.style.display = 'none';
				}
			}

			footer.style.display = 'block';
		} else {
			footer.style.display = 'none';
		}
	}

	add_to_cart() {
		if (!this.selected_variant) return;

		const btn = document.querySelector('.variant-grid-footer .btn-add-to-cart');
		if (btn) {
			btn.disabled = true;
			btn.textContent = __('Adding...');
		}
		const reset = () => {
			if (btn) {
				btn.disabled = false;
				btn.textContent = __('Add to Cart');
			}
		};
		const done = (r) => {
			if (r.exc) { reset(); return; }
			if (typeof showMiniCartNotification === 'function') {
				showMiniCartNotification(this.selected_variant.item_code, 1, this.getVariantDisplayName(), this.selected_variant.image || '');
			} else {
				frappe.show_alert({ message: __('Added to cart'), indicator: 'green' });
			}
			if (r.message && r.message.shopping_cart_menu) {
				const cartMenu = document.querySelector('.shopping-cart-menu');
				if (cartMenu) {
					cartMenu.outerHTML = r.message.shopping_cart_menu;
				}
			}
			if (typeof refreshCart === 'function') {
				refreshCart(() => {
					if (typeof openCart === 'function') {
						setTimeout(() => { openCart(); }, 300);
					}
				});
			} else if (typeof openCart === 'function') {
				setTimeout(() => { openCart(); }, 300);
			}
			reset();
		};

		const shopping_cart = window.erpnext?.shopping_cart || window.webshop?.shopping_cart;
		if (shopping_cart && shopping_cart.update_cart) {
			shopping_cart.update_cart({ item_code: this.selected_variant.item_code, qty: 1, callback: done });
		} else {
			frappe.call({
				method: "webshop.webshop.shopping_cart.cart.update_cart",
				args: { item_code: this.selected_variant.item_code, qty: 1 },
				callback: done
			});
		}
	}
}
