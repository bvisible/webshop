// Check if webshop object exists
if (typeof webshop === 'undefined') {
    window.webshop = {};
}

// Define ProductSearch class
webshop.ProductSearchNoJQuery = class {
	constructor(opts) {
		/* Options: search_box_id (for custom search box) */
		// Remplace $.extend
		this.applyOptions(opts || {});
		this.MAX_RECENT_SEARCHES = 4;
		this.search_box_id = this.search_box_id || "#search-box-nojq";
		this.searchBox = document.querySelector(this.search_box_id);

		this.setupSearchDropDown();
		this.bindSearchAction();
		
		// Ensure dropdown is hidden on load
		if (this.search_dropdown) {
			this.search_dropdown.style.display = "none";
			this.search_dropdown.classList.add("hidden");
		}
	}

	// Replace $.extend
	applyOptions(opts) {
		for (let key in opts) {
			if (opts.hasOwnProperty(key)) {
				this[key] = opts[key];
			}
		}
	}

	setupSearchDropDown() {
		this.search_area = document.querySelector("#dropdownMenuSearchNoJQ");
		this.setupSearchResultContainer();
		this.populateRecentSearches();
	}

	bindSearchAction() {
		let me = this;

		// Show Search dropdown
		this.searchBox.addEventListener("focus", () => {
			this.search_dropdown.style.display = "flex";
			this.search_dropdown.classList.remove("hidden");
		});

		// If click occurs outside search input/results, hide results.
		// Click can happen anywhere on the page
		document.body.addEventListener("click", (e) => {
			let searchEvent = e.target.closest(this.search_box_id) !== null;
			let resultsEvent = e.target.closest('#search-results-container-nojq') !== null;
			let isResultHidden = this.search_dropdown.style.display === "none";

			if (!searchEvent && !resultsEvent && !isResultHidden) {
				this.search_dropdown.style.display = "none";
				this.search_dropdown.classList.add("hidden");
			}
		});

			// Process search input
		this.searchBox.addEventListener("input", (e) => {
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
					if (this.isEmptyObject(product_results) === false || this.isEmptyObject(category_results) === false) {
						me.setRecentSearches(query);
					}
				}
			});

			this.search_dropdown.style.display = "flex";
			this.search_dropdown.classList.remove("hidden");
		});

		// Handle Enter key to navigate to search results page
		this.searchBox.addEventListener("keypress", (e) => {
			if (e.key === "Enter") {
				e.preventDefault();
				let query = e.target.value.trim();
				if (query.length >= 3) {
					// Hide dropdown and navigate to all-products page with search parameter
					this.search_dropdown.style.display = "none";
					this.search_dropdown.classList.add("hidden");
					window.location.href = `/all-products?search=${encodeURIComponent(query)}`;
				}
			}
		});
	}

	// Remplace $.isEmptyObject
	isEmptyObject(obj) {
		if (!obj) return true;
		return Object.keys(obj).length === 0;
	}

	setupSearchResultContainer() {
		// Create dropdown element
		const dropdownElement = document.createElement('div');
		dropdownElement.className = "overflow-hidden shadow dropdown-menu w-100 hidden";
		dropdownElement.id = "search-results-container-nojq";
		dropdownElement.setAttribute("aria-labelledby", "dropdownMenuSearch");
		// Ensure dropdown is hidden initially
		dropdownElement.style.display = "none";
		dropdownElement.style.flexDirection = "column";
		
		// Add to DOM
		this.search_area.appendChild(dropdownElement);
		this.search_dropdown = dropdownElement;

		this.setupCategoryContainer();
		this.setupProductsContainer();
		this.setupRecentsContainer();
	}

	setupProductsContainer() {
		// Create elements
		const productResults = document.createElement('div');
		productResults.id = "product-results";
		productResults.className = "mt-2";
		
		const productScroll = document.createElement('div');
		productScroll.id = "product-scroll";
		productScroll.style.overflow = "scroll";
		productScroll.style.maxHeight = "300px";
		
		// Add to DOM
		productResults.appendChild(productScroll);
		this.search_dropdown.appendChild(productResults);
		this.products_container = productScroll;
	}

	setupCategoryContainer() {
		// Create elements
		const categoryContainer = document.createElement('div');
		categoryContainer.className = "category-container mt-2 mb-1";
		
		const categoryChips = document.createElement('div');
		categoryChips.className = "category-chips";
		
		// Add to DOM
		categoryContainer.appendChild(categoryChips);
		this.search_dropdown.appendChild(categoryContainer);
		this.category_container = categoryChips;
	}

	setupRecentsContainer() {
		// Create elements
		const recentsSection = document.createElement('div');
		recentsSection.className = "mb-2 mt-2 recent-searches";
		
		const titleDiv = document.createElement('div');
		const titleBold = document.createElement('b');
		titleBold.textContent = __("Recent");
		titleDiv.appendChild(titleBold);
		
		const recentsDiv = document.createElement('div');
		recentsDiv.id = "recents";
		recentsDiv.style.padding = ".25rem 0 1rem 0";
		
		// Add to DOM
		recentsSection.appendChild(titleDiv);
		recentsSection.appendChild(recentsDiv);
		this.search_dropdown.appendChild(recentsSection);
		this.recents_container = recentsDiv;
	}

	getRecentSearches() {
		return JSON.parse(localStorage.getItem("recent_searches") || "[]");
	}

	attachEventListenersToChips() {
		let me = this;
		const chips = document.querySelectorAll(".recent-search");

		for (let chip of chips) {
			chip.addEventListener("click", () => {
				me.searchBox.value = chip.innerText.trim();

				// Start search with `recent query`
				// Simulate input event
				const inputEvent = new Event('input', { bubbles: true });
				me.searchBox.dispatchEvent(inputEvent);
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
			this.recents_container.innerHTML = `<span class="text-muted">No searches yet.</span>`;
			return;
		}

		let html = "";
		recents.forEach((key) => {
			html += `
				<div class="recent-search mr-1" style="font-size: 13px">
					<span class="mr-2">
						<svg width="20" height="20" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
							<path d="M8 14C11.3137 14 14 11.3137 14 8C14 4.68629 11.3137 2 8 2C4.68629 2 2 4.68629 2 8C2 11.3137 4.68629 14 8 14Z" stroke="var(--gray-500)" stroke-miterlimit="10" stroke-linecap="round" stroke-linejoin="round"/>
							<path d="M8.00027 5.20947V8.00017L10 10" stroke="var(--gray-500)" stroke-miterlimit="10" stroke-linecap="round" stroke-linejoin="round"/>
						</svg>
					</span>
					${ key }
				</div>
			`;
		});

		this.recents_container.innerHTML = html;
		this.attachEventListenersToChips();
	}

	// Fetch product prices
	fetchProductPrices(products, callback) {
		if (!products || products.length === 0) {
			if (callback) callback();
			return;
		}
		
		// Create an array of item codes for the request
		const itemCodes = products.map(product => product.item_code);
		
		// Call the API to get price information
		frappe.call({
			method: "webshop.webshop.api.get_product_price_info",
			args: {
				items: itemCodes
			},
			callback: (data) => {
				if (data.message && Object.keys(data.message).length > 0) {
					// Add price information to products
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
			this.products_container.innerHTML = '';
			return;
		}

		let html = "";

		product_results.forEach((res) => {
			let thumbnail = res.thumbnail || '/assets/webshop/images/cart-empty-state.png';

			// Prepare price display
			let priceHtml = '';
			if (res.formatted_price) {
				priceHtml = `<div class="product-price">${res.formatted_price}`;

				// Add striked price and discount if available
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

			html += `
				<div class="dropdown-item" style="display: flex;">
					<img class="item-thumb col-2" src=${encodeURI(thumbnail)} />
					<div class="col-9" style="white-space: normal;">
						<a href="/${res.route}" class="product-name-result">${res.web_item_name}</a><br>
						<span class="brand-line">${res.brand ? "by " + res.brand : ""}</span>
						${priceHtml}
					</div>
				</div>
			`;
		});

		// Add "View all results" link
		const searchQuery = this.searchBox.value.trim();
		html += `
			<div class="see-all-results" style="padding: 10px 15px; border-top: 1px solid #ededed; text-align: center;">
				<a href="/all-products?search=${encodeURIComponent(searchQuery)}"
				   style="text-decoration: none; color: var(--primary, #007bff); font-weight: 500;">
					${__("View all results")} &rarr;
				</a>
			</div>
		`;

		this.products_container.innerHTML = html;
	}

	populateCategoriesList(category_results) {
		if (!category_results || category_results.length === 0) {
			let empty_html = `
				<div class="category-container mt-2">
					<div class="category-chips">
					</div>
				</div>
			`;
			this.category_container.innerHTML = empty_html;
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
				</a>
			`;
		});

		this.category_container.innerHTML = html;
	}
};
