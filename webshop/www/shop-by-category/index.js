$(() => {
	//// Neoffice — a website page has no __() catalogue: frappe._() here returned the
	//// English string and the toolbar printed "Search a category or a brand" / "Sort by"
	//// / "Default" on a French shop. index.html fills window.product_translations
	//// server-side, the convention every other webshop page follows.
	const t = window.product_translations || {};
	const _t = (text) => t[text] || text;

	//// Neoffice — added: a search box and an A-Z sort over the category/brand cards.
	//// Upstream renders the cards flat, and a shop with 200 brands was unusable
	//// (48e2708353, 2025-03-13). The block is injected after the section title once the
	//// tabs have rendered, because the tabs are built by the theme.
	// Create and move filters
	function createAndMoveFilters() {
		// Create HTML for filters and sorting options
		//// Neoffice — the search placeholder, the sort label and its three options below were
		//// frappe._(), which does not exist on a website page: they printed in English on a
		//// French shop. They read window.product_translations (_t, declared above) instead.
		//// No comment fits closer: they sit inside this template literal (2bafdf34c2 "fix(catalogue):
		//// la page « Catégories et marques » cesse de parler anglais").
		const filterHTML = `
			<div class="container mt-3 p-0">
				<div class="category-filter-section">
					<div class="row">
						<div class="col-md-6">
							<div class="category-search">
								<input type="text" class="form-control" id="categorySearchInput" placeholder="${_t('Search a category or a brand')}">
							</div>
						</div>
						<div class="col-md-6">
							<div class="sort-options">
								<label for="categorySortSelect">${_t('Sort by')}</label>
								<select class="form-control" id="categorySortSelect">
									<option value="default">${_t('Default')}</option>
									<option value="asc">${_t('Alphabetical (A-Z)')}</option>
									<option value="desc">${_t('Alphabetical (Z-A)')}</option>
								</select>
							</div>
						</div>
					</div>
				</div>
			</div>
		`;
		
		// Wait for the section title to load
		const checkTabsLoaded = setInterval(() => {
			const sectionTitle = $('.section-title');
			if (sectionTitle.length > 0) {
				clearInterval(checkTabsLoaded);
				
				// Insert filters after the section title
				sectionTitle.after(filterHTML);
				
				// Initialize filter events
				initFilterEvents();
			}
		}, 100);
	}
	
	// Initialize filter events
	function initFilterEvents() {
		// Search functionality
		$('#categorySearchInput').on('input', function() {
			const searchTerm = $(this).val().toLowerCase();
			filterCategories(searchTerm);
		});
		
		// Sorting functionality
		$('#categorySortSelect').on('change', function() {
			const sortOption = $(this).val();
			sortCategories(sortOption);
		});
	}
	
	// Activate a specific tab based on a URL parameter
	function activateTabFromURL() {
		const urlParams = new URLSearchParams(window.location.search);
		const tabParam = urlParams.get('tab');
		
		if (tabParam === 'brand' || tabParam === 'marque') {
			// Select the second tab (Marque)
			$('.nav-tabs .nav-link').eq(1).tab('show');
		}
	}
	
	// Call the function on page load
	activateTabFromURL();
	
	// Create and move filters
	createAndMoveFilters();
	
	// Handle clicks on category cards
	$('.category-card').on('click', (e) => {
		let category_type = e.currentTarget.dataset.type;
		//// Neoffice — the URL is built from data-value, not from data-name: a Select
		//// facet's card READS "Occasion" and FILTERS on "Second-hand", and rebuilding the
		//// filter from the label selected nothing. And a card the server already gave a
		//// route to is left to its own link, instead of two navigations racing.
		let category_value = e.currentTarget.dataset.value || e.currentTarget.dataset.name;
		let href = e.currentTarget.querySelector('a.stretched-link')?.getAttribute('href');

		//// Neoffice — see the marker above: a card the server already gave a route to (href set)
		//// is left to its own link, instead of racing it with this rebuilt redirect.
		if (category_type != "item_group" && (!href || href === "#")) {
			let filters = {};
			//// Neoffice — see the marker above: category_value now comes from data-value, so the
			//// rebuilt filter/redirect matches what the catalogue actually filters on.
			filters[category_type] =  [category_value];
			window.location.href = "/all-products?field_filters=" + encodeURIComponent(JSON.stringify(filters));
		}
	});
	//// Neoffice — sorting rebuilds the card list in place and re-applies the search
	//// filter afterwards, so the two controls compose (48e2708353, 2025-03-13).
	
	// Update URL when a tab is manually activated
	$('.nav-tabs .nav-link').on('shown.bs.tab', function (e) {
		const tabIndex = $(this).parent().index();
		const newUrl = new URL(window.location.href);
		
		if (tabIndex === 1) {
			// Tab "Brands"
			newUrl.searchParams.set('tab', 'brand');
		} else {
			// Tab "Item Group" (default)
			newUrl.searchParams.delete('tab');
		}
		
		// Update URL without reloading the page
		window.history.pushState({}, '', newUrl);
	});
	
	// Function to filter categories
	function filterCategories(searchTerm) {
		// Get the active tab
		const activeTabIndex = $('.nav-tabs .nav-item .active').parent().index();
		const activeTabContent = $('.tab-content .tab-pane.active');
		
		// Filter cards in the active tab
		activeTabContent.find('.category-card').each(function() {
			const cardTitle = $(this).find('.card-body').text().trim().toLowerCase();
			
			if (cardTitle.includes(searchTerm)) {
				$(this).removeClass('hidden-card');
			} else {
				$(this).addClass('hidden-card');
			}
		});
		
		// Display a message if no results
		const visibleCards = activeTabContent.find('.category-card:not(.hidden-card)');
		const noResultsMsg = activeTabContent.find('.no-results-message');
		
		if (visibleCards.length === 0 && searchTerm !== '') {
			if (noResultsMsg.length === 0) {
				//// Neoffice — the message was written in French straight in the source, so it
				//// was both untranslatable and a rule violation (code is English). It goes
				//// through the page's translation table like every other label here.
				const message = _t('No result found for "{0}". Try another search.')
					.replace("{0}", frappe.utils.escape_html(searchTerm));
				//// Neoffice — see the marker above: message is the translated string built there,
				//// no longer the hard-coded French sentence.
				activeTabContent.find('.products-list').append(
					'<div class="col-12 text-center no-results-message"><p>' + message + '</p></div>'
				);
			}
		} else {
			noResultsMsg.remove();
		}
	}
	
	// Function to sort categories
	function sortCategories(sortOption) {
		// Get the active tab
		const activeTabContent = $('.tab-content .tab-pane.active');
		const productsList = activeTabContent.find('.products-list');
		
		// Get all cards
		const cards = productsList.children().toArray();
		
		// Sort cards based on the selected option
		if (sortOption !== 'default') {
			cards.sort(function(a, b) {
				const titleA = $(a).find('.card-body').text().trim().toLowerCase();
				const titleB = $(b).find('.card-body').text().trim().toLowerCase();
				
				if (sortOption === 'asc') {
					return titleA.localeCompare(titleB, 'fr');
				} else {
					return titleB.localeCompare(titleA, 'fr');
				}
			});
		}
		
		// Reinsert cards in the correct order
		productsList.empty();
		cards.forEach(function(card) {
			productsList.append(card);
		});
		
		// Reapply search filter if necessary
		const searchTerm = $('#categorySearchInput').val().toLowerCase();
		if (searchTerm) {
			filterCategories(searchTerm);
		}
	}
});