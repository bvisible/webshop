webshop.ProductSearch = class {
	constructor(opts) {
		/* Options: search_box_id (for custom search box) */
		$.extend(this, opts);
		this.MAX_RECENT_SEARCHES = 4;
		this.search_box_id = this.search_box_id || "#search-box";
		this.searchBox = $(this.search_box_id);

		this.setupSearchDropDown();
		this.bindSearchAction();
	}

	setupSearchDropDown() {
		this.search_area = $("#dropdownMenuSearch");
		this.setupSearchResultContainer();
		this.populateRecentSearches();
	}

	bindSearchAction() {
		let me = this;

		// Show Search dropdown
		this.searchBox.on("focus", () => {
			this.search_dropdown.removeClass("hidden");
		});

		// If click occurs outside search input/results, hide results.
		// Click can happen anywhere on the page
		$("body").on("click", (e) => {
			let searchEvent = $(e.target).closest(this.search_box_id).length;
			let resultsEvent = $(e.target).closest('#search-results-container').length;
			let isResultHidden = this.search_dropdown.hasClass("hidden");

			if (!searchEvent && !resultsEvent && !isResultHidden) {
				this.search_dropdown.addClass("hidden");
			}
		});

		// Process search input
		this.searchBox.on("input", (e) => {
			let query = e.target.value;

			if (query.length == 0) {
				me.populateResults(null);
				me.populateCategoriesList(null);
			}

			if (query.length < 3 || !query.length) return;

			frappe.call({
				method: "webshop.templates.pages.product_search.search",
				args: {
					query: query
				},
				callback: (data) => {
					let product_results = null, category_results = null;

					// Populate product results
					product_results = data.message ? data.message.product_results : null;
//// Neoffice — the dropdown shows prices, which upstream's search does not return:
//// the results are enriched by a second call before being rendered (see
//// fetchProductPrices below). 48e2708353, 2025-03-13.
//// TO REVIEW: the comments in this file are in French (RULE #00).

					// Si nous avons des résultats de produits, récupérer les informations de prix
					if (product_results && product_results.length > 0) {
						me.fetchProductPrices(product_results, () => {
							me.populateResults(product_results);
						});
					} else {
						me.populateResults(product_results);
					}

					// Populate categories
					if (me.category_container) {
						category_results = data.message ? data.message.category_results : null;
						me.populateCategoriesList(category_results);
					}

					// Populate recent search chips only on successful queries
					if (!$.isEmptyObject(product_results) || !$.isEmptyObject(category_results)) {
						me.setRecentSearches(query);
					}
				}
			});

			this.search_dropdown.removeClass("hidden");
		});
//// Neoffice — added: Enter goes to the full results page rather than doing
//// nothing, which is what a buyer expects from a search box (912d29f1f4,
//// 2025-12-14). keydown, not keypress: keypress does not fire for Enter in every
//// browser (837f5904f8, 2025-12-14).

		// Handle Enter key to navigate to search results page
		this.searchBox.on("keydown", (e) => {
			if (e.key === "Enter" || e.keyCode === 13) {
				e.preventDefault();
				e.stopPropagation();
				let query = e.target.value.trim();
				if (query.length >= 1) {
					// Hide dropdown and navigate to all-products page with search parameter
					this.search_dropdown.addClass("hidden");
					window.location.href = `/all-products?search=${encodeURIComponent(query)}`;
				}
			}
		});
	}

	setupSearchResultContainer() {
		this.search_dropdown = this.search_area.append(`
			<div class="overflow-hidden shadow dropdown-menu w-100 hidden"
				id="search-results-container"
				aria-labelledby="dropdownMenuSearch"
				style="display: flex; flex-direction: column;">
			</div>
		`).find("#search-results-container");

		this.setupCategoryContainer();
		this.setupProductsContainer();
		this.setupRecentsContainer();
	}

	setupProductsContainer() {
		this.products_container = this.search_dropdown.append(`
			<div id="product-results mt-2">
				<div id="product-scroll" style="overflow: scroll; max-height: 300px">
				</div>
			</div>
		`).find("#product-scroll");
	}

	setupCategoryContainer() {
		this.category_container = this.search_dropdown.append(`
			<div class="category-container mt-2 mb-1">
				<div class="category-chips">
				</div>
			</div>
		`).find(".category-chips");
	}

	setupRecentsContainer() {
		let $recents_section = this.search_dropdown.append(`
			<div class="mb-2 mt-2 recent-searches">
				<div>
					<b>${ __("Recent") }</b>
				</div>
			</div>
		`).find(".recent-searches");

		this.recents_container = $recents_section.append(`
			<div id="recents" style="padding: .25rem 0 1rem 0;">
			</div>
		`).find("#recents");
	}

	getRecentSearches() {
		return JSON.parse(localStorage.getItem("recent_searches") || "[]");
	}

	attachEventListenersToChips() {
		let me  = this;
		const chips = $(".recent-search");
		window.chips = chips;

		for (let chip of chips) {
			chip.addEventListener("click", () => {
				me.searchBox[0].value = chip.innerText.trim();

				// Start search with `recent query`
				me.searchBox.trigger("input");
				me.searchBox.focus();
			});
		}
	}

	setRecentSearches(query) {
		let recents = this.getRecentSearches();
		if (recents.length >= this.MAX_RECENT_SEARCHES) {
			// Remove the `first` query
			recents.splice(0, 1);
		}

		if (recents.indexOf(query) >= 0) {
			return;
		}

		recents.push(query);
		localStorage.setItem("recent_searches", JSON.stringify(recents));

		this.populateRecentSearches();
	}

	populateRecentSearches() {
		let recents = this.getRecentSearches();

		if (!recents.length) {
			this.recents_container.html(`<span class=""text-muted">${ __("No searches yet.") }</span>`);
			return;
		}

		let html = "";
		recents.forEach((key) => {
			html += `
				<div class="recent-search mr-1" style="font-size: 13px">
					<span class="mr-2">
						<svg width="20" height="20" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
							<path d="M8 14C11.3137 14 14 11.3137 14 8C14 4.68629 11.3137 2 8 2C4.68629 2 2 4.68629 2 8C2 11.3137 4.68629 14 8 14Z" stroke="var(--gray-500)"" stroke-miterlimit="10" stroke-linecap="round" stroke-linejoin="round"/>
							<path d="M8.00027 5.20947V8.00017L10 10" stroke="var(--gray-500)" stroke-miterlimit="10" stroke-linecap="round" stroke-linejoin="round"/>
						</svg>
					</span>
					${ key }
				</div>
			`;
		});

		this.recents_container.html(html);
		this.attachEventListenersToChips();
	}

	//// Neoffice — added: prices for the dropdown results, in one call for the whole
	//// page of results. A failure calls back anyway, so the dropdown still shows the
	//// products without their price.
	// Récupérer les informations de prix pour les produits
	fetchProductPrices(products, callback) {
		if (!products || products.length === 0) {
			if (callback) callback();
			return;
		}
		
		// Créer un tableau des codes d'articles pour la requête
		const itemCodes = products.map(product => product.item_code);
		
		// Appeler l'API pour obtenir les informations de prix
		frappe.call({
			method: "webshop.webshop.api.get_product_price_info",
			args: {
				items: itemCodes
			},
			callback: (data) => {
				if (data.message && Object.keys(data.message).length > 0) {
					// Ajouter les informations de prix aux produits
					products.forEach(product => {
						if (data.message[product.item_code]) {
							const priceInfo = data.message[product.item_code];
							product.formatted_price = priceInfo.formatted_price || '';
							product.formatted_mrp = priceInfo.formatted_mrp || '';
							product.discount = priceInfo.discount || '';
						}
					});
				}
				
				if (callback) callback();
			},
			error: () => {
				if (callback) callback();
			}
		});
	}

	populateResults(product_results) {
		if (!product_results || product_results.length === 0) {
			//// Neoffice — upstream empties the container silently when nothing matches, so the
			//// buyer could not tell a slow search from an empty one. Says so instead, above
			//// three characters (4ab27b43f4, 2025-12-14).
			// Show "no results" message only if there's a search query
			const searchQuery = this.searchBox.val().trim();
			if (searchQuery.length >= 3) {
				let empty_html = `
					<div class="no-results-message" style="padding: 20px; text-align: center; color: var(--gray-600);">
						<div style="font-size: 24px; margin-bottom: 10px;">🔍</div>
						<div>${__("No products found for")} "<strong>${frappe.utils.escape_html(searchQuery)}</strong>"</div>
						<div style="font-size: 12px; margin-top: 5px; color: var(--gray-500);">
							${__("Try a different search term")}
						</div>
					</div>
				`;
				this.products_container.html(empty_html);
			} else {
				this.products_container.html('');
			}
			return;
		}

		let html = "";

		//// Neoffice — the price, its struck-through list price and the discount, rendered
		//// from what fetchProductPrices added.
		product_results.forEach((res) => {
			let thumbnail = res.thumbnail || '/assets/webshop/images/cart-empty-state.png';

			// Préparer l'affichage du prix
			let priceHtml = '';
			if (res.formatted_price) {
				priceHtml = `<div class="product-price">${res.formatted_price}`;

				// Ajouter le prix barré et la réduction si disponibles
				if (res.formatted_mrp) {
					priceHtml += `
						<small class="striked-price">
							<s>${res.formatted_mrp.replace(/ +/g, "")}</s>
						</small>
						<small class="ml-1 product-info-green">
							- ${res.discount}
						</small>
					`;
				}

				priceHtml += '</div>';
			} else if (res.price_stock_uom) {
				priceHtml = `<div class="product-price">${res.price_stock_uom}</div>`;
			}

			//// Neoffice — the result title gets a class so the shop can style it.
			//// Neoffice — the price block in the result row (see #5).
			html += `
				<div class="dropdown-item" style="display: flex;">
					<img class="item-thumb col-2" src=${encodeURI(thumbnail)} />
					<div class="col-9" style="white-space: normal;">
						<a class="product-name-result" href="/${res.route}">${res.web_item_name}</a><br>
						<span class="brand-line">${res.brand ? "by " + res.brand : ""}</span>
						${priceHtml}
					</div>
				</div>
			`;
		});

		//// Neoffice — added: a "View all results" link to the full listing; upstream's
		//// dropdown is a dead end (912d29f1f4, 2025-12-14).
		// Add "View all results" link
		const searchQuery = this.searchBox.val().trim();
		html += `
			<div class="see-all-results" style="padding: 10px 15px; border-top: 1px solid #ededed; text-align: center;">
				<a href="/all-products?search=${encodeURIComponent(searchQuery)}"
				   style="text-decoration: none; color: var(--primary, #007bff); font-weight: 500;">
					${__("View all results")} &rarr;
				</a>
			</div>
		`;

		this.products_container.html(html);
	}

	populateCategoriesList(category_results) {
		if (!category_results || category_results.length === 0) {
			let empty_html = `
				<div class="category-container mt-2">
					<div class="category-chips">
					</div>
				</div>
			`;
			this.category_container.html(empty_html);
			return;
		}

		let html = `
			<div class="mb-2">
				<b>${ __("Categories") }</b>
			</div>
		`;

		category_results.forEach((category) => {
			html += `
				<a href="/${category.route}" class="btn btn-sm category-chip mr-2 mb-2"
					style="font-size: 13px" role="button">
				${ category.name }
				</button>
			`;
		});

		this.category_container.html(html);
	}
};
