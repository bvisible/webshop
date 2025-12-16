webshop.ProductView =  class {
	/* Options:
		- View Type
		- Products Section Wrapper,
		- Item Group: If its an Item Group page
	*/
	constructor(options) {
		Object.assign(this, options);
		this.preference = this.view_type;
		this.total_product_count = null;  // Initialize to null to detect first load
		this.stock_filter_default = options.stock_filter_default || false;
		
		// Initialize sort order early
		this.current_sort = localStorage.getItem('product_sort_order') || 
			(window.product_settings && window.product_settings.default_product_sort) || 
			'relevance';
		
		// Check URL parameters for discount filter and sort order
		const urlParams = new URLSearchParams(window.location.search);
		
		// Handle discount filter from URL
		if (urlParams.get('discount') === 'true') {
			// Set discount filter in localStorage when coming from URL
			localStorage.setItem('discount_filter_checked', 'true');
			// Also ensure stock filter is set to false if not already set
			if (localStorage.getItem('stock_filter_checked') === null) {
				localStorage.setItem('stock_filter_checked', 'false');
			}
			// Remove the discount parameter from URL to avoid confusion
			urlParams.delete('discount');
		}
		
		// Handle sort order from URL
		if (urlParams.get('sort') === 'new_arrivals') {
			// Set sort order in localStorage when coming from URL
			localStorage.setItem('product_sort_order', 'new_arrivals');
			this.current_sort = 'new_arrivals';
			// Remove the sort parameter from URL to avoid confusion
			urlParams.delete('sort');
		}
		
		// Update URL if parameters were removed
		if (urlParams.get('discount') === null && urlParams.get('sort') === null) {
			const newUrl = window.location.pathname + (urlParams.toString() ? '?' + urlParams.toString() : '');
			window.history.replaceState({}, '', newUrl);
		}
		
		// Initialize stock filter preference if not set
		if (localStorage.getItem('stock_filter_checked') === null && localStorage.getItem('discount_filter_checked') === 'true') {
			// If discount filter is active and stock filter has no preference, set it to false
			localStorage.setItem('stock_filter_checked', 'false');
		}
		
		this.load_settings();
		
		// Initialize preloaded results cache
		this.preloaded_discount_results = null;
		this.preload_in_progress = false;
	}

	load_settings() {
		frappe.call({
			method: 'webshop.webshop.doctype.webshop_settings.webshop_settings.get_shopping_cart_settings',
			callback: (r) => {
				if (r.message) {
					const savedView = localStorage.getItem("product_view");
					const defaultView = r.message.default_view_type;
					
					if (savedView) {
						this.preference = savedView;
					} else if (defaultView) {
						this.preference = defaultView + " View";
						localStorage.setItem("product_view", this.preference);
					} else {
						this.preference = "Grid View";
						localStorage.setItem("product_view", this.preference);
					}
					
					this.make();
				}
			}
		});
	}

	make(from_filters=false) {
		// Don't empty products_section immediately - keep existing products visible during loading
		// Only empty on initial load (when there are no products yet)
		const hasExistingProducts = $('#products-grid-area').length || $('#products-list-area').length;

		if (!hasExistingProducts) {
			// Initial load - empty the section
			this.products_section.empty();
		}

		// Reset infinite scroll state when filters change or on initial load
		if (from_filters || !this.infinite_scroll_state) {
			this.infinite_scroll_state = null;
			if (this.infinite_scroll_observer) {
				this.infinite_scroll_observer.disconnect();
				this.infinite_scroll_observer = null;
			}
		}

		// Only prepare toolbar on initial load
		if (!hasExistingProducts) {
			this.prepare_toolbar();
		}

		this.get_item_filter_data(from_filters);
	}

	update_page_header_for_search() {
		// Update page header and breadcrumb when search term is present
		if (!this.search_term) return;

		const translations = window.product_translations || {};
		const searchLabel = translations["Search"] || "Search";
		const searchText = `${searchLabel}: "${this.search_term}"`;

		// Update main page header (first div inside .mb-6 header section)
		const $header = $('.mb-6.d-flex > div:first-child');
		if ($header.length && !$header.hasClass('search-updated')) {
			$header.text(searchText);
			$header.addClass('search-updated');
		}

		// Update document title
		document.title = searchText;

		// Update breadcrumb - add search item after Shop
		const $breadcrumbList = $('nav[aria-label="breadcrumb"] ol.breadcrumb');
		if ($breadcrumbList.length && !$breadcrumbList.hasClass('search-updated')) {
			// Add search breadcrumb item at the end
			const position = $breadcrumbList.find('li').length + 1;
			$breadcrumbList.append(`
				<li itemprop="itemListElement" itemscope itemtype="http://schema.org/ListItem" class="breadcrumb-item active" aria-current="page">
					<span itemprop="item">
						<span itemprop="name">${searchText}</span>
						<meta itemprop="position" content="${position}"/>
					</span>
				</li>
			`);
			$breadcrumbList.addClass('search-updated');
		}

		// Pre-fill search box with search term
		const $searchBox = $('#search-box');
		if ($searchBox.length && !$searchBox.val()) {
			$searchBox.val(this.search_term);
		}

		// Also update the no-jquery search box if present
		const $searchBoxNoJq = $('#search-box-nojq');
		if ($searchBoxNoJq.length && !$searchBoxNoJq.val()) {
			$searchBoxNoJq.val(this.search_term);
		}
	}

	prepare_toolbar() {
		this.products_section.append(`
			<div class="toolbar d-flex flex-column flex-md-row align-items-center">
			</div>
		`);
		// On mobile: sort first, then search, then view toggles
		// On desktop: search, view toggles, sort
		this.prepare_search();
		this.prepare_view_toggler();
		this.prepare_sort_selector();
		this.prepare_active_filters_display();

		new webshop.ProductSearch();
	}
	
	prepare_active_filters_display() {
		// Add a section to show active filters
		this.products_section.append(`
			<div class="active-filters-display mt-2 mb-2" style="display: none;">
				<div class="d-flex align-items-center flex-wrap" style="gap: 0.5rem;">
					<small class="text-muted mr-2">Active filters:</small>
					<div class="active-filter-badges d-flex flex-wrap" style="gap: 0.5rem;"></div>
				</div>
			</div>
		`);
	}
	
	update_active_filters_display() {
		const $display = $('.active-filters-display');
		const $badges = $('.active-filter-badges');
		$badges.empty();

		let hasActiveFilters = false;
		const self = this;

		// Check localStorage filters
		const stockFilter = localStorage.getItem('stock_filter_checked') === 'true';
		const discountFilter = localStorage.getItem('discount_filter_checked') === 'true';
		const translations = window.product_translations || {};

		if (stockFilter) {
			hasActiveFilters = true;
			$badges.append(`
				<span class="badge badge-info active-filter-badge" data-filter-type="stock" style="cursor: pointer;">
					<i class="fa fa-check"></i> ${translations["In Stock Only"] || "In Stock Only"}
					<i class="fa fa-times ml-1"></i>
				</span>
			`);
		}

		if (discountFilter) {
			hasActiveFilters = true;
			$badges.append(`
				<span class="badge badge-warning active-filter-badge" data-filter-type="discount" style="cursor: pointer;">
					<i class="fa fa-tag"></i> ${translations["Discounted Only"] || "Discounted Only"}
					<i class="fa fa-times ml-1"></i>
				</span>
			`);
		}

		// Parse URL filters (field_filters, attribute_filters)
		const urlParams = frappe.utils.get_query_params();

		// Field filters from URL
		if (urlParams.field_filters) {
			try {
				const fieldFilters = JSON.parse(decodeURIComponent(urlParams.field_filters));
				for (let fieldName in fieldFilters) {
					const values = fieldFilters[fieldName];
					if (Array.isArray(values)) {
						values.forEach(value => {
							hasActiveFilters = true;
							// Get display label from checkbox if available
							const $checkbox = $(`input[data-filter-name="${fieldName}"][data-filter-value="${value}"]`);
							const displayLabel = $checkbox.length ? $checkbox.next('label').text().trim() || value : value;
							$badges.append(`
								<span class="badge badge-secondary active-filter-badge" data-filter-type="field" data-filter-name="${fieldName}" data-filter-value="${value}" style="cursor: pointer;">
									${displayLabel}
									<i class="fa fa-times ml-1"></i>
								</span>
							`);
						});
					}
				}
			} catch (e) {
				console.error("Error parsing field_filters for display:", e);
			}
		}

		// Attribute filters from URL
		if (urlParams.attribute_filters) {
			try {
				const attrFilters = JSON.parse(decodeURIComponent(urlParams.attribute_filters));
				for (let attrName in attrFilters) {
					const values = attrFilters[attrName];
					if (Array.isArray(values)) {
						values.forEach(value => {
							hasActiveFilters = true;
							$badges.append(`
								<span class="badge badge-primary active-filter-badge" data-filter-type="attribute" data-filter-name="${attrName}" data-filter-value="${value}" style="cursor: pointer;">
									${attrName}: ${value}
									<i class="fa fa-times ml-1"></i>
								</span>
							`);
						});
					}
				}
			} catch (e) {
				console.error("Error parsing attribute_filters for display:", e);
			}
		}

		// Price range from URL
		if (urlParams.price_range) {
			try {
				const priceRange = JSON.parse(decodeURIComponent(urlParams.price_range));
				if (priceRange.min || priceRange.max) {
					hasActiveFilters = true;
					const minLabel = priceRange.min ? priceRange.min : '0';
					const maxLabel = priceRange.max ? priceRange.max : '∞';
					$badges.append(`
						<span class="badge badge-success active-filter-badge" data-filter-type="price" style="cursor: pointer;">
							<i class="fa fa-money"></i> ${minLabel} - ${maxLabel}
							<i class="fa fa-times ml-1"></i>
						</span>
					`);
				}
			} catch (e) {
				console.error("Error parsing price_range for display:", e);
			}
		}

		// Bind click handlers for removal
		$badges.find('.active-filter-badge').off('click').on('click', function() {
			self.remove_active_filter($(this));
		});

		// Show/hide the display based on active filters
		if (hasActiveFilters) {
			$display.show();
		} else {
			$display.hide();
		}
	}

	remove_active_filter($badge) {
		const filterType = $badge.data('filter-type');
		const filterName = $badge.data('filter-name');
		const filterValue = $badge.data('filter-value');

		if (filterType === 'stock') {
			// Remove stock filter
			localStorage.setItem('stock_filter_checked', 'false');
			// The stock-filter class is ON the input itself, not a parent wrapper
			$('input.stock-filter').prop('checked', false);
			if (this.field_filters && this.field_filters['in_stock']) {
				delete this.field_filters['in_stock'];
			}
		} else if (filterType === 'discount') {
			// Remove discount filter
			localStorage.setItem('discount_filter_checked', 'false');
			// The discount-filter class is ON the input itself, not a parent wrapper
			$('input.discount-filter').prop('checked', false);
			if (this.field_filters && this.field_filters['discount']) {
				delete this.field_filters['discount'];
			}
		} else if (filterType === 'field') {
			// Remove field filter
			if (this.field_filters && this.field_filters[filterName]) {
				const idx = this.field_filters[filterName].indexOf(filterValue);
				if (idx > -1) {
					this.field_filters[filterName].splice(idx, 1);
				}
				if (this.field_filters[filterName].length === 0) {
					delete this.field_filters[filterName];
				}
			}
			// Uncheck the checkbox
			$(`input[data-filter-name="${filterName}"][data-filter-value="${filterValue}"]`).prop('checked', false);
		} else if (filterType === 'attribute') {
			// Remove attribute filter
			if (this.attribute_filters && this.attribute_filters[filterName]) {
				const idx = this.attribute_filters[filterName].indexOf(filterValue);
				if (idx > -1) {
					this.attribute_filters[filterName].splice(idx, 1);
				}
				if (this.attribute_filters[filterName].length === 0) {
					delete this.attribute_filters[filterName];
				}
			}
			// Uncheck the checkbox
			$(`input[data-attribute-name="${filterName}"][data-attribute-value="${filterValue}"]`).prop('checked', false);
		} else if (filterType === 'price') {
			// Clear price range
			this.price_range = {};
			$('#min-price').val('');
			$('#max-price').val('');
		}

		// Refresh products with updated filters
		this.from_filters = true;
		this.change_route_with_filters();
	}

	prepare_view_toggler() {

		if (!$("#list").length || !$("#grid").length) {
			this.render_view_toggler();
			this.bind_view_toggler_actions();
			this.set_view_state();
		}
	}
	
	prepare_sort_selector() {
		// Get saved sort order or use default from settings
		const saved_sort = localStorage.getItem('product_sort_order') || 
			(window.product_settings && window.product_settings.default_product_sort) || 
			'relevance';
		
		this.current_sort = saved_sort;
		
		// Use translations from window.product_translations
		const translations = window.product_translations || {};
		const sortByLabel = translations["Sort by:"] || "Sort by:";
		const mostRelevant = translations["Most Relevant"] || "Most Relevant";
		const priceLowToHigh = translations["Price: Low to High"] || "Price: Low to High";
		const priceHighToLow = translations["Price: High to Low"] || "Price: High to Low";
		const newArrivals = translations["New Arrivals"] || "New Arrivals";
		const customerRating = translations["Customer Rating"] || "Customer Rating";
		
		// Add sort selector to toolbar (not toggle-container)
		$(".toolbar").append(`
			<div class="sort-selector-container ml-md-auto d-flex align-items-center mb-2 mb-md-0">
				<label class="mb-0 mr-2 text-muted small d-none d-sm-block">${sortByLabel}</label>
				<div class="d-flex align-items-center">
					<svg class="icon icon-sm mr-1 d-sm-none text-muted" style="width: 16px; height: 16px;">
						<use href="#icon-sort"></use>
					</svg>
					<select class="form-control form-control-sm" id="product-sort-selector" style="width: auto; max-width: 200px;">
						<option value="relevance" ${saved_sort === 'relevance' ? 'selected' : ''}>${mostRelevant}</option>
						<option value="price_low_to_high" ${saved_sort === 'price_low_to_high' ? 'selected' : ''}>${priceLowToHigh}</option>
						<option value="price_high_to_low" ${saved_sort === 'price_high_to_low' ? 'selected' : ''}>${priceHighToLow}</option>
						<option value="new_arrivals" ${saved_sort === 'new_arrivals' ? 'selected' : ''}>${newArrivals}</option>
						<option value="rating" ${saved_sort === 'rating' ? 'selected' : ''}>${customerRating}</option>
					</select>
				</div>
			</div>
		`);
		
		// Bind change event
		$('#product-sort-selector').on('change', (e) => {
			const new_sort = $(e.target).val();
			this.current_sort = new_sort;
			
			// Save preference
			localStorage.setItem('product_sort_order', new_sort);
			
			// Reload products with new sort
			this.get_item_filter_data(true);
		});
	}

	get_item_filter_data(from_filters=false) {
		// Get and render all Product related views
		let me = this;
		this.from_filters = from_filters;
		let args = this.get_query_filters();

		// Update page header for search (if search term present)
		this.update_page_header_for_search();

		this.disable_view_toggler(true);
		this.show_product_loader();

		frappe.call({
			method: "webshop.webshop.api.get_product_filter_data",
			args: {
				query_args: args
			},
			callback: function(result) {
				if (!result || result.exc || !result.message || result.message.exc) {
					me.hide_product_loader();
					me.render_no_products_section(true);
				} else {					
					// Sub Category results are independent of Items
					if (me.item_group && result.message["sub_categories"] && result.message["sub_categories"].length) {
						me.render_item_sub_categories(result.message["sub_categories"]);
					}

					// Always render discount filters
					me.re_render_discount_filters();
					
					// Update price filter range if available
					if (result.message.filters && result.message.filters.price_filters) {
						me.update_price_filter_range(result.message.filters.price_filters);
					} 

					// Clean up any existing no-products section before rendering
					$('.cart-empty').remove();
					
					if (!result.message["items"].length) {
						// if result has no items or result is empty
						me.hide_product_loader();
						me.render_no_products_section();
					} else {
						// Store products before rendering
						me.products = result.message["items"];
						me.product_count = result.message["items_count"];
						me.total_count = result.message["total_count"];  // Utilisation du nouveau total
						me.settings = result.message["settings"];  // Store settings for later use
						
						// Hide loader after storing products
						me.hide_product_loader();
						
						// Render views
						me.render_list_view(result.message["items"], result.message["settings"]);
						me.render_grid_view(result.message["items"], result.message["settings"]);

						// Store total product count on first load
						if (me.total_product_count === null) {
							me.total_product_count = result.message.total_products || me.product_count;
						}
					}

					// Bind filter actions
					if (!from_filters) {
						// If `get_product_filter_data` was triggered after checking a filter,
						// don't touch filters unnecessarily, only data must change
						// filter persistence is handle on filter change event
						me.bind_filters();
						me.restore_filters_state();
					} else {
						// Always restore discount checkbox state from localStorage
						const saved_discount_preference = localStorage.getItem('discount_filter_checked');
						if (saved_discount_preference !== null) {
							$('#showDiscountOnly').prop('checked', saved_discount_preference === 'true');
						}
					}

					// Bottom paging
					me.add_paging_section(result.message["settings"]);
					
					// Update active filters display
					me.update_active_filters_display();
				}

				me.disable_view_toggler(false);
			}
		});
	}

	disable_view_toggler(disable=false) {
		$('#list').prop('disabled', disable);
		$('#grid').prop('disabled', disable);
	}

	render_grid_view(items, settings) {
		// loop over data and add grid html to it
		let me = this;

		this.prepare_product_area_wrapper("grid");

		new webshop.ProductGrid({
			items: items,
			products_section: $("#products-grid-area"),
			settings: settings,
			preference: me.preference
		});
	}

	render_list_view(items, settings) {
		let me = this;

		this.prepare_product_area_wrapper("list");

		new webshop.ProductList({
			items: items,
			products_section: $("#products-list-area"),
			settings: settings,
			preference: me.preference
		});
	}

	prepare_product_area_wrapper(view) {
		// Check if the area already exists - if so, just clear it and return
		const existingArea = $(`#products-${view}-area`);
		if (existingArea.length) {
			existingArea.empty();
			return existingArea;
		}

		// Create new area only if it doesn't exist
		let left_margin = view == "list" ? "ml-2" : "";
		let top_margin = view == "list" ? "mt-2" : "mt-minus-1";
		return this.products_section.append(`
			<div id="products-${view}-area" class="row products-list ${ top_margin } ${ left_margin }" itemscope itemtype="https://schema.org/Product"></div>
		`);
	}

	get_query_filters() {
		const filters = frappe.utils.get_query_params();
		let {field_filters, attribute_filters, price_range} = filters;

		// Safe parsing with proper decoding for mobile compatibility
		try {
			field_filters = field_filters ? JSON.parse(decodeURIComponent(field_filters)) : {};
		} catch (e) {
			console.error("Error parsing field_filters:", e);
			// Try without decoding as fallback
			try {
				field_filters = field_filters ? JSON.parse(field_filters) : {};
			} catch (e2) {
				console.error("Error parsing field_filters (fallback):", e2);
				field_filters = {};
			}
		}
		
		try {
			attribute_filters = attribute_filters ? JSON.parse(decodeURIComponent(attribute_filters)) : {};
		} catch (e) {
			console.error("Error parsing attribute_filters:", e);
			// Try without decoding as fallback
			try {
				attribute_filters = attribute_filters ? JSON.parse(attribute_filters) : {};
			} catch (e2) {
				console.error("Error parsing attribute_filters (fallback):", e2);
				attribute_filters = {};
			}
		}
		
		// Always check localStorage for stock/discount filters
		// These are managed separately from URL filters
		const saved_stock_preference = localStorage.getItem('stock_filter_checked');
		const saved_discount_preference = localStorage.getItem('discount_filter_checked');
		
		// For stock filter
		if (saved_stock_preference !== null) {
			if (saved_stock_preference === 'true') {
				field_filters["in_stock"] = ["1"];
			}
		} else if (Object.keys(field_filters).length === 0 && !this.from_filters && saved_discount_preference !== 'true') {
			// Only apply default if no saved preference, no other filters active, and discount is not active
			if (this.stock_filter_default) {
				field_filters["in_stock"] = ["1"];
			}
		}
		
		// For discount filter - always respect localStorage
		if (saved_discount_preference === 'true') {
			field_filters["discount"] = ["100"];
		}
		
		// Retrieve the price_range parameter from the URL
		if (price_range) {
			try {
				this.price_range = JSON.parse(decodeURIComponent(price_range));
			} catch (e) {
				console.error("Error parsing price_range parameter:", e);
				// Try without decoding as fallback
				try {
					this.price_range = JSON.parse(price_range);
				} catch (e2) {
					console.error("Error parsing price_range (fallback):", e2);
					this.price_range = {};
				}
			}
		}

		// Get search parameter from URL
		const search = filters.search || null;

		// Store search term for later use (title update, search box prefill)
		this.search_term = search;

		const result = {
			field_filters: field_filters,
			attribute_filters: attribute_filters,
			item_group: this.item_group,
			start: filters.start || null,
			from_filters: this.from_filters || false,
			price_range: price_range || null, // Add the price_range parameter to the query
			sort_order: this.current_sort || 'relevance', // Add sort order
			search: search // Add search parameter to the query
		};
		return result;
	}

	add_paging_section(settings) {
		$(".product-paging-area").remove();
		$(".infinite-scroll-loader").remove();

		// Reset infinite scroll state when paging section is rebuilt (e.g., after filter change)
		if (this.infinite_scroll_observer) {
			this.infinite_scroll_observer.disconnect();
			this.infinite_scroll_observer = null;
		}
		this.infinite_scroll_state = null;

		if (!this.products) return;

		// Check if infinite scroll is enabled
		if (settings.enable_infinite_scroll) {
			this.add_infinite_scroll(settings);
			return;
		}

		let query_params = frappe.utils.get_query_params();
		let start = query_params.start ? cint(JSON.parse(query_params.start)) : 0;
		let page_length = settings.products_per_page || 0;
		let current_page = Math.floor(start / page_length) + 1;
		let total_count = this.total_count || this.product_count;

		let total_pages = Math.ceil(total_count / page_length);
		
		// Check if discount filter is active
		const saved_discount_preference = localStorage.getItem('discount_filter_checked');
		const discount_filter_active = saved_discount_preference === 'true';
		
		// If discount filter is active, handle special cases
		if (discount_filter_active) {
			// If we have no products and we're not on the first page, redirect to first page
			if (this.products.length === 0 && start > 0) {
				const translations = window.product_translations || {};
				frappe.show_alert({
					message: translations["No more discounted products. Returning to first page."] || "No more discounted products. Returning to first page.",
					indicator: 'orange'
				});
				setTimeout(() => {
					window.location.search = this.get_query_string({});
				}, 2000);
				return;
			}
			
			// If we have fewer items than expected, adjust display
			if (this.products.length < page_length && total_pages > current_page) {
				// This might be the last page with discount items
				total_pages = current_page;
			}
		}
		
		let paging_html = `
			<div class="row product-paging-area mt-5">
				<div class="col-12 text-center">
					<div class="btn-group">
		`;

		// Previous button (except for first page)
		if (current_page > 1) {
			paging_html += `
				<button class="btn btn-default btn-prev" data-start="${(current_page - 2) * page_length}">
					<svg class="es-icon icon-xs"><use href="#icon-left"></use></svg>
				</button>`;
		}

		// Only show limited page numbers for better UX
		let max_visible_pages = 7;
		let half_visible = Math.floor(max_visible_pages / 2);
		let start_page = Math.max(1, current_page - half_visible);
		let end_page = Math.min(total_pages, start_page + max_visible_pages - 1);
		
		// Adjust start_page if we're near the end
		if (end_page - start_page < max_visible_pages - 1) {
			start_page = Math.max(1, end_page - max_visible_pages + 1);
		}

		// First page and ellipsis if needed
		if (start_page > 1) {
			paging_html += `
				<button class="btn btn-default btn-page" data-start="0">1</button>`;
			if (start_page > 2) {
				paging_html += `<span class="btn btn-default disabled">...</span>`;
			}
		}

		// Show page numbers
		for (let i = start_page; i <= end_page; i++) {
			let is_current = i === current_page;
			let page_start = (i - 1) * page_length;
			paging_html += `
				<button class="btn btn-default btn-page ${is_current ? 'btn-primary' : ''}" 
					data-start="${page_start}" ${is_current ? 'disabled' : ''}>
					${i}
				</button>`;
		}

		// Last page and ellipsis if needed
		if (end_page < total_pages) {
			if (end_page < total_pages - 1) {
				paging_html += `<span class="btn btn-default disabled">...</span>`;
			}
			paging_html += `
				<button class="btn btn-default btn-page" data-start="${(total_pages - 1) * page_length}">
					${total_pages}
				</button>`;
		}

		// Next button (except for last page)
		if (current_page < total_pages) {
			paging_html += `
				<button class="btn btn-default btn-next" data-start="${current_page * page_length}">
					<svg class="es-icon icon-xs"><use href="#icon-right"></use></svg>
				</button>`;
		}

		const translations = window.product_translations || {};
		const pageText = translations["Page"] || "Page";
		const ofText = translations["of"] || "of";
		const productsText = translations["products"] || "products";

		paging_html += `
					</div>
					<div class="mt-3 text-muted">
						${pageText} ${current_page} ${ofText} ${total_pages}
						<i>(${total_count} ${productsText})</i>
					</div>
				</div>
			</div>
		`;

		this.products_section.append(paging_html);
		this.bind_paging_action();
	}

	count_products() {
		let args = this.get_query_filters();
		// Set page_length to 0 to avoid retrieving products
		args.page_length = 0;
		
		return new Promise((resolve) => {
			frappe.call({
				method: "webshop.webshop.api.get_product_filter_data",
				args: {
					query_args: args
				},
				callback: function(result) {
					resolve(result.message.items_count);
				}
			});
		});
	}

	prepare_search() {
		const searchPlaceholder = (window.product_translations && window.product_translations["Search for Products"]) || "Search for Products";
		
		$(".toolbar").append(`
			<div class="input-group flex-grow-1 mb-2 mb-md-0 mr-md-3">
				<div class="dropdown w-100" id="dropdownMenuSearch">
					<input type="search" name="query" id="search-box" class="form-control font-md"
						placeholder="${searchPlaceholder}"
						aria-label="Product" aria-describedby="button-addon2">
					<div class="search-icon">
						<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor" stroke-width="2" stroke-linecap="round"
							stroke-linejoin="round"
							class="feather feather-search">
							<circle cx="11" cy="11" r="8"></circle>
							<line x1="21" y1="21" x2="16.65" y2="16.65"></line>
						</svg>
					</div>
					<!-- Results dropdown rendered in product_search.js -->
				</div>
			</div>
		`);
	}

	render_view_toggler() {
		$(".toolbar").append(`<div class="toggle-container d-flex justify-content-between align-items-center flex-grow-0"></div>`);

		["btn-list-view", "btn-grid-view"].forEach(view => {
			let icon = view === "btn-list-view" ? "list" : "image-view";
			let view_id = view === "btn-list-view" ? "list" : "grid";
			$(".toggle-container").append(`
				<div class="form-group mb-0" id="toggle-view">
					<button id="${ view_id }" class="btn ${ view } mr-2">
						<span>
							<svg class="icon icon-md">
								<use href="#icon-${ icon }"></use>
							</svg>
						</span>
					</button>
				</div>
			`);
		});
	}

	bind_view_toggler_actions() {
		$("#list").click(function() {
			let $btn = $(this);
			$btn.removeClass('btn-primary');
			$btn.addClass('btn-primary');
			$(".btn-grid-view").removeClass('btn-primary');

			$("#products-grid-area").addClass("hidden");
			$("#products-list-area").removeClass("hidden");
			localStorage.setItem("product_view", "List View");
		});

		$("#grid").click(function() {
			let $btn = $(this);
			$btn.removeClass('btn-primary');
			$btn.addClass('btn-primary');
			$(".btn-list-view").removeClass('btn-primary');

			$("#products-list-area").addClass("hidden");
			$("#products-grid-area").removeClass("hidden");
			localStorage.setItem("product_view", "Grid View");
		});
	}

	set_view_state() {
		if (this.preference === "List View") {
			$("#list").addClass('btn-primary');
			$("#grid").removeClass('btn-primary');
		} else {
			$("#grid").addClass('btn-primary');
			$("#list").removeClass('btn-primary');
		}
	}

	bind_paging_action() {
		let me = this;
		$('.btn-prev, .btn-next, .btn-page').on('click', function(e) {
			const $btn = $(this);
			const start = $btn.data('start');

			let query_params = frappe.utils.get_query_params();
			query_params.start = start;
			window.location.search = me.get_query_string(query_params);
		});
	}

	add_infinite_scroll(settings) {
		let me = this;
		let page_length = settings.products_per_page || 12;
		let total_count = this.total_count || this.product_count;
		let current_loaded = this.products ? this.products.length : 0;

		// Initialize infinite scroll state
		if (!this.infinite_scroll_state) {
			this.infinite_scroll_state = {
				start: 0,
				loading: false,
				all_loaded: false
			};
		}

		// Update start position based on currently loaded products
		this.infinite_scroll_state.start = current_loaded;

		// Check if all products are loaded
		if (current_loaded >= total_count) {
			this.infinite_scroll_state.all_loaded = true;
		}

		// Add loader element at the bottom
		const translations = window.product_translations || {};
		const loadingText = translations["Loading more products..."] || "Loading more products...";
		const allLoadedText = translations["All products loaded"] || "All products loaded";
		const productsText = translations["products"] || "products";

		let loader_html = `
			<div class="infinite-scroll-loader text-center py-4">
				${this.infinite_scroll_state.all_loaded ?
					`<div class="text-muted">${allLoadedText} (${total_count} ${productsText})</div>` :
					`<div class="infinite-scroll-spinner" style="display: none;">
						<div class="spinner-border text-primary" role="status">
							<span class="sr-only">${loadingText}</span>
						</div>
						<div class="mt-2 text-muted">${loadingText}</div>
					</div>
					<div class="infinite-scroll-sentinel" style="height: 1px;"></div>`
				}
			</div>
		`;

		this.products_section.append(loader_html);

		// Set up IntersectionObserver for infinite scroll
		if (!this.infinite_scroll_state.all_loaded && !this.infinite_scroll_observer) {
			this.setup_infinite_scroll_observer(settings);
		}
	}

	setup_infinite_scroll_observer(settings) {
		let me = this;

		// Clean up existing observer
		if (this.infinite_scroll_observer) {
			this.infinite_scroll_observer.disconnect();
		}

		const sentinel = document.querySelector('.infinite-scroll-sentinel');
		if (!sentinel) return;

		const options = {
			root: null,
			rootMargin: '200px', // Load before reaching the bottom
			threshold: 0
		};

		this.infinite_scroll_observer = new IntersectionObserver((entries) => {
			entries.forEach(entry => {
				if (entry.isIntersecting && !me.infinite_scroll_state.loading && !me.infinite_scroll_state.all_loaded) {
					me.load_next_page(settings);
				}
			});
		}, options);

		this.infinite_scroll_observer.observe(sentinel);
	}

	load_next_page(settings) {
		let me = this;

		if (this.infinite_scroll_state.loading || this.infinite_scroll_state.all_loaded) {
			return;
		}

		this.infinite_scroll_state.loading = true;

		// Show spinner
		$('.infinite-scroll-spinner').show();

		let args = this.get_query_filters();
		args.start = this.infinite_scroll_state.start;
		// IMPORTANT: Don't send from_filters=true for pagination - it resets start to 0 in backend
		args.from_filters = false;

		frappe.call({
			method: "webshop.webshop.api.get_product_filter_data",
			args: {
				query_args: args
			},
			callback: function(result) {
				me.infinite_scroll_state.loading = false;
				$('.infinite-scroll-spinner').hide();

				if (!result || result.exc || !result.message || result.message.exc) {
					return;
				}

				const new_items = result.message["items"] || [];

				if (new_items.length === 0) {
					me.infinite_scroll_state.all_loaded = true;
					me.update_infinite_scroll_status();
					return;
				}

				// Append new products to existing ones
				me.products = me.products.concat(new_items);
				me.infinite_scroll_state.start += new_items.length;

				// Check if all products are loaded
				const total_count = me.total_count || result.message["total_count"];
				if (me.infinite_scroll_state.start >= total_count) {
					me.infinite_scroll_state.all_loaded = true;
				}

				// Append new items to the view
				me.append_products(new_items, settings);

				// Update status
				me.update_infinite_scroll_status();
			},
			error: function() {
				me.infinite_scroll_state.loading = false;
				$('.infinite-scroll-spinner').hide();
			}
		});
	}

	append_products(items, settings) {
		// Append to grid view
		if (this.preference === "Grid View") {
			const $grid = $("#products-grid-area");
			items.forEach(item => {
				const html = this.get_grid_item_html(item, settings);
				$grid.append(html);
			});
		} else {
			// Append to list view
			const $list = $("#products-list-area");
			items.forEach(item => {
				const html = this.get_list_item_html(item, settings);
				$list.append(html);
			});
		}
	}

	get_grid_item_html(item, settings) {
		// Reuse ProductGrid logic for consistency
		const grid = new webshop.ProductGrid({
			items: [item],
			products_section: $('<div>'),
			settings: settings,
			preference: this.preference,
			no_render: true
		});
		return grid.get_item_html(item);
	}

	get_list_item_html(item, settings) {
		// Reuse ProductList logic for consistency
		const list = new webshop.ProductList({
			items: [item],
			products_section: $('<div>'),
			settings: settings,
			preference: this.preference,
			no_render: true
		});
		return list.get_item_html(item);
	}

	update_infinite_scroll_status() {
		const translations = window.product_translations || {};
		const allLoadedText = translations["All products loaded"] || "All products loaded";
		const productsText = translations["products"] || "products";
		const total_count = this.total_count || this.product_count;

		if (this.infinite_scroll_state.all_loaded) {
			$('.infinite-scroll-loader').html(
				`<div class="text-muted py-3">${allLoadedText} (${total_count} ${productsText})</div>`
			);

			// Disconnect observer
			if (this.infinite_scroll_observer) {
				this.infinite_scroll_observer.disconnect();
				this.infinite_scroll_observer = null;
			}
		}
	}

	re_render_discount_filters() {
		this.get_discount_filter_html();
		if (this.from_filters) {
			// Bind filter action if triggered via filters
			// if not from filter action, page load will bind actions
			this.bind_discount_filter_action();
		}
		// discount filters are rendered with Items (later)
		// unlike the other filters
		this.restore_discount_filter();
	}

	get_discount_filter_html() {
		$("#discount-filters").remove();
		const translations = window.product_translations || {};

		// Find the stock filter section
		const $stockFilter = $('#product-filters').find('.filter-block').filter(function() {
			return $(this).find('.filter-label').text().includes('Availability');
		});

		// Always show the discount filter section before stock filter
		const discountSection = `
			<div id="discount-filters" class="mb-4 filter-block pb-5">
				<div class="filter-label mb-3">${ translations["Discounts"] || "Discounts" }</div>
			</div>
		`;

		if ($stockFilter.length) {
			$stockFilter.before(discountSection);
		} else {
			// If no stock filter, append to the end
			$("#product-filters").append(discountSection);
		}

		let html = `<div class="filter-options">`;

		// Only add "Show only products with discount" checkbox
		html += `
			<div class="checkbox">
				<label>
					<input type="checkbox"
						class="product-filter discount-filter"
						id="showDiscountOnly"
						name="discount"
						data-filter-name="discount"
						data-filter-value="100"
						style="width: 14px !important"
					>
						<span class="label-area" for="showDiscountOnly">
							${ translations["Show only products with discount"] || "Show only products with discount" }
						</span>
					</label>
				</div>
		`;

		html += `</div>`;

		$("#discount-filters").append(html);
	}

	restore_discount_filter() {
		const filters = frappe.utils.get_query_params();
		let field_filters = filters.field_filters;
		
		// First check URL parameters
		if (field_filters) {
			// Safe parsing with proper decoding
			try {
				field_filters = JSON.parse(decodeURIComponent(field_filters));
			} catch (e) {
				// Try without decoding as fallback
				try {
					field_filters = JSON.parse(field_filters);
				} catch (e2) {
					console.error("Error parsing discount filters:", e2);
					field_filters = null;
				}
			}

			if (field_filters && field_filters["discount"]) {
				const values = field_filters["discount"];
				const selector = values.map(value => {
					return `input[data-filter-name="discount"][data-filter-value="${value}"]`;
				}).join(',');
				$(selector).prop('checked', true);
				this.field_filters = field_filters;
			}
		}
		
		// Also check localStorage for the discount filter state
		const saved_discount_preference = localStorage.getItem('discount_filter_checked');
		if (saved_discount_preference === 'true') {
			$('#showDiscountOnly').prop('checked', true);
			// If checkbox is checked via localStorage, also update field_filters
			if (!this.field_filters) {
				this.field_filters = {};
			}
			this.field_filters["discount"] = ["100"];
		}
	}

	bind_discount_filter_action() {
		let me = this;
		
		// Preload discount results if discount filter was previously enabled
		if (localStorage.getItem('discount_filter_checked') === 'true' && !this.preload_in_progress) {
			this.preloadDiscountResults();
		}
		
		$('.discount-filter').on('change', (e) => {
			const $checkbox = $(e.target);
			const is_checked = $checkbox.is(':checked');
			
			// Récupérer la valeur du filtre à partir de l'attribut data-filter-value
			const filter_value = $checkbox.attr('data-filter-value');
			
			// Special handling for "Show only products with discount" checkbox
			if ($checkbox.attr('id') === 'showDiscountOnly') {
				// Save preference in localStorage like stock filter
				localStorage.setItem('discount_filter_checked', is_checked ? 'true' : 'false');
				
				// If enabling discount filter and stock filter has no saved preference, save it as false
				// This prevents the default stock filter from being applied on mobile
				if (is_checked && localStorage.getItem('stock_filter_checked') === null) {
					localStorage.setItem('stock_filter_checked', 'false');
				}
				
				// Force immediate update of filters
				if (is_checked) {
					this.field_filters = this.field_filters || {};
					this.field_filters["discount"] = ["100"];
					
					// Start preloading for next time if not already done
					if (!this.preload_in_progress) {
						this.preloadDiscountResults();
					}
				} else {
					if (this.field_filters) {
						delete this.field_filters["discount"];
					}
					// Clear preloaded results when discount filter is disabled
					this.preloaded_discount_results = null;
				}
				
				// Set from_filters to true to ensure filters are applied
				me.from_filters = true;
				me.change_route_with_filters();
				return;
			}
			
			// For percentage discount filters
			delete this.field_filters["discount"];

			if (is_checked) {
				this.field_filters["discount"] = [];
				this.field_filters["discount"].push(filter_value);
			}

			if (!this.field_filters["discount"] || this.field_filters["discount"].length === 0) {
				delete this.field_filters["discount"];
			}

			me.change_route_with_filters();
		});
	}
	
	preloadDiscountResults() {
		// Avoid duplicate preloading
		if (this.preload_in_progress) return;
		
		this.preload_in_progress = true;
		
		// Get current webshop settings
		const settings = window.product_settings || {};
		const price_list = settings.price_list || null;
		
		// Preload discount items in background
		frappe.call({
			method: "webshop.webshop.api.get_discount_items_preview",
			args: {
				limit: 20,
				price_list: price_list
			},
			callback: (r) => {
				if (r.message) {
					this.preloaded_discount_results = r.message;
				}
				this.preload_in_progress = false;
			},
			error: () => {
				this.preload_in_progress = false;
			}
		});
	}

	bind_filters() {
		let me = this;
		this.field_filters = {};
		this.attribute_filters = {};
		this.tag_filters = [];
		this.price_range = {};
		
		// Initialize stock filter based on saved preference or default
		const url_filters = frappe.utils.get_query_params().field_filters;
		if (!url_filters) {
			// No filters in URL, check saved preferences
			
			// Stock filter
			const saved_stock_preference = localStorage.getItem('stock_filter_checked');
			let should_apply_stock = false;
			
			if (saved_stock_preference !== null) {
				should_apply_stock = saved_stock_preference === 'true';
			} else {
				should_apply_stock = this.stock_filter_default;
			}
			
			if (should_apply_stock) {
				this.field_filters["in_stock"] = ["1"];
			}
			
			// Discount filter
			const saved_discount_preference = localStorage.getItem('discount_filter_checked');
			if (saved_discount_preference === 'true') {
				this.field_filters["discount"] = ["100"];
			}
		}

		$('.product-filter').on('change', (e) => {
			me.from_filters = true;

			const $checkbox = $(e.target);
			const is_checked = $checkbox.is(':checked');
			
			// Reset price filter if another filter is modified
			if (!$checkbox.is('.price-filter')) {
				$('.price-filter').prop('checked', false);
				$('#price-min').val('');
				$('#price-max').val('');
				this.price_range = {};
			}
			
			// Special handling for discount filter - skip here as it's handled separately
			if ($checkbox.is('.discount-filter')) {
				return;
			}
			
			// Special handling for stock filter
			if ($checkbox.is('.stock-filter')) {
				if (is_checked) {
					this.field_filters["in_stock"] = ["1"];
					// Save user preference
					localStorage.setItem('stock_filter_checked', 'true');
				} else {
					// When unchecked, remove the filter completely
					delete this.field_filters["in_stock"];
					// Save user preference
					localStorage.setItem('stock_filter_checked', 'false');
				}
				me.change_route_with_filters();
				return;
			}

			if ($checkbox.is('.attribute-filter')) {
				const {
					attributeName: attribute_name,
					attributeValue: attribute_value
				} = $checkbox.data();

				if (is_checked) {
					this.attribute_filters[attribute_name] = this.attribute_filters[attribute_name] || [];
					this.attribute_filters[attribute_name].push(attribute_value);
				} else {
					this.attribute_filters[attribute_name] = this.attribute_filters[attribute_name] || [];
					this.attribute_filters[attribute_name] = this.attribute_filters[attribute_name].filter(v => v !== attribute_value);
				}

				if (this.attribute_filters[attribute_name].length === 0) {
					delete this.attribute_filters[attribute_name];
				}
			} else if ($checkbox.is('.field-filter') || $checkbox.is('.discount-filter') || $checkbox.is('.tag-filter')) {
				const {
					filterName: filter_name,
					filterValue: filter_value
				} = $checkbox.data();

				if ($checkbox.is('.discount-filter')) {
					// clear previous discount filter to accomodate new
					delete this.field_filters["discount"];
				}
				
				// Handle special handling for tag filters
				if ($checkbox.is('.tag-filter')) {
					if (is_checked) {
						// Add tag to filter
						if (!this.field_filters["_user_tags"]) {
							this.field_filters["_user_tags"] = [];
						}
						if (!in_list(this.field_filters["_user_tags"], filter_value)) {
							this.field_filters["_user_tags"].push(filter_value);
						}
					} else {
						// Remove tag from filter
						if (this.field_filters["_user_tags"]) {
							this.field_filters["_user_tags"] = this.field_filters["_user_tags"].filter(v => v !== filter_value);
							if (this.field_filters["_user_tags"].length === 0) {
								delete this.field_filters["_user_tags"];
							}
						}
					}
				}
				if (is_checked) {
					this.field_filters[filter_name] = this.field_filters[filter_name] || [];
					if (!in_list(this.field_filters[filter_name], filter_value)) {
						this.field_filters[filter_name].push(filter_value);
					}
				} else {
					this.field_filters[filter_name] = this.field_filters[filter_name] || [];
					this.field_filters[filter_name] = this.field_filters[filter_name].filter(v => v !== filter_value);
				}

				if (this.field_filters[filter_name].length === 0) {
					delete this.field_filters[filter_name];
				}
			}

			me.change_route_with_filters();
		});

		// bind filter lookup input box
		$('.filter-lookup-input').on('keydown', frappe.utils.debounce((e) => {
			const $input = $(e.target);
			const keyword = ($input.val() || '').toLowerCase();
			const $filter_options = $input.next('.filter-options');

			if (!keyword) {
				// If search is cleared, show all and collapse hierarchical groups
				$filter_options.find('.filter-lookup-wrapper').show();
				$filter_options.find('.children-container').hide();
				$filter_options.find('.toggle-children').text('+').attr('data-expanded', 'false');
			} else {
				// First, hide all items
				$filter_options.find('.filter-lookup-wrapper').hide();
				
				// Then show items that match the search
				$filter_options.find('.filter-lookup-wrapper').each((i, el) => {
					const $el = $(el);
					const value = ($el.data('value') || '').toLowerCase();
					
					if (value.includes(keyword)) {
						// Show this element
						$el.show();
						
						// If it's a hierarchical item group, show all parents
						$el.parents('.filter-lookup-wrapper').show();
						
						// If it has children, expand and show all children
						const $childContainer = $el.find('> .children-container');
						if ($childContainer.length > 0) {
							$childContainer.show();
							$childContainer.find('.filter-lookup-wrapper').show();
							$el.find('> .d-flex .toggle-children').text('-').attr('data-expanded', 'true');
						}
						
						// Also expand parent containers that contain this item
						$el.parents('.children-container').each(function() {
							$(this).show();
							$(this).prev('.d-flex').find('.toggle-children').text('-').attr('data-expanded', 'true');
						});
					}
				});
			}
		}, 300));
		
		// Initialize price filters
		this.bind_price_filters();
		
		// Bind discount filter actions
		this.bind_discount_filter_action();
	}
	
	update_price_filter_range(price_filters) {
		// Update the price filter range based on current filters
		if (price_filters && price_filters.length > 0) {
			const price_range = price_filters[0]; // First element contains min/max values
			if (price_range.min_value !== undefined && price_range.max_value !== undefined) {
				// Update the hidden values
				$('#price-range-min-value').text(price_range.min_value);
				$('#price-range-max-value').text(price_range.max_value);
				
				// Update the input placeholders
				$('#price-min').attr('placeholder', price_range.min_value);
				$('#price-max').attr('placeholder', price_range.max_value);
				$('#price-max').attr('max', price_range.max_value);
				
				// Re-initialize the price slider if it exists
				if (this.price_slider_initialized) {
					this.bind_price_filters();
				}
			}
		}
	}
	
	bind_price_filters() {
		let me = this;
		
		// Get the minimum and maximum price values from the DOM
		const min_price_value = parseInt($('#price-range-min-value').text()) || 0;
		const max_price_value = parseInt($('#price-range-max-value').text()) || 10000;
		
		// Variables to store the current state of the slider
		let current_min = min_price_value;
		let current_max = max_price_value;
		
		// Get DOM elements
		const $track = $('#price-slider-track');
		const $min_handle = $('#price-slider-min');
		const $max_handle = $('#price-slider-max');
		const $selection = $('#price-slider-selection');
		const $min_input = $('#price-min');
		const $max_input = $('#price-max');
		
		// Function to convert a price value to a position on the slider (in percentage)
		const priceToPosition = (price) => {
			return ((price - min_price_value) / (max_price_value - min_price_value)) * 100;
		};
		
		// Function to convert a position on the slider to a price value
		const positionToPrice = (position) => {
			const percentage = Math.max(0, Math.min(100, position)) / 100;
			return Math.round(min_price_value + percentage * (max_price_value - min_price_value));
		};
		
		// Function to update the slider display
		const updateSlider = () => {
			const min_pos = priceToPosition(current_min);
			const max_pos = priceToPosition(current_max);
			
			$min_handle.css('left', `${min_pos}%`);
			$max_handle.css('left', `${max_pos}%`);
			$selection.css({
				'left': `${min_pos}%`,
				'width': `${max_pos - min_pos}%`
			});
			
			$min_input.val(current_min);
			$max_input.val(current_max);
		};
		
		// Initialize the slider
		updateSlider();
		
		// Handle the drag of the slider handles
		let isDragging = false;
		let currentHandle = null;
		
		$min_handle.add($max_handle).on('mousedown touchstart', function(e) {
			e.preventDefault();
			isDragging = true;
			currentHandle = $(this).is($min_handle) ? 'min' : 'max';
			$(document).on('mousemove touchmove', handleDrag);
			$(document).on('mouseup touchend', stopDrag);
		});
		
		const handleDrag = (e) => {
			if (!isDragging) return;
			
			const trackWidth = $track.width();
			const trackOffset = $track.offset().left;
			let pageX = e.pageX;
			
			// Support for touch events
			if (e.touches && e.touches.length) {
				pageX = e.touches[0].pageX;
			}
			
			const position = ((pageX - trackOffset) / trackWidth) * 100;
			const price = positionToPrice(position);
			
			if (currentHandle === 'min') {
				current_min = Math.min(price, current_max - 1);
			} else {
				current_max = Math.max(price, current_min + 1);
			}
			
			updateSlider();
		};
		
		const stopDrag = () => {
			isDragging = false;
			$(document).off('mousemove touchmove', handleDrag);
			$(document).off('mouseup touchend', stopDrag);
			
			// Apply filters automatically when the user releases the handle
			applyPriceFilter();
		};
		
		// Handle changes in input fields
		$min_input.on('input', function() {
			// Ensure the value is between 0 and current_max - 1
			let value = parseInt($(this).val()) || min_price_value;
			value = Math.max(0, Math.min(value, current_max - 1));
			current_min = value;
			updateSlider();
		});
		
		$min_input.on('change', function() {
			// Ensure the value is between 0 and current_max - 1
			let value = parseInt($(this).val()) || min_price_value;
			value = Math.max(0, Math.min(value, current_max - 1));
			current_min = value;
			$(this).val(value); // Update the field with the corrected value
			updateSlider();
			// Apply filters automatically when the user finishes typing
			applyPriceFilter();
		});
		
		$max_input.on('input', function() {
			// Ensure the value is between current_min + 1 and max_price_value
			let value = parseInt($(this).val()) || max_price_value;
			value = Math.min(max_price_value, Math.max(value, current_min + 1));
			current_max = value;
			updateSlider();
		});
		
		$max_input.on('change', function() {
			// Ensure the value is between current_min + 1 and max_price_value
			let value = parseInt($(this).val()) || max_price_value;
			value = Math.min(max_price_value, Math.max(value, current_min + 1));
			current_max = value;
			$(this).val(value); // Update the field with the corrected value
			updateSlider();
			// Apply filters automatically when the user finishes typing
			applyPriceFilter();
		});
		
		// Function to apply filters automatically
		const applyPriceFilter = () => {
			// Check if the values have changed compared to the previous values
			const previousPriceRange = {...me.price_range};
			
			// Reset the price_range object before updating
			me.price_range = {};
			
			// Do not include min/max values if they are equal to the extremes
			if (current_min > min_price_value) {
				me.price_range.min = current_min;
			}
			
			if (current_max < max_price_value) {
				me.price_range.max = current_max;
			}
			
			// Always apply the filter, even if we return to default values
			// This allows to correctly reset the filters
			const hasChanges = (
				previousPriceRange.min !== me.price_range.min || 
				previousPriceRange.max !== me.price_range.max ||
				(Object.keys(previousPriceRange).length > 0 && Object.keys(me.price_range).length === 0) ||
				(Object.keys(previousPriceRange).length === 0 && Object.keys(me.price_range).length > 0)
			);
			
			// If the values have changed or if we have returned to default values, apply the filter
			if (hasChanges) {
				me.change_route_with_filters();
			}
		};
		
		// Restore price filters from URL if necessary
		const restore_price_filters = () => {
			const url_params = new URLSearchParams(window.location.search);
			const price_range_param = url_params.get('price_range');
			
			if (price_range_param) {
				try {
					const price_range = JSON.parse(decodeURIComponent(price_range_param));
					
					if (price_range.min !== undefined) {
						current_min = parseInt(price_range.min);
					}
					
					if (price_range.max !== undefined) {
						current_max = parseInt(price_range.max);
					}
					
					updateSlider();
				} catch (e) {
					console.error('Erreur lors de la restauration des filtres de prix:', e);
				}
			}
		};
		
		// Call the restore function
		restore_price_filters();
		
		// Mark that price slider is initialized
		me.price_slider_initialized = true;
	}

	refresh_list_view() {
		// This method is called when price filters are modified
		// Use change_route_with_filters directly to avoid parameter duplication
		this.change_route_with_filters();
	}

	change_route_with_filters() {
		let route_params = frappe.utils.get_query_params();

		let start = this.if_key_exists(route_params.start) || 0;
		if (this.from_filters) {
			start = 0; // show items from first page if new filters are triggered
		}

		// Create a copy of field_filters excluding localStorage-managed filters
		let url_field_filters = {};
		if (this.field_filters) {
			for (let key in this.field_filters) {
				// Exclude stock and discount filters from URL (they use localStorage)
				if (key !== 'in_stock' && key !== 'discount') {
					url_field_filters[key] = this.field_filters[key];
				}
			}
		}

		// Check if we have any filters to put in URL
		const has_url_field_filters = this.if_key_exists(url_field_filters);
		const has_attribute_filters = this.if_key_exists(this.attribute_filters);
		const has_price_filters = this.price_range && (this.price_range.min || this.price_range.max);
		
		// If no filters and start is 0, use clean URL
		if (!has_url_field_filters && !has_attribute_filters && !has_price_filters && start === 0) {
			window.history.pushState('filters', '', location.pathname);
		} else {
			// Prepare the query parameters
			let query_params = {};
			
			if (start > 0) {
				query_params.start = start;
			}
			
			if (has_url_field_filters) {
				query_params.field_filters = JSON.stringify(url_field_filters);
			}
			
			if (has_attribute_filters) {
				query_params.attribute_filters = JSON.stringify(this.attribute_filters);
			}
			
			if (has_price_filters) {
				query_params.price_range = JSON.stringify(this.price_range);
			}

			const query_string = this.get_query_string(query_params);
			window.history.pushState('filters', '', `${location.pathname}?` + query_string);
		}

		$('.page_content input').prop('disabled', true);

		this.make(true);
		$('.page_content input').prop('disabled', false);
	}

	restore_filters_state() {
		const filters = frappe.utils.get_query_params();
		let {field_filters, attribute_filters, price_range} = filters;
		
		// Track if we have any filters in URL
		const has_url_filters = field_filters || attribute_filters || price_range;

		if (field_filters) {
			field_filters = JSON.parse(field_filters);
			// Apply all filters from URL
			for (let fieldname in field_filters) {
				const values = field_filters[fieldname];
				const selector = values.map(value => {
					return `input[data-filter-name="${fieldname}"][data-filter-value="${value}"]`;
				}).join(',');
				$(selector).prop('checked', true);
			}
			this.field_filters = field_filters;
		}
		
		// Always restore localStorage-managed filters regardless of URL filters
		// Stock filter
		const saved_stock_preference = localStorage.getItem('stock_filter_checked');
		if (saved_stock_preference !== null) {
			const should_check_stock = saved_stock_preference === 'true';
			if (should_check_stock) {
				this.field_filters = this.field_filters || {};
				this.field_filters["in_stock"] = ["1"];
				$('#showInStockOnly').prop('checked', true);
			} else {
				$('#showInStockOnly').prop('checked', false);
			}
		} else if (!has_url_filters) {
			// Only use default if no saved preference and no URL filters
			const should_check_stock = this.stock_filter_default;
			if (should_check_stock) {
				this.field_filters = this.field_filters || {};
				this.field_filters["in_stock"] = ["1"];
				$('#showInStockOnly').prop('checked', true);
			} else {
				$('#showInStockOnly').prop('checked', false);
			}
		}
		
		// Discount filter - only update checkbox state, not filters
		const saved_discount_preference = localStorage.getItem('discount_filter_checked');
		if (saved_discount_preference !== null) {
			const should_check_discount = saved_discount_preference === 'true';
			$('#showDiscountOnly').prop('checked', should_check_discount);
		} else {
			// No saved preference - ensure checkbox is unchecked by default
			$('#showDiscountOnly').prop('checked', false);
		}
		
		if (attribute_filters) {
			attribute_filters = JSON.parse(attribute_filters);
			for (let attribute in attribute_filters) {
				const values = attribute_filters[attribute];
				const selector = values.map(value => {
					return `input[data-attribute-name="${attribute}"][data-attribute-value="${value}"]`;
				}).join(',');
				$(selector).prop('checked', true);
			}
			this.attribute_filters = attribute_filters;
		}
		
		// Restore price filters state
		if (price_range) {
			try {
				const price_range_obj = JSON.parse(price_range);
				
				// Update the price_range object
				this.price_range = price_range_obj;
				
				// Update the input fields
				if (price_range_obj.min) {
					$('#price-min').val(price_range_obj.min);
				}
				
				if (price_range_obj.max) {
					$('#price-max').val(price_range_obj.max);
				}
				
				// Check the corresponding checkbox if it exists
				$('.price-filter').each(function() {
					const start_price = parseInt($(this).attr('data-start-price'));
					const end_price = parseInt($(this).attr('data-end-price'));
					
					if (start_price === price_range_obj.min && end_price === price_range_obj.max) {
						$(this).prop('checked', true);
					}
				});
			} catch (e) {
				console.error("Error restoring price filters:", e);
			}
		}
	}

	render_no_products_section(error=false) {
		const translations = window.product_translations || {};
		let error_section = `
			<div class="mt-4 w-100 alert alert-error font-md">
				${ translations["Something went wrong. Please refresh or contact us."] || "Something went wrong. Please refresh or contact us." }
			</div>
		`;
		let no_results_section = `
			<div class="cart-empty frappe-card mt-4">
				<div class="cart-empty-state">
					<img src="/assets/webshop/images/cart-empty-state.png" alt="Empty Cart">
				</div>
				<div class="cart-empty-message mt-4">${ translations["No products found"] || "No products found" }</p>
			</div>
		`;

		this.products_section.append(error ? error_section : no_results_section);
	}

	render_item_sub_categories(categories) {
		if (categories && categories.length) {
			let sub_group_html = `
				<div class="sub-category-container scroll-categories">
			`;

			categories.forEach(category => {
				sub_group_html += `
					<a href="/${ category.route || '#' }" style="text-decoration: none;">
						<div class="category-pill">
							${ category.name }
						</div>
					</a>
				`;
			});
			sub_group_html += `</div>`;

			$("#product-listing").prepend(sub_group_html);
		}
	}

	get_query_string(object) {
		const url = new URLSearchParams();
		for (let key in object) {
			const value = object[key];
			if (value) {
				// For JSON values, ensure they are properly stringified
				if (typeof value === 'object') {
					url.append(key, JSON.stringify(value));
				} else {
					url.append(key, value);
				}
			}
		}
		
		// Note: Do not add price_range here as it is already included in the params object
		// in the change_route_with_filters method
		
		return url.toString();
	}

	if_key_exists(obj) {
		let exists = false;
		for (let key in obj) {
			if (Object.prototype.hasOwnProperty.call(obj, key) && obj[key]) {
				exists = true;
				break;
			}
		}
		return exists ? obj : undefined;
	}

	disable_view_toggler(disable) {
		$('#list').prop('disabled', disable);
		$('#grid').prop('disabled', disable);
	}
	
	show_product_loader() {
		// Determine view type from user preference
		const isGridView = this.preference === "Grid View";

		// Always use skeleton loading - provides better visual feedback than overlay spinner

		// First ensure the containers exist (only on initial load)
		if (!$('#products-grid-area').length) {
			this.products_section.append(`
				<div id="products-list-area" class="row products-list mt-6 ml-2 ${!isGridView ? '' : 'hidden'}" itemscope itemtype="https://schema.org/Product"></div>
				<div id="products-grid-area" class="row products-list mt-minus-1 ${isGridView ? '' : 'hidden'}" itemscope itemtype="https://schema.org/Product"></div>
			`);
		}

		// Make sure the correct view is visible
		if (isGridView) {
			$('#products-list-area').addClass('hidden');
			$('#products-grid-area').removeClass('hidden');
		} else {
			$('#products-grid-area').addClass('hidden');
			$('#products-list-area').removeClass('hidden');
		}

		// Get the target container
		const targetContainer = isGridView ? $('#products-grid-area') : $('#products-list-area');

		// Clear existing content (only for initial skeleton load)
		targetContainer.empty();
		
		// Create skeleton loader HTML
		let skeletonItems = '';
		// Use the page length from settings or default values
		const itemCount = (this.settings && this.settings.products_per_page) || (isGridView ? 12 : 8);
		
		for (let i = 0; i < itemCount; i++) {
			if (isGridView) {
				// Grid skeleton
				skeletonItems += `
					<div class="col-sm-6 col-lg-4 item-card skeleton-item">
						<div class="card text-left">
							<div class="card-img-container">
								<div class="skeleton-img skeleton-loader"></div>
							</div>
							<div class="card-body text-left card-body-flex" style="width:100%">
								<div style="margin-top: 1rem;">
									<div class="skeleton-title skeleton-loader"></div>
								</div>
								<div class="skeleton-category skeleton-loader"></div>
								<div class="skeleton-price-row">
									<div class="skeleton-price skeleton-loader"></div>
								</div>
							</div>
						</div>
					</div>
				`;
			} else {
				// List skeleton
				skeletonItems += `
					<div class="row list-row w-100 mb-4 skeleton-item">
						<div class="col-2 border text-center rounded list-image" style="position: relative; overflow: hidden;">
							<div class="skeleton-img-list skeleton-loader"></div>
						</div>
						<div class="col-10 text-left">
							<div style="display: flex; margin-left: -15px;">
								<div class="col-8" style="margin-right: -15px;">
									<div class="skeleton-title skeleton-loader"></div>
								</div>
								<div class="col-4">
									<div class="skeleton-btn-list skeleton-loader"></div>
								</div>
							</div>
							<div class="skeleton-category skeleton-loader"></div>
							<div class="skeleton-price skeleton-loader"></div>
						</div>
					</div>
				`;
			}
		}
		
		// Add skeletons directly to the existing container
		targetContainer.html(skeletonItems);
		
		// Add CSS if not already added
		if (!$('#skeleton-loader-styles').length) {
			$('head').append(`
				<style id="skeleton-loader-styles">
					/* Skeleton loader base styles */
					.skeleton-loader {
						background: linear-gradient(
							90deg,
							#f0f0f0 0%,
							#f8f8f8 50%,
							#f0f0f0 100%
						);
						background-size: 200% 100%;
						animation: skeleton-loading 1.5s ease-in-out infinite;
					}
					
					@keyframes skeleton-loading {
						0% {
							background-position: -200% 0;
						}
						100% {
							background-position: 200% 0;
						}
					}
					
					/* Grid skeleton styles */
					.skeleton-img {
						height: 200px;
						width: 100%;
						border-radius: 0;
					}
					
					.skeleton-title {
						height: 18px;
						width: 80%;
						margin-bottom: 8px;
						border-radius: 4px;
					}
					
					.skeleton-category {
						height: 14px;
						width: 50%;
						margin-bottom: 8px;
						border-radius: 4px;
					}
					
					.skeleton-price-row {
						margin-top: 16px;
					}
					
					.skeleton-price {
						height: 20px;
						width: 45%;
						border-radius: 4px;
						display: inline-block;
					}
					
					/* Match card styles */
					.product-loader .card {
						margin-bottom: 1rem;
						border: 1px solid rgba(0,0,0,.125);
						border-radius: 0.25rem;
					}
					
					.product-loader .card-body {
						padding: 1rem;
					}
					
					/* List skeleton styles */
					.skeleton-img-list {
						height: 100%;
						width: 100%;
						min-height: 120px;
						border-radius: 0.25rem;
					}
					
					.skeleton-btn-list {
						height: 30px;
						width: 135px;
						float: right;
						border-radius: 4px;
					}
					
					.list-row .skeleton-title {
						margin-bottom: 8px;
					}
					
					.list-row .skeleton-category {
						height: 14px;
						width: 40%;
						margin-bottom: 8px;
					}
					
					.list-row .skeleton-price {
						height: 20px;
						width: 30%;
					}
					
					/* Remove default card styles for skeleton */
					.skeleton-item .card {
						transition: none;
					}
					
					.skeleton-item .card:hover {
						transform: none;
						box-shadow: 0 1px 3px rgba(0,0,0,0.12), 0 1px 2px rgba(0,0,0,0.24);
					}
					
					/* Position relative for products section */
					#products-grid-area, #products-list-area {
						margin-top: 10px;
						position: relative;
					}

					/* Loading overlay styles */
					.product-loading-overlay {
						position: absolute;
						top: 0;
						left: 0;
						right: 0;
						bottom: 0;
						background: rgba(255, 255, 255, 0.7);
						display: flex;
						justify-content: center;
						align-items: flex-start;
						padding-top: 100px;
						z-index: 100;
						min-height: 200px;
					}

					.loading-spinner {
						width: 40px;
						height: 40px;
						border: 3px solid #f3f3f3;
						border-top: 3px solid var(--primary-color, #171717);
						border-radius: 50%;
						animation: spin 1s linear infinite;
					}

					@keyframes spin {
						0% { transform: rotate(0deg); }
						100% { transform: rotate(360deg); }
					}
				</style>
			`);
		}
	}
	
	hide_product_loader() {
		// Remove all skeleton items
		$('.skeleton-item').remove();

		// Remove loading overlay
		$('.product-loading-overlay').remove();
		$('#products-grid-area, #products-list-area').css('position', '');

		// Also ensure both product areas are properly cleaned if no products will be shown
		if (!this.products || this.products.length === 0) {
			$('#products-grid-area').empty();
			$('#products-list-area').empty();
		}
	}
};
