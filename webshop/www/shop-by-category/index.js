$(() => {
	// Create and move filters
	function createAndMoveFilters() {
		// Create HTML for filters and sorting options
		const filterHTML = `
			<div class="container mt-3 p-0">
				<div class="category-filter-section">
					<div class="row">
						<div class="col-md-6">
							<div class="category-search">
								<input type="text" class="form-control" id="categorySearchInput" placeholder="${frappe._('Search a category or a brand')}">
							</div>
						</div>
						<div class="col-md-6">
							<div class="sort-options">
								<label for="categorySortSelect">${frappe._('Sort by')}</label>
								<select class="form-control" id="categorySortSelect">
									<option value="default">${frappe._('Default')}</option>
									<option value="asc">${frappe._('Alphabetical (A-Z)')}</option>
									<option value="desc">${frappe._('Alphabetical (Z-A)')}</option>
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
		let category_name = e.currentTarget.dataset.name;

		if (category_type != "item_group") {
			let filters = {};
			filters[category_type] =  [category_name];
			window.location.href = "/all-products?field_filters=" + JSON.stringify(filters);
		}
	});
	
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
				activeTabContent.find('.products-list').append(
					'<div class="col-12 text-center no-results-message"><p>Aucun résultat trouvé pour "' + 
					searchTerm + '". Veuillez essayer une autre recherche.</p></div>'
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