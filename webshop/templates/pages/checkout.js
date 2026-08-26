if (!frappe.get_abbr) {
    frappe.get_abbr = function(txt, max_length) {
        if (!txt) return "";
        var abbr = "";
        max_length = max_length || 2;
        $.each(txt.split(" "), function(i, w) {
            if (abbr.length >= max_length) return false;
            if (!w.trim().length) return;
            abbr += w.trim()[0];
        });
        return abbr.toUpperCase();
    }
}

frappe.ready(function() {
    class CheckoutManager {
        constructor() {
            // Global payment processing state
            this.isProcessingPayment = false;
            this.paymentTimeout = null;
            
            // Idempotency token for payment requests
            this.paymentIdempotencyToken = this.generateIdempotencyToken();
            
            if (frappe.session.user === 'Guest') {
                // Show login dialog with forceLogin
                setTimeout(() => {
                    frappe.showLoginDialog({
                        forceLogin: true,
                        callback: function() {
                            // Redirect to cart after successful login
                            frappe.msgprint({
                                message: __('Login successful! Redirecting to cart...'),
                                indicator: 'green'
                            });
                            setTimeout(() => {
                                window.location.href = '/cart';
                            }, 1000);
                        }
                    });
                }, 500);
                
                // Add a back to cart link
                setTimeout(() => {
                    const loginDialog = document.querySelector('.login-dialog');
                    if (loginDialog && !loginDialog.querySelector('.back-to-cart-link')) {
                        const backLink = document.createElement('div');
                        backLink.className = 'back-to-cart-link text-center mt-3';
                        backLink.innerHTML = '<a href="/cart" class="text-muted">← ' + __('Back to Cart') + '</a>';
                        loginDialog.appendChild(backLink);
                    }
                }, 1000);
                
                // Prevent the rest of the checkout initialization for guests
                return;
            }
            this.steps = {
                'cart': 1,
                'step-address': 2,
                'step-shipping': 3,
                'step-payment': 4
            };
            this.isLoading = false;
            this.pendingChanges = {};
            this.currentShippingMethod = null;
            this.isUpdatingShipping = false;  
            this.isUpdatingPayment = false;  
            this.paymentMethods = [];
            this.currentMethod = null;
            this.isGiftCardOnly = false;
            this.quotationName = null;
            this.paymentMethodsInitialized = false;
            // Initialisation du cache pour les templates de paiement
            this.loadedPaymentTemplates = {};

            this.setupListeners();
            this.setupAddressListeners();
            this.bindQuantityControls();
            this.checkGiftCardOnly();
            this.showStep('step-address');
            this.loadExistingAddress();
            //this.setupLeavePageConfirmation();

            this.initializeAddressesAndOrderSummary();
            this.initializeCouponHandling();
            this.initializeLoyaltyHandling();
            $(".shopping-cart").toggleClass('hidden', true);
            // Restore initial state from localStorage
            const isOrderSummaryExpanded = localStorage.getItem('orderSummaryExpanded') === 'true';
            if (isOrderSummaryExpanded) {
                $('.order-items-content').addClass('active');
                $('.chevron-icon').addClass('active');
                $('.summary-details').addClass('active');
            }

            $('.toggle-order-items').on('click', function() {
                const $content = $('.order-items-content');
                const $chevron = $(this).find('.chevron-icon');
                const $summaryDetails = $(this).find('.summary-details');
                
                $content.toggleClass('active');
                $chevron.toggleClass('active');
                $summaryDetails.toggleClass('active');

                // Save the state in localStorage
                localStorage.setItem('orderSummaryExpanded', $content.hasClass('active'));
            });

            // Initialize terms and conditions
            const fullText = $('.terms-full .ql-editor').html();
            if (fullText) {
                const words = fullText.split(' ').slice(0, 30).join(' ') + '...';
                $('.terms-preview .ql-editor').html(words);
            }
            
            // Override dialog hide to reset payment state
            const originalHide = frappe.ui.Dialog.prototype.hide;
            frappe.ui.Dialog.prototype.hide = function() {
                if (window.checkout_manager && window.checkout_manager.isProcessingPayment) {
                    console.log("Dialog closed, resetting payment state");
                    window.checkout_manager.stopPaymentProcessing();
                }
                return originalHide.apply(this, arguments);
            };
            
            // Also listen for escape key
            $(document).on('keydown', (e) => {
                if (e.key === 'Escape' && this.isProcessingPayment) {
                    console.log("Escape pressed, resetting payment state");
                    this.stopPaymentProcessing();
                }
            });
            
            // Listen for click on modal backdrop or close button
            $(document).on('click', '.modal-backdrop, .modal .btn-modal-close, .modal .close', () => {
                if (this.isProcessingPayment) {
                    console.log("Modal closed via backdrop or close button, resetting payment state");
                    this.stopPaymentProcessing();
                }
            });
        }

        initializeAddressesAndOrderSummary() {
            if (this.isLoading) return;
            
            this.freezeElements(['step-section', 'order-summary']);
            
            try {
                frappe.call({
                    method: 'webshop.webshop.shopping_cart.cart.get_cart_quotation',
                    callback: (r) => {
                        if (!r.exc && r.message) {
                            const quotation = r.message.doc;
                            if (quotation) {
                                this.quotationName = quotation.name;
                                if (quotation.customer_address) {
                                    $('#billing_address_name').val(quotation.customer_address);
                                    frappe.call({
                                        method: 'webshop.webshop.shopping_cart.cart.update_cart_address',
                                        args: {
                                            address_type: 'Billing',
                                            address_name: quotation.customer_address
                                        }
                                    }).then(() => {
                                        this.unfreezeElements(['step-section', 'order-summary']);
                                    });
                                }
                                
                                // Update order summary
                                this.updateOrderSummaryFromDoc(quotation);
                            }
                        }
                    }
                });
            } catch (error) {
                console.error('Error initializing addresses:', error);
                this.unfreezeElements(['step-section', 'order-summary']);
            }
        }

        setupListeners() {
            this.handleShippingAddressToggle();
            this.bindEvents();
            this.setupCompanyField();
            this.setupGeoAdminAutocomplete();
        }

        // Address autocomplete - Swiss GeoAdmin + European Photon (OpenStreetMap)
        setupGeoAdminAutocomplete() {
            const self = this;

            // Swiss canton codes to full names mapping
            const cantonMap = {
                'ag': 'Aargau',
                'ai': 'Appenzell Innerrhoden',
                'ar': 'Appenzell Ausserrhoden',
                'be': 'Bern',
                'bl': 'Basel-Landschaft',
                'bs': 'Basel-Stadt',
                'fr': 'Fribourg',
                'ge': 'Genève',
                'gl': 'Glarus',
                'gr': 'Graubünden',
                'ju': 'Jura',
                'lu': 'Luzern',
                'ne': 'Neuchâtel',
                'nw': 'Nidwalden',
                'ow': 'Obwalden',
                'sg': 'St. Gallen',
                'sh': 'Schaffhausen',
                'so': 'Solothurn',
                'sz': 'Schwyz',
                'tg': 'Thurgau',
                'ti': 'Ticino',
                'ur': 'Uri',
                'vd': 'Vaud',
                'vs': 'Valais',
                'zg': 'Zug',
                'zh': 'Zürich'
            };

            // Setup autocomplete for both billing and shipping address fields
            this.setupAddressAutocomplete('#billing_address_1', 'billing', cantonMap);
            this.setupAddressAutocomplete('#shipping_address_1', 'shipping', cantonMap);
        }

        // Check if selected country is Switzerland
        isSwissCountry(prefix) {
            const $countryField = $(`#${prefix}_country`);
            if (!$countryField.length) return true; // Default to Swiss if no country field

            const selectedCountry = ($countryField.val() || '').toLowerCase();
            const selectedText = ($countryField.find('option:selected').text() || '').toLowerCase();

            // Check various Swiss identifiers
            const swissIdentifiers = ['switzerland', 'suisse', 'schweiz', 'svizzera', 'ch'];
            return swissIdentifiers.some(id =>
                selectedCountry.includes(id) || selectedText.includes(id)
            ) || !selectedCountry; // Default to Swiss if nothing selected
        }

        setupAddressAutocomplete(inputSelector, prefix, cantonMap) {
            const self = this;
            const $input = $(inputSelector);
            if (!$input.length) return;

            // Create dropdown container
            const $dropdown = $('<div class="address-autocomplete-dropdown"></div>').css({
                position: 'absolute',
                width: '100%',
                maxHeight: '200px',
                overflowY: 'auto',
                backgroundColor: 'var(--card-bg, #fff)',
                border: '1px solid var(--border-color, #d1d8dd)',
                borderRadius: '8px',
                boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
                zIndex: 1050,
                display: 'none'
            });

            // Wrap input and add dropdown
            $input.parent().css('position', 'relative');
            $input.after($dropdown);

            let debounceTimer;

            // Input event for search
            $input.on('input', function() {
                clearTimeout(debounceTimer);
                const query = $(this).val();

                if (query.length < 3) {
                    $dropdown.hide();
                    return;
                }

                debounceTimer = setTimeout(() => {
                    // Choose API based on selected country
                    if (self.isSwissCountry(prefix)) {
                        self.searchGeoAdmin(query, $dropdown, $input, prefix, cantonMap);
                    } else {
                        self.searchPhoton(query, $dropdown, $input, prefix);
                    }
                }, 300);
            });

            // Hide dropdown on blur (with delay for click)
            $input.on('blur', function() {
                setTimeout(() => $dropdown.hide(), 200);
            });

            // Show dropdown on focus if has results
            $input.on('focus', function() {
                if ($dropdown.children().length > 0) {
                    $dropdown.show();
                }
            });
        }

        // Swiss GeoAdmin API search
        searchGeoAdmin(query, $dropdown, $input, prefix, cantonMap) {
            const self = this;

            $.ajax({
                url: 'https://api3.geo.admin.ch/rest/services/api/SearchServer',
                data: {
                    searchText: query,
                    type: 'locations',
                    origins: 'address',
                    limit: 10
                },
                success: function(response) {
                    $dropdown.empty();

                    if (response.results && response.results.length > 0) {
                        response.results.forEach(function(result) {
                            const item = $('<div class="address-autocomplete-item"></div>')
                                .css({
                                    padding: '10px 12px',
                                    cursor: 'pointer',
                                    borderBottom: '1px solid var(--border-color, #eee)',
                                    fontSize: '13px'
                                })
                                .text(result.attrs.label.replace(/<[^>]*>/g, ''))
                                .hover(
                                    function() { $(this).css('backgroundColor', 'var(--control-bg, #f5f7fa)'); },
                                    function() { $(this).css('backgroundColor', ''); }
                                )
                                .on('mousedown', function(e) {
                                    e.preventDefault();
                                    self.fillAddressFromGeoAdmin(result, prefix, cantonMap);
                                    $dropdown.hide();
                                });

                            $dropdown.append(item);
                        });

                        $dropdown.show();
                    } else {
                        $dropdown.hide();
                    }
                },
                error: function() {
                    $dropdown.hide();
                }
            });
        }

        // European Photon (OpenStreetMap) API search
        searchPhoton(query, $dropdown, $input, prefix) {
            const self = this;

            // Get selected country for filtering results
            const $countryField = $(`#${prefix}_country`);
            const selectedCountry = $countryField.length ? $countryField.val() : '';

            $.ajax({
                url: 'https://photon.komoot.io/api/',
                data: {
                    q: query,
                    limit: 10,
                    lang: 'fr' // Default to French for European addresses
                },
                success: function(response) {
                    $dropdown.empty();

                    if (response.features && response.features.length > 0) {
                        response.features.forEach(function(feature) {
                            const props = feature.properties;

                            // Build display label
                            let label = '';
                            if (props.name) label += props.name;
                            if (props.housenumber) label += ' ' + props.housenumber;
                            if (props.street) {
                                if (label && !props.name) label = props.street + ' ' + label;
                                else if (!label) label = props.street;
                            }
                            if (props.postcode) label += ', ' + props.postcode;
                            if (props.city) label += ' ' + props.city;
                            if (props.country) label += ' (' + props.country + ')';

                            if (!label.trim()) return; // Skip empty results

                            const item = $('<div class="address-autocomplete-item"></div>')
                                .css({
                                    padding: '10px 12px',
                                    cursor: 'pointer',
                                    borderBottom: '1px solid var(--border-color, #eee)',
                                    fontSize: '13px'
                                })
                                .text(label)
                                .hover(
                                    function() { $(this).css('backgroundColor', 'var(--control-bg, #f5f7fa)'); },
                                    function() { $(this).css('backgroundColor', ''); }
                                )
                                .on('mousedown', function(e) {
                                    e.preventDefault();
                                    self.fillAddressFromPhoton(feature, prefix);
                                    $dropdown.hide();
                                });

                            $dropdown.append(item);
                        });

                        $dropdown.show();
                    } else {
                        $dropdown.hide();
                    }
                },
                error: function() {
                    $dropdown.hide();
                }
            });
        }

        // Fill address fields from Photon (OpenStreetMap) result
        fillAddressFromPhoton(feature, prefix) {
            const props = feature.properties;

            // Fill address fields based on prefix (billing or shipping)
            const setFieldValue = (fieldName, value) => {
                const $field = $(`#${prefix}_${fieldName}`);
                if ($field.length && value) {
                    $field.val(value).trigger('change');
                }
            };

            // Build street address
            let streetAddress = '';
            if (props.street) {
                streetAddress = props.street;
                if (props.housenumber) {
                    streetAddress += ' ' + props.housenumber;
                }
            } else if (props.name) {
                streetAddress = props.name;
                if (props.housenumber) {
                    streetAddress += ' ' + props.housenumber;
                }
            }

            setFieldValue('address_1', streetAddress);
            setFieldValue('postcode', props.postcode || '');
            setFieldValue('city', props.city || props.town || props.village || props.municipality || '');
            setFieldValue('state', props.state || props.county || '');

            // Set country if available
            if (props.country) {
                const $countryField = $(`#${prefix}_country`);
                if ($countryField.length) {
                    // Try to find matching country option
                    const countryLower = props.country.toLowerCase();
                    const countryOption = $countryField.find('option').filter(function() {
                        const optVal = ($(this).val() || '').toLowerCase();
                        const optText = ($(this).text() || '').toLowerCase();
                        return optVal.includes(countryLower) || optText.includes(countryLower) ||
                               countryLower.includes(optVal) || countryLower.includes(optText);
                    });
                    if (countryOption.length) {
                        $countryField.val(countryOption.first().val()).trigger('change');
                    }
                }
            }
        }

        fillAddressFromGeoAdmin(result, prefix, cantonMap) {
            const attrs = result.attrs;

            // Parse the detail field: "street number postal_code city ... country_code canton_code"
            // Example: "rue du lac 1 1400 yverdon-les-bains 5938 yverdon-les-bains ch vd"
            const detail = attrs.detail || '';
            const parts = detail.split(' ');

            // Extract postal code (4-digit number) and city from detail
            let postalCode = '';
            let city = '';
            let cantonCode = '';

            // Find postal code (4 digits) and get city name after it
            for (let i = 0; i < parts.length; i++) {
                if (/^\d{4}$/.test(parts[i])) {
                    postalCode = parts[i];
                    // City is the next part(s) until we hit another number or 'ch'
                    let cityParts = [];
                    for (let j = i + 1; j < parts.length; j++) {
                        if (/^\d+$/.test(parts[j]) || parts[j].toLowerCase() === 'ch') {
                            break;
                        }
                        cityParts.push(parts[j]);
                    }
                    if (cityParts.length > 0) {
                        // Capitalize city name properly
                        city = cityParts.map(part =>
                            part.split('-').map(word =>
                                word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()
                            ).join('-')
                        ).join(' ');
                    }
                    break;
                }
            }

            // Extract canton code (last part after 'ch')
            const chIndex = parts.map(p => p.toLowerCase()).indexOf('ch');
            if (chIndex !== -1 && chIndex < parts.length - 1) {
                cantonCode = parts[chIndex + 1].toLowerCase();
            }

            // Get full canton name from code
            const canton = cantonMap[cantonCode] || '';

            // Fill address fields based on prefix (billing or shipping)
            const setFieldValue = (fieldName, value) => {
                const $field = $(`#${prefix}_${fieldName}`);
                if ($field.length && value) {
                    $field.val(value).trigger('change');
                }
            };

            // Clean and format the label for street address
            const label = attrs.label.replace(/<[^>]*>/g, '');

            // Extract the "street + number" part (everything before the postal code)
            let streetAddress = label;
            if (postalCode) {
                const postalMatch = label.match(new RegExp(`^(.+?)\\s+${postalCode}\\s+`));
                if (postalMatch) {
                    streetAddress = postalMatch[1].trim();
                }
            }

            // Split "street + number" into two distinct fields (structured address,
            // no concatenation). attrs.num signals there IS a building number, but it
            // is lossy on alphanumeric numbers (e.g. "1a" comes back as 1), so read the
            // accurate number from the label's trailing token and use attrs.num only as
            // a fallback — otherwise the suffix would stay glued to the street and the
            // number would appear twice.
            const apiNumber = (attrs.num || '').toString().trim();
            let streetName = streetAddress;
            let houseNumber = apiNumber;
            if (apiNumber) {
                const trailing = streetAddress.match(
                    /^(.*?)[,\s]+(\d+\s?[A-Za-z]?(?:[-/]\d+\s?[A-Za-z]?)*)$/
                );
                if (trailing) {
                    streetName = trailing[1].trim();
                    houseNumber = trailing[2].replace(/\s+/g, '');
                } else {
                    const numAtEnd = new RegExp(
                        '\\s*' + apiNumber.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '$'
                    );
                    streetName = streetAddress.replace(numAtEnd, '').trim() || streetAddress;
                }
            }

            setFieldValue('address_1', streetName);
            setFieldValue('house_number', houseNumber);
            setFieldValue('postcode', postalCode);
            setFieldValue('city', city);
            setFieldValue('state', canton);

            // Set country to Switzerland
            const $countryField = $(`#${prefix}_country`);
            if ($countryField.length) {
                // Try to find and select Switzerland option
                const switzerlandOption = $countryField.find('option').filter(function() {
                    return $(this).val().toLowerCase().includes('switzerland') ||
                           $(this).text().toLowerCase().includes('switzerland') ||
                           $(this).text().toLowerCase().includes('suisse') ||
                           $(this).text().toLowerCase().includes('schweiz');
                });
                if (switzerlandOption.length) {
                    $countryField.val(switzerlandOption.val()).trigger('change');
                }
            }
        }

        setupLeavePageConfirmation() {
            // Variable to track page modifications
            this.pageModified = true;
            
            // Add an event listener to intercept tab closing
            window.addEventListener('beforeunload', (e) => {
                if (this.pageModified) {
                    // Standard message for different browsers
                    const confirmationMessage =__("Are you sure you want to leave this page? Your order has not been finalized.");
                    e.returnValue = confirmationMessage; // Standard for most browsers
                    return confirmationMessage; // For older browsers
                }
            });
            
            // Intercept clicks on links that leave the checkout
            $(document).on('click', 'a', (e) => {
                const href = $(e.currentTarget).attr('href');
                // Check if the link does not contain 'checkout', is not thank_you.html and is not an internal anchor (#)
                if (href && !href.includes('checkout') && !href.includes('thank_you.html') && !href.startsWith('#') && this.pageModified) {
                    if (!confirm(__("Are you sure you want to leave this page? Your order has not been finalized."))) {
                        e.preventDefault();
                    }
                }
            });
            
            // Disable alert when order is finalized
            $(document).on('click', '.btn-submit-payment', () => {
                this.pageModified = false;
            });
        }

        setupCompanyField() {
            // Load initial company name if customer type is Company
            frappe.call({
                method: 'webshop.webshop.shopping_cart.cart.get_customer_info',
                callback: (response) => {
                    if (response.message) {
                        const customer = response.message;
                        if (customer.customer_type === 'Company') {
                            $('#customer_name').val(customer.customer_name);
                        }
                    }
                }
            });
        }

        bindEvents() {
            // Remove all existing event handlers from the document
            $(document).off('click', '.next-step');
            $(document).off('click', '.prev-step');
            $(document).off('click', '.place-order');
            $(document).off('change', '#address-form input, #address-form select');

            // Track form changes
            $(document).on('change', '#address-form input, #address-form select', (e) => {
                const $input = $(e.target);
                const fieldName = $input.attr('name') || $input.attr('id');
                let newValue = $input.val();
                // If the field is a checkbox, use the 'checked' property
                if ($input.is(':checkbox')) {
                    newValue = $input.prop('checked');
                }

                // Initialize initial form values if not set
                if (!this.initialFormValues) {
                    this.initialFormValues = {};
                    $('#address-form input, #address-form select').each(function() {
                        const name = $(this).attr('name') || $(this).attr('id');
                        if (name) {
                            let val = $(this).val();
                            if ($(this).is(':checkbox')) {
                                val = $(this).prop('checked');
                            }
                            this.initialFormValues[name] = val;
                        }
                    }.bind(this));
                }

                // Compare new value with initial value
                let initialValue = this.initialFormValues[fieldName];
                // For a checkbox, if the initial value is not set, consider false
                if ($input.is(':checkbox') && typeof initialValue === 'undefined') {
                    initialValue = false;
                }

                if (initialValue === newValue) {
                    delete this.pendingChanges[fieldName];
                } else {
                    this.pendingChanges[fieldName] = newValue;
                }

            });

            // Bind events using event delegation
            $(document).on('click', '.next-step', async (e) => {
                e.preventDefault(); // Prevent form submission
                e.stopPropagation(); // Stop event propagation

                if (this.isLoading) return;
                const currentStep = $(e.target).closest('.step-section').attr('id');
                
                if (currentStep === 'step-address') {
                    // Validate required billing address fields
                    const requiredFields = {
                        'contact_first_name': __('First Name'),
                        'contact_last_name': __('Last Name'),
                        'contact_email': __('Email'),
                        'contact_phone': __('Phone'),
                        'billing_address_1': __('Address'),
                        'billing_city': __('City'),
                        'billing_postcode': __('Postal Code'),
                        'billing_country': __('Country')
                    };

                    let missingFields = [];
                    for (let [field, label] of Object.entries(requiredFields)) {
                        if (!$(`#${field}`).val()) {
                            missingFields.push(label);
                        }
                    }

                    if (missingFields.length > 0) {
                        frappe.throw(__('Please fill in the following required fields: {0}', [missingFields.join(', ')]));
                        return;
                    }

                    // If "Ship to different address" is checked, validate shipping address
                    if ($('#ship_to_different').is(':checked')) {
                        const shippingFields = {
                            'shipping_address_1': __('Shipping Address'),
                            'shipping_city': __('Shipping City'),
                            'shipping_postcode': __('Shipping Postal Code'),
                            'shipping_country': __('Shipping Country')
                        };

                        missingFields = [];
                        for (let [field, label] of Object.entries(shippingFields)) {
                            if (!$(`#${field}`).val()) {
                                missingFields.push(label);
                            }
                        }

                        if (missingFields.length > 0) {
                            frappe.throw(__('Please fill in the following required fields: {0}', [missingFields.join(', ')]));
                            return;
                        }
                    }

                    if (Object.keys(this.pendingChanges).length > 0) {
                        this.showConfirmationDialog(e);
                    } else {
                        // Force address synchronization if necessary
                        await frappe.call({
                            method: 'webshop.webshop.shopping_cart.cart.update_cart_address',
                            args: { 
                                address_type: 'Shipping', 
                                address_name: $('#billing_address_name').val() 
                            }
                        });

                        // Check if all items are gift cards
                        await this.checkGiftCardOnly();
                        
                        if (this.isGiftCardOnly) {
                            this.showStep('step-payment');
                        } else {
                            this.showStep('step-shipping');
                        }
                    }
                } else if (currentStep === 'step-shipping') {
                    // Check if a shipping method has been selected
                    const selectedShipping = $('input[name="shipping_method"]:checked').val();
                    if (!selectedShipping) {
                        frappe.msgprint({
                            title: __('Shipping Method Required'),
                            message: __('Please select a shipping method before proceeding to payment'),
                            indicator: 'red'
                        });
                        return;
                    }

                    this.showStep('step-payment');
                }
            });

            $(document).on('click', '.prev-step', (e) => {
                if (this.isLoading) return;
                this.handlePrevStep(e);
            });

            $('.toggle-terms').on('click', function() {
                const $btn = $(this);
                const $preview = $('.terms-preview');
                const $full = $('.terms-full');
                
                if ($full.hasClass('hidden')) {
                    $preview.addClass('hidden');
                    $full.removeClass('hidden');
                    $btn.text(__("Show less"));
                } else {
                    $preview.removeClass('hidden');
                    $full.addClass('hidden');
                    $btn.text(__("Show more"));
                }
            });

            $(document).on('click', '.terms-link', function(e) {
                e.preventDefault();
                const $termsTitle = $('#terms-title');
                const $preview = $('.terms-preview');
                const $full = $('.terms-full');
                const $btn = $('.toggle-terms');
                
                // Display full text
                if ($full.hasClass('hidden')) {
                    $preview.addClass('hidden');
                    $full.removeClass('hidden');
                    $btn.text(__("Show less"));
                }
                
                // Scroll to title
                $('html, body').animate({
                    scrollTop: $termsTitle.offset().top - 20
                }, 500);
            });

            // Handle terms acceptance for all payment methods
            $(document).on('change click', '.payment-method-item.selected #terms-acceptance, .payment-method-item.selected .form-check-label', function(e) {
                const $container = $(this).closest('.payment-method-item.selected');
                if (!$container.length) return;

                // If it's a label click, simulate a checkbox click
                if ($(this).hasClass('form-check-label')) {
                    e.preventDefault();
                    const $checkbox = $container.find('#terms-acceptance');
                    $checkbox.prop('checked', !$checkbox.prop('checked')).trigger('change');
                    return;
                }

                const $submitBtn = $container.find('.btn-submit-payment');
                const isChecked = $(this).prop('checked');

                // Enable/disable submit button
                $submitBtn.prop('disabled', !isChecked);
                
                if (!isChecked) {
                    $submitBtn.addClass('disabled')
                        .attr('disabled', 'disabled')
                        .attr('title', __('Please accept the terms and conditions to continue'));
                    
                    if ($submitBtn.data('bs.tooltip')) {
                        $submitBtn.tooltip('enable');
                    }
                } else {
                    $submitBtn.removeClass('disabled')
                        .removeAttr('disabled')
                        .removeAttr('title');
                    
                    if ($submitBtn.data('bs.tooltip')) {
                        $submitBtn.tooltip('disable');
                    }
                }
            });
            
            // Function to check and update button state based on terms acceptance
            this.updatePaymentButtonState = function() {
                $('.payment-method-item.selected').each(function() {
                    const $item = $(this);
                    const $checkbox = $item.find('#terms-acceptance');
                    const $submitBtn = $item.find('.btn-submit-payment');
                    
                    if ($checkbox.length && $submitBtn.length) {
                        const isChecked = $checkbox.prop('checked');
                        $submitBtn.prop('disabled', !isChecked);
                        
                        if (!isChecked) {
                            $submitBtn.addClass('disabled')
                                .attr('disabled', 'disabled')
                                .attr('title', __('Please accept the terms and conditions to continue'));
                        } else {
                            $submitBtn.removeClass('disabled')
                                .removeAttr('disabled')
                                .removeAttr('title');
                        }
                    }
                });
            };

            // Initialize tooltips
            $('[data-toggle="tooltip"]').tooltip();
        }

        async format_currency_value(value, currency) {
            return new Promise((resolve, reject) => {
                frappe.call({
                    method: "webshop.webshop.utils.utils.format_currency_value",
                    args: {
                        value: value,
                        currency: currency
                    },
                    callback: function(r) {
                        if (r.message) {
                            resolve(r.message);
                        } else {
                            resolve("0");
                        }
                    },
                    error: function(err) {
                        console.error('Error formatting currency:', err);
                        reject(err);
                    }
                });
            });
        }

        loadExistingAddress() {
            // Continue with existing address loading logic
            frappe.call({
                method: 'webshop.templates.pages.checkout.get_shipping_address',
                callback: (response) => {
                    if (response.message) {
                        const address = response.message;
                        $('[name="shipping_address_name"]').val(address.name || '');
                        $('[name="shipping_customer"]').val(address.customer_name || '');
                        $('[name="shipping_address_1"]').val(address.address_line1 || '');
                        $('[name="shipping_house_number"]').val(address.custom_house_number || '');
                        $('[name="shipping_address_2"]').val(address.address_line2 || '');
                        $('[name="shipping_city"]').val(address.city || '');
                        $('[name="shipping_state"]').val(address.state || '');
                        $('[name="shipping_postcode"]').val(address.pincode || '');
                        $('[name="shipping_country"]').val(address.country || '');
                        $('[name="shipping_phone"]').val(address.phone || $('[name="billing_phone"]').val());
                        $('[name="shipping_email"]').val(address.email_id || $('[name="billing_email"]').val());
                    }
                }
            });
        }

        collectAddressData(type) {
            const prefix = type.toLowerCase();
            const fullname = $('[name="contact_first_name"]').val() + ' ' + $('[name="contact_last_name"]').val();
            
            return {
                address_title: fullname,
                address_type: type,
                address_line1: $(`[name="${prefix}_address_1"]`).val(),
                custom_house_number: $(`[name="${prefix}_house_number"]`).val() || '',
                address_line2: $(`[name="${prefix}_address_2"]`).val() || '',
                city: $(`[name="${prefix}_city"]`).val(),
                state: $(`[name="${prefix}_state"]`).val(),
                pincode: $(`[name="${prefix}_postcode"]`).val(),
                country: $(`[name="${prefix}_country"]`).val(),
                phone: $(`[name="${prefix}_phone"]`).val(),
                email_id: $(`[name="${prefix}_email"]`).val(),
                is_primary_address: type === 'Billing' ? 1 : 0,
                is_shipping_address: type === 'Shipping' ? 1 : 0
            };
        }

        collectContactData() {
            return {
                fullname: $('[name="contact_first_name"]').val() + ' ' + $('[name="contact_last_name"]').val(),
                first_name: $('[name="contact_first_name"]').val(),
                last_name: $('[name="contact_last_name"]').val(),
                phone: $('[name="contact_phone"]').val(),
                email: $('[name="contact_email"]').val(),
                company_name: $('[name="customer_name"]').val()
            };
        }

        async handleContactChange() {
            const contactData = this.collectContactData();

            return new Promise((resolve, reject) => {
                frappe.call({
                    method: 'webshop.webshop.shopping_cart.cart.update_contact_info',
                    args: {
                        first_name: contactData.first_name,
                        last_name: contactData.last_name,
                        email: contactData.email,
                        phone: contactData.phone,
                        company_name: contactData.company_name
                    },
                    callback: (r) => {
                        if (!r.exc) {
                            resolve(r);
                        } else {
                            console.error('Error updating contact:', r.exc);
                            reject(r.exc);
                        }
                    }
                });
            });
        }

        setupAddressListeners() {
            // Listen for changes in billing address fields
            const billingFields = [
                'billing_phone',
                'billing_email',
                'billing_address_1',
                'billing_address_2',
                'billing_city',
                'billing_state',
                'billing_postcode',
                'billing_country'
            ];

            // Listen for changes in shipping address fields
            const shippingFields = [
                'shipping_name',
                'shipping_phone',
                'shipping_email',
                'shipping_address_1',
                'shipping_address_2',
                'shipping_city',
                'shipping_state',
                'shipping_postcode',
                'shipping_country'
            ];

            // Remove existing listeners
            billingFields.forEach(field => {
                $(document).off('change', `[name="${field}"]`);
            });
            shippingFields.forEach(field => {
                $(document).off('change', `[name="${field}"]`);
            });

            // Add new listeners to track changes
            billingFields.forEach(field => {
                $(document).on('change', `[name="${field}"]`, (e) => {
                    const $input = $(e.target);
                    this.pendingChanges[field] = $input.val();
                });
            });

            shippingFields.forEach(field => {
                $(document).on('change', `[name="${field}"]`, (e) => {
                    const $input = $(e.target);
                    this.pendingChanges[field] = $input.val();
                });
            });

            // Handle "Use same address for shipping" checkbox
            $(document).on('change', '#same_as_billing', () => {
                const sameAsBilling = $('#same_as_billing').is(':checked');

                if (sameAsBilling) {
                    shippingFields.forEach(field => {
                        const billingField = field.replace('shipping_', 'billing_');
                        const value = $(`[name="${billingField}"]`).val();
                        $(`[name="${field}"]`).val(value);
                        this.pendingChanges[field] = value;
                    });
                }
            });
        }

        async applyPendingChanges() {
            try {
                // Update contact information if needed
                const contactFields = ['contact_first_name', 'contact_last_name', 'contact_email', 'contact_phone'];
                if (Object.keys(this.pendingChanges).some(key => contactFields.includes(key))) {
                    await this.handleContactChange();
                }

                // Update customer information if needed
                if (this.pendingChanges['customer_name']) {
                    const response = await frappe.call({
                        method: 'webshop.webshop.shopping_cart.cart.update_customer_info',
                        args: {
                            customer_name: this.pendingChanges['customer_name'],
                            customer_type: 'Company'
                        }
                    });

                    if (!response.message.success) {
                        throw new Error(response.message.message);
                    }
                }

                // Handle billing and shipping addresses
                const shipToDifferent = $('#ship_to_different').is(':checked');
                const hasBillingChanges = Object.keys(this.pendingChanges).some(key => 
                    key.startsWith('billing_') || 
                    key === 'contact_first_name' || 
                    key === 'contact_last_name'
                );
                const hasShippingChanges = Object.keys(this.pendingChanges).some(key => key.startsWith('shipping_'));

                try {
                    // Handle billing address if modified
                    if (hasBillingChanges) {
                        const billingData = this.collectAddressData('Billing');
                        const billingAddressName = $('#billing_address_name').val();

                        if (billingAddressName) {
                            // Update existing address using new method
                            await frappe.call({
                                method: 'webshop.templates.pages.checkout.update_address_info',
                                args: {
                                    doctype: 'Address',
                                    docname: billingAddressName,
                                    fieldname_dict: {
                                        ...billingData,
                                        is_primary_address: 1,
                                        is_shipping_address: 0
                                    }
                                }
                            });
                        } else {
                            // Create new billing address
                            const response = await frappe.call({
                                method: 'webshop.webshop.shopping_cart.cart.add_new_address',
                                args: {
                                    doc: {
                                        ...billingData,
                                        is_primary_address: 1,
                                        is_shipping_address: 0
                                    }
                                }
                            });

                            if (response.message) {
                                $('#billing_address_name').val(response.message.name);
                                await frappe.call({
                                    method: 'webshop.webshop.shopping_cart.cart.update_cart_address',
                                    args: {
                                        address_type: 'Billing',
                                        address_name: response.message.name
                                    }
                                });
                            }
                        }
                    }

                    // New shipping address handling
                    if (shipToDifferent) {
                        if ($('#shipping_address_name').val() === $('#billing_address_name').val()) {
                            $('#shipping_address_name').val('');
                        }
                        const shippingData = this.collectAddressData('Shipping');
                        let shippingAddressName = $('#shipping_address_name').val();
                        if (shippingAddressName) {
                            // Update existing shipping address using new method
                            await frappe.call({
                                method: 'webshop.templates.pages.checkout.update_address_info',
                                args: {
                                    doctype: 'Address',
                                    docname: shippingAddressName,
                                    fieldname_dict: {
                                        ...shippingData,
                                        is_primary_address: 0,
                                        is_shipping_address: 1
                                    }
                                }
                            });
                        } else {
                            // Create new shipping address
                            const response = await frappe.call({
                                method: 'webshop.webshop.shopping_cart.cart.add_new_address',
                                args: {
                                    doc: {
                                        ...shippingData,
                                        is_primary_address: 0,
                                        is_shipping_address: 1
                                    }
                                }
                            });
                            if (response.message) {
                                $('#shipping_address_name').val(response.message.name);
                            }
                        }
                        // Update quotation with shipping address
                        await frappe.call({
                            method: 'webshop.webshop.shopping_cart.cart.update_cart_address',
                            args: { 
                                address_type: 'Shipping', 
                                address_name: $('#shipping_address_name').val() 
                            }
                        });
                    } else {
                        // If 'ship_to_different' is not checked, use billing address for shipping
                        await frappe.call({
                            method: 'webshop.webshop.shopping_cart.cart.update_cart_address',
                            args: { 
                                address_type: 'Shipping', 
                                address_name: $('#billing_address_name').val() 
                            }
                        });
                    }

                    // Update display after changes
                    const displayResponse = await frappe.call({
                        method: 'webshop.webshop.shopping_cart.cart.get_cart_quotation'
                    });

                    if (displayResponse.message) {
                        $('.tax-container').html(displayResponse.message.taxes);
                        $('.billing-address-display').html(displayResponse.message.address);
                        if (shipToDifferent) {
                            $('.shipping-address-display').html(displayResponse.message.shipping_address);
                        }
                    }

                    frappe.show_alert({
                        message: __('Information updated successfully'),
                        indicator: 'green'
                    });

                    return true;
                } catch (error) {
                    console.error('Error applying changes:', error);
                    throw error;
                }
            } catch (error) {
                console.error('Error applying changes:', error);
                throw error;
            }
        }

        handleShippingAddressToggle() {
            const shippingContainer = $('#shipping-address-container');
            const shippingFields = $('.shipping-field');

            $('#ship_to_different').on('change', async (e) => {
                const isChecked = $(e.target).is(':checked');

                if (isChecked) {
                    shippingContainer.show();
                    shippingFields.prop('required', true);
                    shippingFields.prop('disabled', false);
                } else {
                    shippingContainer.hide();
                    shippingFields.prop('required', false);
                    shippingFields.prop('disabled', true);
                }
            });
        }

        async handlePrevStep(e) {
            if (this.isLoading) return;

            const currentStep = $(e.target).closest('.step-section').attr('id');
            let prevStep;

            // Define step navigation
            switch (currentStep) {
                case 'step-address':
                    window.location.href = '/cart';
                    return;
                case 'step-shipping':
                    prevStep = 'step-address';
                    break;
                case 'step-payment':
                    prevStep = this.isGiftCardOnly ? 'step-address' : 'step-shipping';
                    break;
                default:
                    return;
            }

            // Reload the address data when going back to the address step
            if (prevStep === 'step-address') {
                this.loadExistingAddress();
            }

            this.showStep(prevStep);
        }

        showStep(stepId) {
            $('.step-section').removeClass('active').addClass('hidden');
            const $step = $(`#${stepId}`);
            $step.hide().removeClass('hidden').fadeIn(500, function() {
                $step.addClass('active');
            });
            
            if (stepId === 'step-payment') {
                // Initialise payment methods if you have not already done so
                if (!this.paymentMethodsInitialized) {
                    this.setupPaymentMethods();
                    this.paymentMethodsInitialized = true;
                }
                
                // Update shipping method if already selected
                const selectedShippingMethod = $('input[name="shipping_method"]:checked').val();
                if (selectedShippingMethod) {
                    this.updateShippingMethod(selectedShippingMethod, true);
                }
            }

            // If showing shipping step, load shipping methods
            if (stepId === 'step-shipping') {
                this.loadShippingMethods();
            }

            // Update progress bar
            const currentStep = this.steps[stepId];
            this.updateProgressBar(currentStep);
            
            // Scroll to top
            window.scrollTo(0, 0);
        }

        updateProgressBar(currentStep) {
            // Update data-active-step attribute
            $('.steps-progress-bar').attr('data-active-step', currentStep);
            
            // Update step numbers and labels
            $('.step-item').each((index, item) => {
                const stepNumber = index + 1;
                const $number = $(item).find('.step-number');
                const $label = $(item).find('.step-label');
                
                if (stepNumber <= currentStep) {
                    $number.addClass('active');
                    $label.addClass('active');
                } else {
                    $number.removeClass('active');
                    $label.removeClass('active');
                }
            });
        }

        showConfirmationDialog(originalEvent) {
            // Create changes summary HTML
            let changesSummary = '<div class="changes-summary">';
            for (const [field, value] of Object.entries(this.pendingChanges)) {
                const fieldLabel = $(`label[for="${field}"]`).text() || this.formatFieldName(field);
                const displayValue = typeof value === 'boolean' ? (value ? '✓' : '✗') : value;
                changesSummary += `<div class="change-item" style="margin-bottom: 8px;">
                    <strong>${fieldLabel}:</strong> ${displayValue}
                </div>`;
            }
            changesSummary += '</div>';

            frappe.confirm(
                changesSummary,
                () => {
                    // On 'Yes'
                    this.applyPendingChanges().then(() => {
                        this.pendingChanges = {};
                        this.showStep('step-shipping');
                    }).catch(error => {
                        frappe.msgprint({
                            title: __('Error'),
                            indicator: 'red',
                            message: __('Error applying changes: ' + error.message)
                        });
                    });
                },
                () => {
                    // On 'No'
                    return;
                },
                {
                    title: __('Confirm Changes'),
                    description: __('The following changes will be applied:')
                }
            );

            // Prevent form submission
            if (originalEvent) {
                originalEvent.preventDefault();
                originalEvent.stopPropagation();
            }
        }

        formatFieldName(fieldName) {
            return fieldName
                .replace(/_/g, ' ')
                .replace(/([A-Z])/g, ' $1')
                .toLowerCase()
                .replace(/^\w/, c => c.toUpperCase());
        }

        freeze(selector = 'step-section') {
            this.isLoading = true;
            if (!$(`#checkout-freeze-${selector}`).length) {
                let selectorClass = `.${selector}`;
                if(selector === 'step-section') {
                    selectorClass += '.active';
                } else if(selector === 'payment-method-item') {
                    selectorClass += '.selected';
                }
                let freeze = $(`<div id="checkout-freeze-${selector}" class="checkout-freeze">
                    <div class="loader">
                        <div class="mask"></div>
                        <div class="mask2"></div>
                    </div>
                </div>`).appendTo($(selectorClass));

                setTimeout(function() {
                    freeze.addClass("show");
                }, 1);
            } else {
                $(`#checkout-freeze-${selector}`).addClass("show");
            }
        }

        unfreeze(selector = 'step-section') {
            this.isLoading = false;
            if ($("." + selector).length) {
                let freeze = $(`#checkout-freeze-${selector}`).removeClass("show");
                setTimeout(function() {
                    freeze.remove();
                }, 1);
            }
        }

        freezeElements(selectors) {
            selectors.forEach(selector => {
                this.freeze(selector);
                setTimeout(() => {
                    this.unfreeze(selector);
                }, 3000);
            });
        }

        unfreezeElements(selectors) {
            selectors.forEach(selector => {
                this.unfreeze(selector);
            });
        }

        handleShippingAddressToggle() {
            const shippingContainer = $('#shipping-address-container');
            const shippingFields = $('.shipping-field');

            $('#ship_to_different').on('change', async (e) => {
                const isChecked = $(e.target).is(':checked');

                if (isChecked) {
                    shippingContainer.show();
                    shippingFields.prop('required', true);
                    shippingFields.prop('disabled', false);
                } else {
                    shippingContainer.hide();
                    shippingFields.prop('required', false);
                    shippingFields.prop('disabled', true);
                }
            });
        }

        async loadShippingMethods(isRefresh = false) {
            if (this.isLoading) return;
            
            this.freezeElements(['step-section', 'order-summary']);
            const container = $('#shipping-methods-container');
            const previousHtml = container.html();
            container.html(`<div class="text-muted">${__('Loading shipping methods...')}</div>`);

            // Get form data
            const ship_to_different = $('#ship_to_different').is(':checked');
            const shipping_country = $('[name="shipping_country"]').val();
            const billing_country = $('[name="billing_country"]').val();

            try {
                const response = await frappe.call({
                    method: 'webshop.templates.pages.checkout.get_shipping_methods',
                    args: {
                        ship_to_different: ship_to_different,
                        shipping_country: shipping_country,
                        billing_country: billing_country
                    }
                });

                if (response.message && response.message.length) {
                    const methods = response.message;

                    let html = `<div class="shipping-methods">
                        <div class="mb-3">${__('Please select a shipping method to continue')}</div>`;

                    methods.forEach((method, index) => {
                        html += `
                            <div class="shipping-method frappe-card p-5 mb-4">
                                <div class="custom-control custom-radio">
                                    <input type="radio" 
                                           id="shipping_method_${method.name}" 
                                           name="shipping_method" 
                                           class="custom-control-input hide"
                                           value="${method.name}"
                                           data-rate="${method.rate}"
                                           ${methods.length === 1 || method.name === this.currentShippingMethod ? 'checked' : ''}>
                                    <label class="custom-control-label w-100" for="shipping_method_${method.name}">
                                        <div class="d-flex justify-content-between align-items-center">
                                            <div>
                                                <strong>${method.title}</strong>
                                                ${method.carrier ? `<span class="text-muted ml-2">(${method.carrier})</span>` : ''}
                                            </div>
                                            <div class="shipping-rate">
                                                ${method.formatted_rate}
                                            </div>
                                        </div>
                                        ${method.description ? `<small class="text-muted d-block">${method.description}</small>` : ''}
                                    </label>
                                </div>
                            </div>`;
                    });

                    html += '</div>';

                    // Update HTML only if it has changed
                    if (html !== previousHtml) {
                        container.html(html);
                        // Reattach events
                        this.attachShippingMethodEvents();

                        // If a shipping method is auto-selected (e.g., only one available),
                        // apply it to the quotation to ensure the order summary is updated
                        const checkedMethod = $('input[name="shipping_method"]:checked');
                        if (checkedMethod.length && checkedMethod.val() !== this.currentShippingMethod) {
                            this.updateShippingMethod(checkedMethod.val(), true);
                        }
                    }

                } else {
                    container.html(`<div class="alert alert-warning">${__('No shipping methods available for your location')}</div>`);
                }

            } catch (error) {
                console.error('Error loading shipping methods:', error);
                container.html(`<div class="alert alert-danger">${__('Error loading shipping methods')}</div>`);
            } finally {
                this.unfreezeElements(['step-section', 'order-summary']);
            }
        }

        attachShippingMethodEvents() {
            $('input[name="shipping_method"]').off('change').on('change', (e) => {
                const method = $(e.target).val();
                
                // Update selected class
                $('.shipping-method').removeClass('selected');
                $(e.target).closest('.shipping-method').addClass('selected');
                
                this.updateShippingMethod(method);
            });

            // Add selected class to already checked method on load
            const checkedMethod = $('input[name="shipping_method"]:checked');
            if (checkedMethod.length) {
                checkedMethod.closest('.shipping-method').addClass('selected');
            }
        }

        refreshShippingMethods() {
            return this.loadShippingMethods(true);
        }

        updateShippingMethod(shipping_method, notReload = false) {
            if (!shipping_method) return;
            this.freezeElements(['step-section', 'order-summary']);
            this.isUpdatingShipping = true;  
            this.currentShippingMethod = shipping_method;  

            // Check if a coupon or loyalty points are applied
            frappe.call({
                method: 'webshop.webshop.shopping_cart.cart.get_cart_quotation',
                callback: (r) => {
                    if (r.message && r.message.doc) {
                        const doc = r.message.doc;
                        // Check if a coupon is applied
                        if (doc.coupon_code || doc.gift_card_coupon) {
                            // Remove the coupon before applying the shipping rule
                            frappe.call({
                                method: 'webshop.webshop.shopping_cart.cart.remove_coupon_code',
                                callback: (r) => {
                                    if (r.message) {
                                        frappe.show_alert({
                                            message: __('The coupon has been removed to apply shipping rule'),
                                            indicator: 'blue'
                                        });
                                        // Apply the shipping rule
                                        this.applyShippingRule(shipping_method, notReload);
                                    }
                                }
                            });
                        } else if (doc.loyalty_points > 0) {
                            // Remove loyalty points before applying the shipping rule
                            frappe.call({
                                method: 'webshop.webshop.shopping_cart.cart.remove_loyalty_points',
                                callback: (r) => {
                                    if (r.message) {
                                        frappe.show_alert({
                                            message: __('The loyalty points have been removed to apply shipping rule'),
                                            indicator: 'blue'
                                        });
                                        // Apply the shipping rule
                                        this.applyShippingRule(shipping_method, notReload);
                                    }
                                }
                            });
                        } else {
                            // No coupon or loyalty points, apply the shipping rule directly
                            this.applyShippingRule(shipping_method, notReload);
                        }
                    } else {
                        // No cart data, apply the shipping rule directly
                        this.applyShippingRule(shipping_method, notReload);
                    }
                }
            });
        }
        
        applyShippingRule(shipping_method, notReload = false) {
            frappe.call({
                method: 'webshop.webshop.shopping_cart.cart.apply_shipping_rule',
                args: {
                    shipping_rule: shipping_method
                },
                callback: (r) => {
                    if (r.message && r.message.doc) {
                        this.updateOrderSummaryFromDoc(r.message.doc, notReload);
                    }
                    this.isUpdatingShipping = false; 
                    this.unfreezeElements(['step-section', 'order-summary']);
                }
            });
        }

        async updateOrderSummaryFromDoc(doc, notReload = false) {
            if (!doc || typeof doc === 'boolean') {
                // If no doc or doc is a boolean (case of remove), get updated doc
                frappe.call({
                    method: 'webshop.webshop.shopping_cart.cart.get_cart_quotation',
                    callback: (result) => {
                        if (result.message && result.message.doc) {
                            this.updateOrderSummaryFromDoc(result.message.doc, notReload);
                        }
                        this.unfreezeElements(['step-section', 'order-summary']);
                    }
                });
                return;
            }

            await this._updateOrderSummary(doc, notReload);
            this.unfreezeElements(['step-section', 'order-summary']);
        }

        async _updateOrderSummary(doc, notReload = false) {
            const subtotalElement = $('.bill-content.net-total.subtotal');
            const subtotalLabelElement = $('.bill-label.subtotal-element');

            const formattedSubtotal = await this.format_currency_value(doc.net_total, doc.currency);
            subtotalElement.text(formattedSubtotal);

            if (subtotalLabelElement.length) {
                //// Neoffice — toFixed(1) turned a count of items into "6.0
                //// Articles"; nobody buys a tenth of a basket. And the label
                //// was assembled from two fragments, which cannot be
                //// translated into a language that orders words differently —
                //// the server-rendered version of this same summary uses the
                //// placeholder string, so both sides now read alike.
                const qty = Math.round(parseFloat(doc.total_qty) || 0);
                $('.summary-details .collapsed-view.items-count').text(`(${__("{0} items", [qty])})`);
                subtotalLabelElement.text(__("Subtotal excl. tax ({0} items)", [qty]));
            }

            // Remove all existing lines except subtotal and total
            $('table.table tbody tr').not(':last').not(':first').remove();

            let summaryHtml = '';

            // 1. Shipping
            if (doc.shipping_charges && doc.shipping_charges > 0) {
                const formattedShipping = await this.format_currency_value(doc.shipping_charges, doc.currency);
                summaryHtml += `
                    <tr>
                        <td class="bill-label">${__("Shipping Charges")}</td>
                        <td class="bill-content text-right">${formattedShipping}</td>
                    </tr>`;
            }

            // 2. Taxes — customer-friendly labels: drop account codes ("22007 - ...")
            // and internal ids ("Economy_2kg"), keep the "TVA x%" segment for VAT
            // rows and merge them by rate (matches the cart/drawer summaries).
            if (doc.taxes) {
                const mergedTaxes = {};
                for (const tax of doc.taxes) {
                    if (!(tax.tax_amount > 0)) continue;
                    const raw = tax.description || 'Tax';
                    const parts = raw.split(' - ').filter(p => p.trim() && !/^\d+$/.test(p.trim()) && !p.includes('_'));
                    let label = parts.length ? parts.join(' - ') : raw;
                    let key = label;
                    const pct = parts.find(p => p.includes('%'));
                    if (pct) {
                        label = pct.trim();
                        const m = label.match(/(\d+(?:\.\d+)?)\s*%/);
                        if (m) key = 'vat-' + m[1];
                    }
                    if (mergedTaxes[key]) mergedTaxes[key].amount += tax.tax_amount;
                    else mergedTaxes[key] = { label: label, amount: tax.tax_amount };
                }
                for (const row of Object.values(mergedTaxes)) {
                    const formattedTaxAmount = await this.format_currency_value(row.amount, doc.currency);
                    summaryHtml += `
                        <tr>
                            <td class="bill-label">${row.label}</td>
                            <td class="bill-content text-right">${formattedTaxAmount}</td>
                        </tr>`;
                }
            }

            // 3. Coupon
            if (doc.coupon_code || doc.gift_card_coupon) {
                const formattedDiscount = await this.format_currency_value(doc.discount_amount, doc.currency);
                summaryHtml += `
                    <tr class="coupon-row">
                        <td class="bill-label text-success">
                            ${__("Coupon Discount")} (${doc.coupon_code || doc.gift_card_coupon})
                        </td>
                        <td class="bill-content text-right text-success">
                            -${formattedDiscount}
                        </td>
                    </tr>`;
            }

            // 4. Loyalty points
            if (doc.loyalty_amount && doc.loyalty_amount > 0) {
                summaryHtml += `
                    <tr class="loyalty-row">
                        <td class="bill-label text-success">
                            ${__("Loyalty Points")} (${doc.loyalty_points} ${__("points")})
                        </td>
                        <td class="bill-content text-right text-success">
                            -${format_currency(doc.loyalty_amount, doc.currency)}
                        </td>
                    </tr>`;
            }

            // Insert all lines after subtotal
            if (summaryHtml) {
                $('table.table tbody tr:first').after(summaryHtml);
            }

            // Update items if present
            if (doc.items) {
                for (const item of doc.items) {
                    const itemRow = $(`.order-item[data-item-code="${item.item_code}"]`);
                    if (itemRow.length) {
                        // Update quantity
                        //// Neoffice — toFixed(1) printed "3.0" for three
                        //// baskets. A fractional quantity (sold by weight)
                        //// still shows its decimals; a whole one does not.
                        itemRow.find('.cart-qty').val(String(parseFloat(item.qty)));
                        
                        // Update prices
                        const priceDetails = itemRow.find('.item-price-details');
                        if (priceDetails.length) {
                            // Update total price
                            const formattedAmount = await this.format_currency_value(item.amount, doc.currency);
                            priceDetails.find('.original-price').text(formattedAmount);

                            // Handle unit price
                            const unitPriceElement = priceDetails.find('.unit-price');
                            if (item.qty > 1) {
                                const formattedRate = await this.format_currency_value(item.rate, doc.currency);
                                const unitPriceHtml = `(${formattedRate} / ${item.uom})`;
                                
                                if (unitPriceElement.length) {
                                    unitPriceElement.text(unitPriceHtml);
                                } else {
                                    priceDetails.append(`<span class="unit-price">${unitPriceHtml}</span>`);
                                }
                            } else {
                                unitPriceElement.remove();
                            }

                            // Update discount if it exists
                            if (item.discount_percentage) {
                                const discountValue = parseFloat(item.discount_percentage).toFixed(1);
                                const baseAmount = item.price_list_rate * item.qty;
                                const formattedBaseAmount = await this.format_currency_value(baseAmount, doc.currency);
                                
                                let discountLine = priceDetails.find('.discount-line');
                                if (!discountLine.length) {
                                    discountLine = $('<div class="discount-line"></div>');
                                    priceDetails.prepend(discountLine);
                                }
                                
                                let priceBeforeDiscount = discountLine.find('.striked-price');
                                if (!priceBeforeDiscount.length) {
                                    priceBeforeDiscount = $('<span class="striked-price"></span>');
                                    discountLine.append(priceBeforeDiscount);
                                }
                                priceBeforeDiscount.text(formattedBaseAmount);
                                
                                let discountElement = discountLine.find('.discount');
                                if (!discountElement.length) {
                                    discountElement = $('<span class="discount"></span>');
                                    discountLine.append(discountElement);
                                }
                                discountElement.text(`-${discountValue}%`);
                            } else {
                                priceDetails.find('.discount-line').remove();
                            }
                        }
                    }
                }
            }

            // Update total
            const grandTotalRow = $('table.table tbody tr:last');
            if (grandTotalRow.length) {
                const formattedGrandTotal = await this.format_currency_value(doc.rounded_total || doc.grand_total, doc.currency);
                $('.summary-details .collapsed-view.total-amount').text(formattedGrandTotal);
                grandTotalRow.find('.net-total.grand-total').text(formattedGrandTotal);
            }

            // Update coupon interface
            frappe.call({
                method: 'webshop.webshop.shopping_cart.cart.get_coupon_html',
                callback: (r) => {
                    if (r.message) {
                        $('#coupon-form-container').html(r.message);
                        this.initializeCouponHandling();
                    }
                }
            });

            // Update loyalty points interface
            frappe.call({
                method: 'webshop.webshop.shopping_cart.cart.get_loyalty_points_html',
                callback: (r) => {
                    if (r.message) {
                        $('#loyalty-points-container').html(r.message);
                        this.initializeLoyaltyHandling();
                    }
                }
            });

            // Update input fields
            if (doc.loyalty_points) {
                $('.txtcoupon, .txtreferral_sales_partner').prop('disabled', true)
                    .attr('title', __('Please remove loyalty points first'));
                $('.bt-coupon').prop('disabled', true);
            } else {
                $('.txtcoupon, .txtreferral_sales_partner').prop('disabled', false)
                    .removeAttr('title');
                $('.bt-coupon').prop('disabled', false);
            }

            if (doc.coupon_code || doc.gift_card_coupon) {
                $('#loyalty-point-to-redeem').prop('disabled', true)
                    .attr('title', __('Please remove coupon code first'));
                $('.bt-loyalty-point').prop('disabled', true);
            } else {
                $('#loyalty-point-to-redeem').prop('disabled', false)
                    .removeAttr('title');
                $('.bt-loyalty-point').prop('disabled', false);
            }

            // Refresh shipping methods only if not already updating a method
            if (!this.isUpdatingShipping) {
                this.refreshShippingMethods();
            }
            // Refresh payment methods only if not already updating a method and on payment step
            if (!this.isUpdatingPayment && $('.step-section.active').attr('id') === 'step-payment' && !notReload) {
                this.refreshPaymentMethods();
            }
        }

        bindQuantityControls() {
            // Bind quantity change events
            $('.order-items').on('change', '.cart-qty', (e) => {
                e.stopPropagation();
                e.stopImmediatePropagation();
                const $input = $(e.target);
                const item_code = $input.attr('data-item-code');
                const newVal = $input.val();
                //// Neoffice — multi-warehouse: target the line of THIS stock
                //// source (empty attr = single-source line, server resolves).
                const warehouse = $input.attr('data-warehouse') || undefined;

                this.updateItemQuantity(item_code, newVal, warehouse);
            });

            // Bind + and - buttons
            // Use capture phase to intercept before cart_component.js handler
            const orderItems = document.querySelector('.order-items');
            if (orderItems) {
                orderItems.addEventListener('click', (e) => {
                    const btn = e.target.closest('.number-spinner button');
                    if (!btn) return;

                    // Stop propagation to prevent cart_component.js from handling this
                    e.stopPropagation();
                    e.stopImmediatePropagation();

                    const spinner = btn.closest('.number-spinner');
                    const input = spinner ? spinner.querySelector('input') : null;
                    if (!input) return;

                    const oldValue = parseInt(input.value.trim()) || 1;
                    let newVal = oldValue;

                    if (btn.getAttribute('data-dir') === 'up') {
                        newVal = oldValue + 1;
                    } else if (oldValue > 1) {
                        newVal = oldValue - 1;
                    }

                    input.value = newVal;
                    const item_code = input.getAttribute('data-item-code');
                    //// Neoffice — multi-warehouse: same per-source targeting.
                    const warehouse = input.getAttribute('data-warehouse') || undefined;
                    this.updateItemQuantity(item_code, newVal, warehouse);
                }, true); // Use capture phase
            }
        }

        updateItemQuantity(item_code, qty, warehouse) {
            this.freezeElements(['order-summary']);
            
            // Check if a coupon or loyalty points are applied
            frappe.call({
                method: 'webshop.webshop.shopping_cart.cart.get_cart_quotation',
                callback: (r) => {
                    if (r.message && r.message.doc) {
                        const doc = r.message.doc;
                        // Check if a coupon or loyalty points are applied
                        if (doc.coupon_code || doc.gift_card_coupon) {
                            // Remove the coupon before updating the quantity
                            frappe.call({
                                method: 'webshop.webshop.shopping_cart.cart.remove_coupon_code',
                                callback: (r) => {
                                    if (r.message) {
                                        frappe.show_alert({
                                            message: __('The coupon has been removed to update item quantity'),
                                            indicator: 'blue'
                                        });
                                        // Update the quantity
                                        this.performItemQuantityUpdate(item_code, qty, warehouse);
                                    }
                                }
                            });
                        } else if (doc.loyalty_points) {
                            // Remove loyalty points before updating the quantity
                            frappe.call({
                                method: 'webshop.webshop.shopping_cart.cart.remove_loyalty_points',
                                callback: (r) => {
                                    if (r.message) {
                                        frappe.show_alert({
                                            message: __('The loyalty points have been removed to update item quantity'),
                                            indicator: 'blue'
                                        });
                                        // Update the quantity
                                        this.performItemQuantityUpdate(item_code, qty, warehouse);
                                    }
                                }
                            });
                        } else {
                            // No coupon or loyalty points, update quantity directly
                            this.performItemQuantityUpdate(item_code, qty, warehouse);
                        }
                    } else {
                        // No cart data, update quantity directly
                        this.performItemQuantityUpdate(item_code, qty, warehouse);
                    }
                }
            });
        }
        
        performItemQuantityUpdate(item_code, qty, warehouse) {
            // Use nested callback to ensure get_cart_quotation runs AFTER update_cart completes
            frappe.call({
                method: 'webshop.webshop.shopping_cart.cart.update_cart',
                args: {
                    item_code: item_code,
                    qty: qty,
                    with_items: true,
                    //// Neoffice — multi-warehouse: keep the edit on the right line.
                    warehouse: warehouse !== undefined ? warehouse : undefined
                },
                callback: (r) => {
                    if (r.message) {
                        // Update cart count
                        webshop.webshop.shopping_cart.set_cart_count(false);

                        // Now get fresh cart data - this call starts AFTER update_cart callback fires
                        frappe.call({
                            method: 'webshop.webshop.shopping_cart.cart.get_cart_quotation',
                            callback: (result) => {
                                if (result.message && result.message.doc) {
                                    this.updateOrderSummaryFromDoc(result.message.doc);
                                }
                                this.unfreezeElements(['order-summary']);
                            }
                        });
                    } else {
                        this.unfreezeElements(['order-summary']);
                    }
                }
            });
        }

        initializeLoyaltyHandling() {
            // Apply loyalty points
            $('.bt-loyalty-point').on('click', () => {
                const points = parseInt($('#loyalty-point-to-redeem').val());
                if (!points || points <= 0) {
                    frappe.throw(__('Please enter a valid number of points'));
                    return;
                }

                // Get current doc
                frappe.call({
                    method: 'webshop.webshop.shopping_cart.cart.get_cart_quotation',
                    callback: (r) => {
                        if (r.message && r.message.doc) {
                            const doc = r.message.doc;
                            // If a coupon is applied, remove it first
                            if (doc.coupon_code || doc.gift_card_coupon) {
                                this.freezeElements(['order-summary']);
                                frappe.call({
                                    method: 'webshop.webshop.shopping_cart.cart.remove_coupon_code',
                                    callback: (r) => {
                                        if (r.message) {
                                            // Once coupon is removed, apply loyalty points
                                            this.applyLoyaltyPoints(points);
                                        }
                                    }
                                });
                            } else {
                                this.applyLoyaltyPoints(points);
                            }
                        }
                    }
                });
            });

            // Remove loyalty points
            $('.bt-remove-loyalty').on('click', () => {
                this.freezeElements(['order-summary']);
                frappe.call({
                    method: 'webshop.webshop.shopping_cart.cart.remove_loyalty_points',
                    callback: (r) => {
                        if (r.message) {
                            this.updateOrderSummaryFromDoc(r.message);
                            frappe.show_alert({
                                message: __('Loyalty points removed'),
                                indicator: 'blue'
                            });
                        }
                        this.unfreezeElements(['order-summary']);
                    }
                });
            });

            // Limit input to maximum available points
            $('#loyalty-point-to-redeem').off('input').on('input', function() {
                const maxPoints = parseFloat($(this).attr('max'));
                let points = parseFloat($(this).val());
                
                if (points > maxPoints) {
                    $(this).val(maxPoints);
                }
            });
        }

        applyLoyaltyPoints(points) {
            this.freezeElements(['order-summary']);
            try {
                frappe.call({
                    method: 'webshop.webshop.shopping_cart.cart.apply_loyalty_points',
                    args: {
                        points: points
                    },
                    callback: (r) => {
                        if (r.message) {
                            this.updateOrderSummaryFromDoc(r.message);
                            frappe.show_alert({
                                message: __('Loyalty points applied successfully'),
                                indicator: 'green'
                            });
                        }
                        this.unfreezeElements(['order-summary']);
                    }
                });
            } catch (error) {
                console.error(error);
                this.unfreezeElements(['order-summary']);
                return;
            }
        }

        initializeCouponHandling() {
            // Apply coupon
            $('.bt-coupon').on('click', () => {
                const coupon = $('.txtcoupon').val();
                if (!coupon) {
                    frappe.throw(__('Please enter a coupon code'));
                    return;
                }

                // Get current doc
                frappe.call({
                    method: 'webshop.webshop.shopping_cart.cart.get_cart_quotation',
                    callback: (r) => {
                        if (r.message && r.message.doc) {
                            const doc = r.message.doc;
                            // If loyalty points are applied, remove them first
                            if (doc.loyalty_points) {
                                this.freezeElements(['order-summary']);
                                frappe.call({
                                    method: 'webshop.webshop.shopping_cart.cart.remove_loyalty_points',
                                    callback: (r) => {
                                        if (r.message) {
                                            // Once loyalty points are removed, apply coupon
                                            this.applyCoupon(coupon);
                                        }
                                    }
                                });
                            } else {
                                this.applyCoupon(coupon);
                            }
                        }
                    }
                });
            });

            // Remove coupon
            $('.bt-remove-coupon').on('click', () => {
                this.freezeElements(['order-summary']);
                frappe.call({
                    method: 'webshop.webshop.shopping_cart.cart.remove_coupon_code',
                    callback: (r) => {
                        if (r.message) {
                            this.updateOrderSummaryFromDoc(r.message);
                            frappe.show_alert({
                                message: __('Coupon code removed'),
                                indicator: 'blue'
                            });
                        }
                        this.unfreezeElements(['order-summary']);
                    }
                });
            });
        }

        applyCoupon(coupon) {
            this.freezeElements(['order-summary']);
            try {
                frappe.call({
                    method: 'webshop.webshop.shopping_cart.cart.apply_coupon_code',
                    args: {
                        applied_code: coupon,
                        applied_referral_sales_partner: $('.txtreferral_sales_partner').val() || ''
                    },
                    callback: (r) => {
                        if (r.message) {
                            this.updateOrderSummaryFromDoc(r.message);
                            frappe.show_alert({
                                message: __('Coupon code applied successfully'),
                                indicator: 'green'
                            });
                        }
                        this.unfreezeElements(['order-summary']);
                    }
                });
            } catch (error) {
                console.error(error);
                this.unfreezeElements(['order-summary']);
            }
        }

        setupPaymentMethods() {
            if (this.paymentMethodsInitialized) {
                return;
            }
            frappe.call({
                method: 'webshop.templates.pages.checkout.get_payment_methods',
                callback: (r) => {
                    if (!r.message) {
                        console.error("No response from get_payment_methods API");
                        return;
                    }

                    if (r.message.error) {
                        console.error("Error loading payment methods:", r.message.message);
                        $('#payment-methods-container').html(`
                            <div class="alert alert-danger">
                                ${r.message.message || __("An error occurred while loading payment methods")}
                            </div>
                        `);
                        return;
                    }

                    if (!r.message.methods || !Array.isArray(r.message.methods)) {
                        console.error("Invalid response format for payment methods:", r.message);
                        return;
                    }

                    this.paymentMethods = r.message.methods;

                    // Get rounded_total from quotation
                    frappe.call({
                        method: 'webshop.webshop.shopping_cart.cart.get_cart_quotation',
                        callback: (result) => {
                            
                            if (!result.message || !result.message.doc) {
                                console.error("Failed to retrieve quotation");
                                return;
                            }

                            const rounded_total = result.message.doc.rounded_total;
                            
                            const container = $('#payment-methods-container');
                            container.empty();

                            // If total is 0, show only direct validation button
                            if (rounded_total === 0) {
                                const validationButton = `
                                    <div class="payment-method-item selected frappe-card p-5 mb-3 d-flex justify-content-between align-items-center" data-method-id="direct_validation">
                                        <div class="form-check mb-3" id="terms-acceptance-container">
                                            <input type="checkbox" class="form-check-input" id="terms-acceptance" required>
                                            <label class="form-check-label" for="terms-acceptance">
                                                ${__("I agree to the")} <a href="#terms-title" class="terms-link">${result.message.doc.tc_name || __("terms and conditions")}</a>
                                            </label>
                                        </div>
                                        <div class="mt-4 d-flex justify-content-end">
                                            <button class="btn btn-primary w-100" 
                                                id="validate_zero_amount" 
                                                disabled
                                                data-toggle="tooltip"
                                                data-placement="top"
                                                title="${__('Please accept the terms and conditions to continue')}">
                                                ${__('Validate Order')}
                                            </button>
                                        </div>
                                    </div>
                                `;
                                container.html(validationButton);

                                // Initialize tooltip
                                $('#validate_zero_amount').tooltip();

                                $('#terms-acceptance').on('change', function() {
                                    const $button = $('#validate_zero_amount');
                                    const isChecked = this.checked;
                                    $button.prop('disabled', !isChecked);
                                    
                                    // Handle tooltip based on state
                                    if (isChecked) {
                                        $button.tooltip('disable');
                                    } else {
                                        $button.tooltip('enable');
                                    }
                                });

                                $('#validate_zero_amount').on('click', () => {
                                    // Use global payment lock
                                    if (!this.startPaymentProcessing()) {
                                        return;
                                    }
                                    
                                    this.freezeElements(['payment-method-item']);
                                    frappe.call({
                                        method: 'webshop.controllers.payment_handler.handle_direct_order',
                                        args: {
                                            idempotency_token: this.getIdempotencyToken()
                                        },
                                        callback: (r) => {
                                            if (r.message) {
                                                if (r.message.status === "success") {
                                                    window.location.href = r.message.redirect_to;
                                                } else {
                                                    frappe.msgprint({
                                                        title: __('Error'),
                                                        indicator: 'red',
                                                        message: r.message.message
                                                    });
                                                    this.stopPaymentProcessing();
                                                }
                                                this.unfreezeElements(['payment-method-item']);
                                            }
                                        },
                                        error: () => {
                                            this.stopPaymentProcessing();
                                            this.unfreezeElements(['payment-method-item']);
                                        }
                                    });
                                });
                            } else {
                                // Show all payment methods
                                this.paymentMethods.forEach(method => {
                                    const cleanId = method.id.replace(/[^a-zA-Z0-9]/g, '_');
                                    
                                    const methodHtml = `
                                        <div class="payment-method-item frappe-card p-5 mb-3" data-method-id="${cleanId}">
                                            <div class="payment-method-header d-flex align-items-center justify-content-between">
                                                <div class="payment-method-title">
                                                    <input type="radio" 
                                                           id="method_${cleanId}" 
                                                           name="payment_method" 
                                                           class="custom-control-input hide"
                                                           value="${method.id}"
                                                           data-rate="${method.rate}"
                                                           ${this.paymentMethods.length === 1 || method.id === this.currentMethod ? 'checked' : ''}>
                                                    <label for="method_${cleanId}">
                                                        ${method.title || method.id}
                                                    </label>
                                                </div>
                                                                ${method.logo || ''}
                                                            </div>
                                                            ${method.description ? `
                                                                <div class="payment-method-description text-muted">
                                                                    ${method.description}
                                                                </div>
                                                            ` : ''}
                                            <div class="payment-method-form mt-3 pt-3" id="payment-form-${cleanId}"></div>
                                        </div>
                                    `;
                                    container.append(methodHtml);
                                });

                                // Attach event handlers
                                $('.payment-method-item').on('click', (e) => {
                                    const $item = $(e.currentTarget);
                                    const $radio = $item.find('input[type="radio"]');
                                    
                                    if (!$(e.target).closest('.payment-method-form').length) {
                                        $radio.prop('checked', true);
                                        this.handlePaymentMethodChange($radio.val());
                                    }
                                });

                                // Get saved payment method
                                frappe.call({
                                    method: 'webshop.webshop.shopping_cart.cart.get_cart_quotation',
                                    callback: (result) => {
                                        if (result.message && result.message.doc && result.message.doc.payment_method) {
                                            const savedMethod = result.message.doc.payment_method;
                                            $(`#method_${savedMethod.replace(/[^a-zA-Z0-9]/g, '_')}`).prop('checked', true);
                                            this.handlePaymentMethodChange(savedMethod);
                                        } else if (this.paymentMethods.length > 0) {
                                            // if no payment method is saved, select the first one by default
                                            const firstMethod = this.paymentMethods[0];
                                            $(`#method_${firstMethod.id.replace(/[^a-zA-Z0-9]/g, '_')}`).prop('checked', true);
                                            this.handlePaymentMethodChange(firstMethod.id);
                                        }
                                    }
                                });

                                // Initialize tooltips
                                $('[data-toggle="tooltip"]').tooltip();
                            }
                        }
                    });
                }
            });

            this.paymentMethodsInitialized = true;
            this.unfreeze('step-section');
        }

        handlePaymentMethodChange(methodId) {
            // Reset payment processing state when changing payment method
            if (this.isProcessingPayment) {
                console.log("Resetting payment state due to payment method change");
                this.stopPaymentProcessing();
            }
            
            const method = this.paymentMethods.find(m => m.id === methodId);
            if (!method) {
                console.error('Method not found:', methodId);
                return;
            }
        
            // Save the method in the quotation
            frappe.call({
                method: 'webshop.templates.pages.checkout.update_payment_method',
                args: {
                    payment_method: methodId
                }
            });
        
            // Update the selected method
            $('.payment-method-item').removeClass('selected');
            const cleanId = method.id.replace(/[^a-zA-Z0-9]/g, '_');
            $(`[data-method-id="${cleanId}"]`).addClass('selected');
            $(`#method_${cleanId}`).prop('checked', true);
        
            // Hide all payment forms
            $('.payment-method-form').hide();
        
            // Prepare the container for the payment form
            const formId = `payment-form-${cleanId}`;
            const $form = $(`#${formId}`);
        
            // If the template for this method is already loaded, just show it
            if (this.loadedPaymentTemplates[cleanId]) {
                 $form.show();
                 // Update button state when showing cached template
                 setTimeout(() => {
                     this.updatePaymentButtonState();
                 }, 50);
                 return;
            }
        
            // Any existing content in the form will be removed
            $form.empty().off();

            //// Neoffice — une méthode BASCULÉE sur le moteur d'intentions se
            //// dessine ici plutôt que par son gabarit. Toutes les autres
            //// passent tout droit : `start_cart_intent` répond `legacy` tant
            //// que la case `use_payment_intent` n'est pas cochée, et le code
            //// ci-dessous est alors rigoureusement celui d'avant.
            //// Au moindre doute — appel en échec, action inattendue — on
            //// retombe sur le gabarit : mieux vaut le chemin connu qu'un écran
            //// vide sur un paiement.
            const self_ = this;
            frappe.call({
                method: 'webshop.templates.pages.checkout.start_cart_intent',
                args: { payment_gateway_account: method.payment_gateway_account },
                callback: function (r) {
                    //// Neoffice — `send_translations` marche sur le desk, pas ici :
                    //// le `frappe.call` du site ne fusionne pas `__messages`, il se
                    //// contente de passer la réponse. Sans cette ligne, un tunnel
                    //// francophone lit « Or type 12345 in the app. » sous le QR.
                    if (r && r.__messages) $.extend(frappe._messages || (frappe._messages = {}), r.__messages);
                    const a = (r && r.message) || {};
                    if (a.action && a.action !== 'legacy' && self_.showIntentScreen(a, $form, cleanId)) return;
                    self_.loadLegacyPaymentTemplate(method, $form, cleanId, formId);
                },
                error: function () { self_.loadLegacyPaymentTemplate(method, $form, cleanId, formId); },
            });
        }

        //// Neoffice — l'écran d'une méthode passée aux intentions. Rend `true`
        //// s'il a su afficher quelque chose ; `false` renvoie au gabarit.
        showIntentScreen(a, $form, cleanId) {
            if (a.action === 'redirect' && a.url) {
                $form.html('<div class="text-center py-4"><a class="btn btn-primary" href="' +
                    frappe.utils.escape_html(a.url) + '">' + __('Continue to payment') + '</a></div>').show();
                return true;
            }
            if (a.action === 'qr' && a.payload && a.payload.qr_svg) {
                const code = a.payload.pairing_token
                    ? '<p class="text-muted mt-2">' + __('Or type {0} in the app.', [a.payload.pairing_token]) + '</p>'
                    : '';
                $form.html('<div class="text-center py-4"><div class="d-inline-block p-3 bg-white border rounded">' +
                    a.payload.qr_svg + '</div>' + code +
                    '<p class="text-muted mt-3 intent-attente">' + __('Waiting for your payment…') + '</p></div>').show();
                //// Neoffice — un QR ne redirige pas : sans surveillance, le client
                //// paie sur son téléphone et la page reste figée pour toujours.
                //// Le signal principal est l'évènement `payment.intent.<nom>.updated`
                //// que publie chaque pilote de `payments` — le même que son propre
                //// dialogue TWINT écoute — et le sondage n'est qu'un filet si la
                //// socket tombe. C'est la Payment Request qui tranche, pas
                //// l'intention : elle seule dit que la commande est passée.
                this.watchIntent(a.intent, $form);
                return true;
            }
            return false;
        }

        //// Neoffice — la surveillance d'une intention, jusqu'à la commande.
        watchIntent(intent, $form) {
            if (!intent) return;
            const self_ = this;
            const canal = 'payment.intent.' + intent + '.updated';
            let fini = false, restant = 60;   // 5 minutes à 5 s
            const arreter = () => {
                if (self_._intentTimer) { clearInterval(self_._intentTimer); self_._intentTimer = null; }
                try { if (frappe.realtime && frappe.realtime.off) frappe.realtime.off(canal, demander); }
                catch (e) { /* la socket a pu partir avant nous */ }
            };
            const demander = () => {
                if (fini) return;
                frappe.call({
                    method: 'webshop.templates.pages.checkout.cart_intent_state',
                    args: { intent: intent },
                    callback: function (r) {
                        const m = (r && r.message) || {};
                        if (fini || !m.done) return;
                        fini = true; arreter();
                        if (m.redirect_to) { window.location.href = m.redirect_to; return; }
                        window.location.reload();
                    },
                    error: function () { /* le filet reprendra au tour suivant */ },
                });
            };
            try {
                //// S'abonner CONNECTE la socket : sur une page publique elle
                //// reste inerte tant que personne n'écoute.
                if (frappe.realtime && frappe.realtime.on) frappe.realtime.on(canal, demander);
            } catch (e) { /* pas de temps réel ici : le filet suffit */ }
            this._intentTimer = setInterval(() => {
                restant -= 1;
                if (restant <= 0) {
                    arreter();
                    $form.find('.intent-attente').text(__('Payment not received. You can try again.'));
                    return;
                }
                demander();
            }, 5000);
            demander();
            window.addEventListener('pagehide', arreter);
        }

        //// Neoffice — le chargement historique, extrait tel quel pour être
        //// appelé depuis les deux branches. Rien n'y a changé.
        loadLegacyPaymentTemplate(method, $form, cleanId, formId) {
            frappe.call({
                method: 'webshop.templates.pages.checkout.get_payment_template',
                args: {
                    payment_gateway_account: method.payment_gateway_account,
                    context: {
                        payment_form_id: formId,
                        card_element_id: `card-element-${cleanId}`,
                        card_errors_id: `card-errors-${cleanId}`,
                        submit_id: `submit-${cleanId}`,
                        paypal_button_id: `paypal-button-${cleanId}`,
                        amount: this.grandTotal,
                        currency: method.currency,
                        payer_name: frappe.session.user_fullname,
                        payer_email: frappe.session.user
                    }
                },
                callback: (r) => {
                    if (!r.error && r.message) {
                        // Server-side failures come back as {error: true, message} inside
                        // r.message — without this guard `r.message.html` is undefined and
                        // gets coerced into a literal "undefined" in the form container.
                        if (r.message.error) {
                            console.error("Payment template error:", r.message.message);
                            $form.html(`<div class="alert alert-danger">${r.message.message || __("Unable to load this payment method")}</div>`);
                            return;
                        }
                        try {
                            // Cleanup old gateway instances if they exist
                            if (window[`destroy${method.id}Gateway`]) {
                                window[`destroy${method.id}Gateway`]();
                            }
        
                            // Create a temporary container to separate HTML and scripts
                            const tempContainer = document.createElement('div');
                            tempContainer.innerHTML = r.message.html;
        
                            // Extract scripts and remove script content from container
                            const scripts = tempContainer.getElementsByTagName('script');
                            const scriptContents = [];
                            while (scripts.length > 0) {
                                const script = scripts[0];
                                scriptContents.push(script.textContent);
                                script.parentNode.removeChild(script);
                            }
        
                            // Inject HTML (without scripts) into the form container
                            $form.html(tempContainer.innerHTML);
        
                            // Create a function to initialize the payment form in an isolated scope
                            const initializePaymentForm = new Function(`
                                return function(formId, method, config) {
                                    ${scriptContents.join('\n')}
                                }
                            `)();
        
                            // Initialize the payment form
                            initializePaymentForm(formId, method, r.message.config || {});
        
                            // If the gateway requires a specific initialization, launch it
                            if (method.client_configuration) {
                                try {
                                    const config = JSON.parse(method.client_configuration);
                                    if (config.init_function && window[config.init_function]) {
                                        const settings = r.message.config || {};
                                        const requiredFields = config.required_fields || [];
                                        const initParams = {};
                                        requiredFields.forEach(field => {
                                            if (settings[field]) {
                                                initParams[field] = settings[field];
                                            }
                                        });
                                        window[config.init_function](initParams);
                                    }
                                } catch (e) {
                                    console.error('Error initializing gateway:', e);
                                }
                            }
        
                            // Show the form with an animation
                            $form.fadeIn();
        
                            // Store in the cache that the template
                            this.loadedPaymentTemplates[cleanId] = {
                                loaded: true,
                                destroy: typeof window[`destroy${method.id}Gateway`] === 'function'
                                        ? window[`destroy${method.id}Gateway`]
                                        : null
                            };
                            
                            // Update button state after loading template
                            setTimeout(() => {
                                this.updatePaymentButtonState();
                            }, 100);
                        } catch (e) {
                            console.error('Error loading payment template:', e);
                            frappe.msgprint({
                                title: __('Error'),
                                message: __('Error loading payment template'),
                                indicator: 'red'
                            });
                        }
                    } else {
                        console.error('Error loading payment template:', r.message);
                        frappe.msgprint({
                            title: __('Error'),
                            message: r.message.message || __('Error loading payment template'),
                            indicator: 'red'
                        });
                    }
                }
            });
        }

        getPaymentFormData() {
            const fullname = $('[name="contact_first_name"]').val() + ' ' + $('[name="contact_last_name"]').val();
            const email = $('[name="contact_email"]').val();
            const phone = $('[name="contact_phone"]').val();

            // Return data as an object
            return {
                fullname: fullname,
                email: email,
                phone: phone
            };
        }

        initPaymentForm(formId) {
            const formData = this.getPaymentFormData();
            const cardholderName = $(`#${formId} input[name="cardholder-name"]`);
            const cardholderEmail = $(`#${formId} input[name="cardholder-email"]`);

            // Pre-fill fields if empty
            if (!cardholderName.val()) cardholderName.val(formData.fullname);
            if (!cardholderEmail.val()) cardholderEmail.val(formData.email);

            // Return data for use in callbacks
            return {
                cardholderName: cardholderName.val(),
                cardholderEmail: cardholderEmail.val(),
                ...formData
            };
        }

        refreshPaymentMethods() {
            this.isUpdatingPayment = true;
            // Invalidate the cache to force reloading with new data
            this.loadedPaymentTemplates = {};
            this.paymentMethodsInitialized = false;  
            this.setupPaymentMethods();
            this.isUpdatingPayment = false;
        }

        showMessagePayment(type, message) {
            // Hide all messages
            document.querySelectorAll('.payment-message').forEach(el => {
                el.style.display = 'none';
                el.classList.remove('show');
            });
            
            // Show appropriate message
            const messageEl = document.querySelector('.' + type + '.payment-message');
            if (messageEl) {
                messageEl.textContent = message;
                messageEl.style.display = 'block';
                // Force reflow for animation to work
                messageEl.offsetHeight;
                messageEl.classList.add('show');
            }
            
            // Show Frappe alert
            frappe.show_alert({
                message: __(message),
                indicator: type === 'error' ? 'red' : 'green'
            });
        }

        errorShowPaymentMessage(message) {
            const paymentMethod = document.querySelector('.payment-method-item.selected');
            if (paymentMethod) {
                paymentMethod.classList.add('shake');
                setTimeout(() => {
                    paymentMethod.classList.remove('shake');
                }, 500);
            }
            
            // Show Frappe alert
            frappe.show_alert({
                message: __(message),
                indicator: 'red'
            });
        }

        isValidEmail(email) {
            const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            return emailRegex.test(email);
        }

        async checkGiftCardOnly() {
            frappe.call({
                method: 'webshop.webshop.shopping_cart.cart.get_cart_quotation',
                callback: async (r) => {
                    if (!r.exc && r.message && r.message.doc) {
                        const quotation = r.message.doc;
                        let allGiftCards = false;
                        
                        // Check each item sequentially
                        const checkItems = async () => {
                            for (let item of quotation.items || []) {
                                try {
                                    const result = await new Promise((resolve, reject) => {
                                        frappe.call({
                                            method: 'webshop.webshop.shopping_cart.cart.is_gift_card_item',
                                            args: {
                                                item_code: item.item_code
                                            },
                                            callback: (result) => {
                                                resolve(result.message === 1);
                                            },
                                            error: (err) => reject(err)
                                        });
                                    });
                                    
                                    if (!result) {
                                        allGiftCards = false;
                                        return false; // Exit loop if item is not a gift card
                                    }
                                    allGiftCards = true;
                                } catch (err) {
                                    console.error('Error checking gift card:', err);
                                    allGiftCards = false;
                                    return false;
                                }
                            }
                            return true;
                        };

                        await checkItems();
                        this.isGiftCardOnly = allGiftCards;
                    }
                }
            });
        }

        // Global payment lock methods
        startPaymentProcessing() {
            if (this.isProcessingPayment) {
                console.log("Payment already in progress, blocking new payment attempt");
                return false;
            }
            
            this.isProcessingPayment = true;
            
            // Disable ALL payment buttons
            $('.btn-submit-payment').prop('disabled', true);
            
            // Set a safety timeout to re-enable buttons after 60 seconds
            this.paymentTimeout = setTimeout(() => {
                console.warn("Payment timeout reached, re-enabling buttons");
                this.stopPaymentProcessing();
            }, 60000); // 60 seconds timeout
            
            return true;
        }

        stopPaymentProcessing() {
            // Prevent recursive calls
            if (this._isResetting) {
                return;
            }
            this._isResetting = true;
            
            this.isProcessingPayment = false;
            
            // Clear timeout if exists
            if (this.paymentTimeout) {
                clearTimeout(this.paymentTimeout);
                this.paymentTimeout = null;
            }
            
            // Reset idempotency token for next payment attempt
            this.resetIdempotencyToken();
            
            // Reset all payment buttons to their original state
            $('.btn-submit-payment').each(function() {
                const $btn = $(this);
                // Remove spinner and restore original text based on button ID
                if ($btn.find('.spinner-border').length > 0) {
                    if ($btn.attr('id').includes('twint')) {
                        $btn.html($btn.data('original-text') || 'Pay');
                    } else if ($btn.attr('id').includes('stripe')) {
                        $btn.html($btn.data('original-text') || 'Pay');
                    } else if ($btn.attr('id').includes('paypal')) {
                        $btn.html($btn.data('original-text') || 'Pay with PayPal');
                    } else if ($btn.attr('id').includes('validate_zero_amount')) {
                        $btn.html($btn.data('original-text') || 'Validate Order');
                    } else {
                        $btn.html($btn.data('original-text') || 'Validate my order');
                    }
                }
            });
            
            // Re-enable payment buttons based on their terms acceptance state
            if (this.updatePaymentButtonState) {
                this.updatePaymentButtonState();
            } else {
                $('.payment-method-item').each(function() {
                    const $item = $(this);
                    const $submitBtn = $item.find('.btn-submit-payment');
                    const $termsCheckbox = $item.find('#terms-acceptance');
                    
                    if ($item.hasClass('selected') && $termsCheckbox.prop('checked')) {
                        $submitBtn.prop('disabled', false);
                    }
                });
            }
            
            // Clear the resetting flag
            this._isResetting = false;
        }

        // Check if payment is in progress
        isPaymentInProgress() {
            return this.isProcessingPayment;
        }

        // Generate idempotency token
        generateIdempotencyToken() {
            // Generate a unique token using timestamp and random string
            const timestamp = Date.now();
            const randomString = Math.random().toString(36).substring(2, 15);
            const sessionId = frappe.session.user || 'guest';
            return `${sessionId}-${timestamp}-${randomString}`;
        }

        // Get current idempotency token
        getIdempotencyToken() {
            // Generate a new token if payment was completed or failed
            if (!this.paymentIdempotencyToken || !this.isProcessingPayment) {
                this.paymentIdempotencyToken = this.generateIdempotencyToken();
            }
            return this.paymentIdempotencyToken;
        }

        // Reset idempotency token after payment completion
        resetIdempotencyToken() {
            this.paymentIdempotencyToken = this.generateIdempotencyToken();
        }
    }

    window.checkout_manager = new CheckoutManager();
});