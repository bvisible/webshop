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
            //// Neoffice — lu par templates/payments/webshopsi.html via
            //// checkout_manager.quotationName : ce n'est pas une variable morte.
            this.quotationName = null;
            this.currentMethod = null;
            this.isGiftCardOnly = false;
            this.paymentMethodsInitialized = false;
            // Initialisation du cache pour les templates de paiement
            this.loadedPaymentTemplates = {};

            this.setupListeners();
            this.setupAddressListeners();
            //// Neoffice — address book: bind first (delegated, so it survives
            //// the list being re-rendered), then load and draw the cards.
            this.bindAddressPickers();
            this.loadAddressBook();
            this.bindQuantityControls();
            this.checkGiftCardOnly();
            this.showStep('step-address');
            this.loadExistingAddress();

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
            
            //// Neoffice — this used to read the quotation, then WRITE the very
            //// address it had just read back to the server. update_cart_address
            //// is not a cheap call: it reloads the quotation, re-reads the
            //// address, re-applies cart settings, recalculates every tax and
            //// saves the document — measured at 517 ms, on every single page
            //// load, for a value that had not changed.
            ////
            //// And the server already handles the case that write was meant to
            //// cover: get_cart_quotation assigns the default billing address
            //// itself when the quotation has none (cart.py, "if doc and not
            //// doc.customer_address and addresses"). The branch here only ran
            //// when customer_address was ALREADY set — precisely when there
            //// was nothing to do.
            ////
            //// The old try/catch could never fire either: frappe.call does not
            //// throw synchronously, so its unfreeze was dead code. callServer
            //// releases the screen in a finally block, failure included.
            this.callServer(
                'webshop.webshop.shopping_cart.cart.get_cart_quotation',
                {},
                {freeze: ['step-section', 'order-summary']}
            ).then(message => {
                const quotation = message && message.doc;
                if (!quotation) return;
                this.quotationName = quotation.name;
                if (quotation.customer_address) {
                    $('#billing_address_name').val(quotation.customer_address);
                    //// The card list may already be drawn (or not yet) — see
                    //// syncAddressPickerSelection. Re-deriving is free.
                    this.syncAddressPickerSelection('billing');
                }
                this.updateOrderSummaryFromDoc(quotation);
            }).catch(() => {
                /* callServer already told the shopper and released the screen */
            });
        }

        //// Neoffice — isLoading gates the step buttons: handleNextStep and
        //// handlePrevStep both start with `if (this.isLoading) return`. That
        //// guard is right — two overlapping step changes corrupt the quotation —
        //// but it used to swallow the click in COMPLETE silence: arriving on the
        //// payment step loads five gateway templates, and during that second or
        //// two "Retour à la livraison" simply did nothing, with no cursor, no
        //// disabled state, nothing. The shopper clicks again, harder.
        ////
        //// Making it a property lets the buttons reflect the state instead:
        //// every existing `this.isLoading = …` now also disables them, wherever
        //// it is written, with no call site to remember to update.
        get isLoading() {
            return this._isLoading;
        }

        set isLoading(valeur) {
            this._isLoading = valeur;
            $('.next-step, .prev-step')
                .prop('disabled', !!valeur)
                .toggleClass('is-busy', !!valeur);
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
                    //// Neoffice — this loop was a no-op. jQuery passes the DOM
                    //// element as `this` inside .each(), and the `.bind(this)`
                    //// replaced it with the CheckoutManager instance: every
                    //// `$(this).attr('name')` returned undefined, the `if (name)`
                    //// never passed, and initialFormValues stayed empty for the
                    //// life of the page.
                    ////
                    //// Consequence, and it is the reason the address step talks
                    //// to the server so much: with no reference values, the
                    //// comparison below never matched, so pendingChanges was
                    //// never cleared. Typing a character and undoing it still
                    //// counted as a change — the confirmation dialog opened on
                    //// every "next step" and applyPendingChanges fired its 4 to
                    //// 7 sequential calls even when nothing had actually moved.
                    ////
                    //// An arrow function keeps `this` as the instance while
                    //// .each() hands us the element as an argument.
                    $('#address-form input, #address-form select').each((_, el) => {
                        const $el = $(el);
                        const name = $el.attr('name') || $el.attr('id');
                        if (name) {
                            this.initialFormValues[name] = $el.is(':checkbox')
                                ? $el.prop('checked')
                                : $el.val();
                        }
                    });
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

            //// Neoffice — was bound on 'change click' for BOTH the checkbox and
            //// its label, and the label branch flipped the box by hand
            //// (preventDefault + prop('checked', !checked) + trigger).
            ////
            //// A <label for> already ticks its box natively, which already fires
            //// 'change'. Adding a manual flip on top meant one click could run
            //// the handler twice and undo itself: the box ended up unticked at
            //// random, "Payer" stayed disabled, and nothing on screen explained
            //// why. Caught by the payment tests, which failed one run in three.
            ////
            //// The only thing the label branch really protected is the "terms
            //// and conditions" LINK living inside the label: clicking it must
            //// open the terms, not accept them. That is already handled — the
            //// '.terms-link' handler above calls preventDefault(), which stops
            //// the label from ticking the box — so the box can simply behave
            //// like a checkbox.

            //// Neoffice — ne plus exiger `.selected` sur la tuile.
            ////
            //// Le gestionnaire ne s'appliquait qu'à `.payment-method-item.selected
            //// #terms-acceptance`, et updatePaymentButtonState() ne parcourait que
            //// les tuiles sélectionnées. Il suffisait donc que la tuile n'ait pas
            //// (encore, ou plus) cette classe au moment où le client coche pour
            //// que le bouton reste verrouillé sur « Veuillez accepter les
            //// conditions générales » — case cochée, formulaire complet, et rien
            //// à faire. Re-sélectionner la tuile n'aidait pas: cela re-rend le
            //// formulaire et décoche la case.
            ////
            //// Mettre à jour le bouton DE LA TUILE où l'on coche est à la fois
            //// plus simple et sans risque: le formulaire d'une tuile non
            //// sélectionnée est masqué, son bouton n'est pas atteignable.
            $(document).on('change', '.payment-method-item .terms-acceptance', function() {
                const $container = $(this).closest('.payment-method-item');
                if (!$container.length) return;

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
            
            //// Neoffice — parcourt TOUTES les tuiles, pas seulement la
            //// sélectionnée (même raison que le gestionnaire ci-dessus: une tuile
            //// pas encore marquée `selected` gardait un bouton verrouillé pour
            //// toujours). Le formulaire d'une tuile non sélectionnée est masqué.
            this.updatePaymentButtonState = function() {
                $('.payment-method-item').each(function() {
                    const $item = $(this);
                    const $checkbox = $item.find('.terms-acceptance');
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

        //// Neoffice — formatting a number used to cost an HTTP round trip, one
        //// per amount, awaited in series. Refreshing the order summary of a
        //// six-item cart fired up to 17 of them (subtotal, shipping, one per
        //// tax line, one per item, one per unit price, one per discount,
        //// total) — measured at 25 ms each, so ~175 ms of pure waiting on the
        //// page load alone, and the same again after every quantity change.
        ////
        //// The client already has the answer. Frappe's own format_currency()
        //// was in fact already used a few lines below for the loyalty amount,
        //// without any network. Verified against the server on 0, 49, 271.97,
        //// 1234.5 and 1000000: byte-for-byte identical output, Swiss digit
        //// grouping included.
        ////
        //// The one thing the server knew and the browser did not is the
        //// "hide_currency_symbol_in_shop" setting; checkout.py now seeds it
        //// into the page. Kept async so the eight `await` call sites are
        //// untouched — awaiting a plain value simply resolves immediately.
        async format_currency_value(value, currency) {
            try {
                const hideSymbol = window.webshop_hide_currency_symbol === true;
                return format_currency(value, hideSymbol ? null : currency);
            } catch (err) {
                console.error('checkout: currency formatting failed', err);
                return String(value ?? '');
            }
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
                        //// Neoffice — same race as the billing side: this reply and
                        //// the address book are two independent calls.
                        this.syncAddressPickerSelection('shipping');
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

        //// Neoffice — address book.
        ////
        //// A Frappe customer routinely holds several addresses (home, office,
        //// a delivery address that is not the billing one). The checkout only
        //// ever rendered one flat form pre-filled with whichever address came
        //// back first, and the field holding its identity was hidden. Picking
        //// another one was impossible: you retyped over the form, which then
        //// OVERWROTE the address on file — the shopper's home address quietly
        //// became their office one.
        ////
        //// Selecting a card here means "use this address for this order". It
        //// does not edit anything: the form is filled, the reference values are
        //// re-baselined so the fields do not count as modified, and only the
        //// quotation is pointed at the address. Editing a field afterwards
        //// still updates that address, exactly as before.
        async loadAddressBook() {
            try {
                const r = await frappe.call({
                    method: 'webshop.webshop.shopping_cart.cart.get_customer_addresses'
                });
                this.addressBook = (r && r.message) || [];
            } catch (err) {
                //// A failure here must not block the checkout: the plain form
                //// below still works, the shopper simply types their address.
                console.error('checkout: address book unavailable', err);
                this.addressBook = [];
            }
            this.renderAddressPicker('billing');
            this.renderAddressPicker('shipping');
        }

        renderAddressPicker(target) {
            const $picker = $(`#${target}-address-picker`);
            if (!$picker.length) return;

            const book = this.addressBook || [];
            //// With no address on file there is nothing to choose between, and
            //// a lone "New address" card would only add noise to an empty form.
            if (!book.length) {
                $picker.attr('hidden', true);
                return;
            }

            const selected = $(`#${target}_address_name`).val();
            const cards = book.map(addr => {
                const lines = [addr.address_line1, [addr.pincode, addr.city].filter(Boolean).join(' ')]
                    .filter(Boolean).join('<br>');
                const tag = addr.is_primary_address ? __('Default')
                    : (addr.is_shipping_address ? __('Delivery') : (addr.address_type || ''));
                return `
                    <button type="button" class="address-card-choice ${addr.name === selected ? 'is-selected' : ''}"
                            data-address="${frappe.utils.escape_html(addr.name)}">
                        <span class="address-card-choice__title">
                            ${frappe.utils.escape_html(addr.title || addr.name)}
                            ${tag ? `<span class="address-card-choice__tag">${frappe.utils.escape_html(tag)}</span>` : ''}
                        </span>
                        <span class="address-card-choice__lines">${lines}</span>
                    </button>`;
            });

            cards.push(`
                <button type="button" class="address-card-choice address-card-choice--new"
                        data-address="">
                    + ${__('New address')}
                </button>`);

            $picker.find('.address-picker__list').html(cards.join(''));
            $picker.removeAttr('hidden');
            this.syncAddressPickerSelection(target);
        }

        //// Neoffice — the highlighted card is derived from the hidden field, never
        //// baked into the markup. The card list and the quotation arrive from two
        //// independent calls (get_customer_addresses and get_cart_quotation), so
        //// whichever lands last used to decide what the shopper saw: draw the cards
        //// before the quotation replied and "New address" was highlighted even
        //// though the form below was already filled with their default address.
        //// Both paths now call this, and it is idempotent, so the order stops
        //// mattering.
        syncAddressPickerSelection(target) {
            const $picker = $(`#${target}-address-picker`);
            if (!$picker.length) return;

            const selected = $(`#${target}_address_name`).val() || '';
            const $cards = $picker.find('.address-card-choice');
            $cards.removeClass('is-selected').attr('aria-pressed', 'false');

            //// An unknown name (address deleted elsewhere, or one the customer
            //// filter does not return) must not silently fall back to "New
            //// address": the form still holds that address, so highlighting the
            //// empty card would contradict what is on screen. Leave none selected.
            const $match = $cards.filter(`[data-address="${(selected || '').replace(/"/g, '\\"')}"]`);
            if (selected && !$match.length) return;
            $match.first().addClass('is-selected').attr('aria-pressed', 'true');
        }

        bindAddressPickers() {
            $(document).off('click.addressbook', '.address-card-choice');
            $(document).on('click.addressbook', '.address-card-choice', (e) => {
                const $btn = $(e.currentTarget);
                const target = $btn.closest('.address-picker').data('target');
                const name = $btn.data('address') || '';
                this.selectAddress(target, name);
            });
        }

        async selectAddress(target, name) {
            const prefix = `${target}_`;
            const addr = (this.addressBook || []).find(a => a.name === name);

            const champs = {
                [`${prefix}address_1`]: addr ? (addr.address_line1 || '') : '',
                [`${prefix}address_2`]: addr ? (addr.address_line2 || '') : '',
                [`${prefix}city`]: addr ? (addr.city || '') : '',
                [`${prefix}state`]: addr ? (addr.state || '') : '',
                [`${prefix}postcode`]: addr ? (addr.pincode || '') : '',
                [`${prefix}country`]: addr ? (addr.country || '') : '',
            };
            if (addr && addr.phone) champs[`${prefix}phone`] = addr.phone;
            if (addr && addr.email_id) champs[`${prefix}email`] = addr.email_id;

            //// Set the values WITHOUT firing change: this is not an edit, and
            //// letting it land in pendingChanges would make the next step call
            //// update_address_info, rewriting the chosen address (with
            //// is_primary_address = 1) instead of merely using it.
            Object.entries(champs).forEach(([field, value]) => {
                $(`[name="${field}"]`).val(value);
                if (this.initialFormValues) this.initialFormValues[field] = value;
                delete this.pendingChanges[field];
            });
            $(`#${target}_address_name`).val(name);
            this.syncAddressPickerSelection(target);

            if (!name) return;   // "New address": the form is cleared, nothing to tell the server yet

            //// Point the quotation at the address straight away, so the taxes
            //// on the right follow the country the shopper just picked.
            try {
                const r = await this.callServer(
                    'webshop.webshop.shopping_cart.cart.update_cart_address',
                    {address_type: target === 'billing' ? 'Billing' : 'Shipping', address_name: name},
                    {freeze: ['order-summary'],
                     errorMessage: __('This address could not be selected. Please try again.')}
                );
                if (r && r.taxes !== undefined) $('.tax-container').html(r.taxes);
                if (r && r.address !== undefined && target === 'billing') {
                    $('.billing-address-display').html(r.address);
                }
            } catch (err) {
                /* callServer has already told the shopper */
            }
        }

        setupAddressListeners() {
            //// Neoffice — this method used to re-register a `change` handler on
            //// every billing and shipping field, writing straight into
            //// pendingChanges with no comparison. bindEvents() already watches
            //// the same fields (selector '#address-form input, …') and DOES
            //// compare against the initial value.
            ////
            //// The two lived side by side: the `.off()` calls here never
            //// removed bindEvents' handler because jQuery only unbinds a
            //// delegated handler through its exact selector, and this one runs
            //// second (constructor order: setupListeners → bindEvents, then
            //// setupAddressListeners). So it always had the last word and put
            //// the field back into pendingChanges — undoing the comparison and
            //// keeping the "you have unsaved changes" dialog permanently armed.
            ////
            //// Only the "same address for shipping" behaviour was its own, and
            //// it stays: copying billing into shipping IS a real change, so
            //// writing it down directly is correct.
            const shippingFields = [
                'shipping_phone',
                'shipping_email',
                'shipping_address_1',
                'shipping_address_2',
                'shipping_city',
                'shipping_state',
                'shipping_postcode',
                'shipping_country'
            ];

            $(document).off('change', '#same_as_billing');
            $(document).on('change', '#same_as_billing', () => {
                if (!$('#same_as_billing').is(':checked')) return;
                shippingFields.forEach(field => {
                    const billingField = field.replace('shipping_', 'billing_');
                    const value = $(`[name="${billingField}"]`).val();
                    $(`[name="${field}"]`).val(value);
                    this.pendingChanges[field] = value;
                });
            });
        }

        async applyPendingChanges() {
            //// Neoffice — holds the answer of the last update_cart_address so
            //// the display can be refreshed from it instead of asking again.
            let addressResult = null;
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
                        addressResult = await frappe.call({
                            method: 'webshop.webshop.shopping_cart.cart.update_cart_address',
                            args: {
                                address_type: 'Shipping',
                                address_name: $('#shipping_address_name').val()
                            }
                        });
                    } else {
                        // If 'ship_to_different' is not checked, use billing address for shipping
                        addressResult = await frappe.call({
                            method: 'webshop.webshop.shopping_cart.cart.update_cart_address',
                            args: {
                                address_type: 'Shipping',
                                address_name: $('#billing_address_name').val()
                            }
                        });
                    }

                    //// Neoffice — the two calls above used to throw their
                    //// answer away, and a get_cart_quotation was fired right
                    //// after to fetch `taxes` and `address`.
                    ////
                    //// Two things were wrong with that. update_cart_address
                    //// ALREADY returns exactly {taxes, address} (see cart.py,
                    //// end of update_cart_address) — so the round trip was
                    //// buying something we had just been handed. And
                    //// get_cart_quotation does not even return those keys: its
                    //// payload is {doc, shipping_addresses, billing_addresses,
                    //// …}. The three lines below were writing `undefined` into
                    //// the DOM — inert, because jQuery's .html(undefined) acts
                    //// as a getter, which is why nobody ever noticed.
                    ////
                    //// `shipping_address` is returned by neither, so that line
                    //// is gone rather than kept as decoration.
                    const addressPayload = addressResult && addressResult.message;
                    if (addressPayload) {
                        if (addressPayload.taxes !== undefined) {
                            $('.tax-container').html(addressPayload.taxes);
                        }
                        if (addressPayload.address !== undefined) {
                            $('.billing-address-display').html(addressPayload.address);
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

        //// Neoffice — handleShippingAddressToggle() was declared twice in
        //// this class, with byte-identical bodies. JavaScript keeps the last
        //// declaration and silently drops the first, so these 18 lines never
        //// ran. Nothing was broken by it, but anyone fixing the first copy
        //// would have watched their change do nothing. The live one lives
        //// further down, next to the shipping code it belongs with.


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

        //// Neoffice — freezing used to auto-release after 3 seconds. That was
        //// a blindfolded safety net: a call slower than 3s left the screen
        //// usable while it was still running (the shopper could click again
        //// and fire concurrent writes), and a call that FAILED never released
        //// anything because unfreeze only lived in the success callback.
        ////
        //// Freezes are now counted per selector: two overlapping calls freeze
        //// once and release once the last one is done. Release is guaranteed
        //// by callServer()'s finally block, so it happens on failure too. The
        //// remaining timer is a last-resort net at 30s that TELLS the shopper
        //// instead of silently unlocking mid-flight.
        freezeElements(selectors) {
            this._freezeCounts = this._freezeCounts || {};
            this._freezeTimers = this._freezeTimers || {};
            selectors.forEach(selector => {
                const n = (this._freezeCounts[selector] || 0) + 1;
                this._freezeCounts[selector] = n;
                if (n === 1) this.freeze(selector);

                clearTimeout(this._freezeTimers[selector]);
                this._freezeTimers[selector] = setTimeout(() => {
                    if (this._freezeCounts[selector]) {
                        this._freezeCounts[selector] = 0;
                        this.unfreeze(selector);
                        frappe.msgprint({
                            title: __('Error'),
                            message: __('The server is taking too long to answer. Please check your connection and try again.'),
                            indicator: 'orange'
                        });
                    }
                }, 30000);
            });
        }

        unfreezeElements(selectors) {
            this._freezeCounts = this._freezeCounts || {};
            this._freezeTimers = this._freezeTimers || {};
            selectors.forEach(selector => {
                const n = Math.max(0, (this._freezeCounts[selector] || 0) - 1);
                this._freezeCounts[selector] = n;
                if (n === 0) {
                    clearTimeout(this._freezeTimers[selector]);
                    this.unfreeze(selector);
                }
            });
        }

        //// Neoffice — single door to the server. Guarantees three things the
        //// 47 hand-written frappe.call sites did not: the screen is always
        //// released (finally), a failure is shown to the shopper instead of
        //// dying in the console, and the caller gets a promise it can await
        //// rather than another nesting level.
        async callServer(method, args = {}, opts = {}) {
            const {freeze = [], errorMessage = null, silent = false} = opts;
            if (freeze.length) this.freezeElements(freeze);
            try {
                const r = await frappe.call({method, args});
                return r ? r.message : null;
            } catch (err) {
                console.error(`checkout: ${method} failed`, err);
                if (!silent) {
                    frappe.msgprint({
                        title: __('Error'),
                        message: errorMessage || __('Something went wrong. Please try again.'),
                        indicator: 'red'
                    });
                }
                throw err;
            } finally {
                if (freeze.length) this.unfreezeElements(freeze);
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
            //// Neoffice — re-entrancy lock.
            ////
            //// This method refreshes the shipping and payment lists, and those
            //// refreshes can lead back here. Closing the one known cycle (see
            //// the `notReload` guard further down) is not enough on its own:
            //// ten call sites reach this method, some through several hops,
            //// and any future one could reopen a path. A summary redraw that
            //// starts while another is still running has nothing to add — the
            //// one in flight is about to paint the same numbers.
            ////
            //// Without this, a cycle spins as fast as the CPU allows and the
            //// tab stops responding — which is exactly what happened once the
            //// currency round trips that used to slow every turn were removed.
            if (this._summaryRendering) return;
            this._summaryRendering = true;
            try {
                return await this._updateOrderSummaryInner(doc, notReload);
            } finally {
                this._summaryRendering = false;
            }
        }

        async _updateOrderSummaryInner(doc, notReload = false) {
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
                    //// Neoffice — multi-warehouse: matching on item_code
                    //// alone hit both lines of the same article, and the last
                    //// one processed overwrote the other's quantity — the
                    //// total updated while the fields kept the old numbers.
                    const whSel = item.warehouse ? `[data-warehouse="${item.warehouse}"]` : '';
                    let itemRow = $(`.order-item[data-item-code="${item.item_code}"]${whSel}`);
                    if (!itemRow.length) {
                        itemRow = $(`.order-item[data-item-code="${item.item_code}"]`).first();
                    }
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

            //// Neoffice — infinite loop, closed here.
            ////
            //// _updateOrderSummary asked for a shipping refresh, which
            //// re-rendered the list, which re-applied the checked method
            //// (loadShippingMethods → updateShippingMethod), which came back
            //// into _updateOrderSummary. The only brake was a comparison
            //// "re-render only if the HTML changed" that can never hold: one
            //// side is the browser's re-serialisation (`checked=""`), the
            //// other the raw template (`checked`), so they always differ.
            ////
            //// The loop was already there, but each turn paid for ~17 currency
            //// round trips at 25 ms, so it crawled — visible only as the
            //// flicker Jérémy had noticed. With formatting now local there is
            //// nothing left to slow it down and the tab freezes outright.
            ////
            //// `notReload` is exactly the "this refresh comes FROM a shipping
            //// update" signal, and was already threaded down here for the
            //// payment side. Honouring it for shipping too breaks the cycle at
            //// its only re-entry point.
            if (!this.isUpdatingShipping && !notReload) {
                this.refreshShippingMethods();
            }
            //// Neoffice — ne re-rendre les méthodes de paiement que si le
            //// MONTANT a changé.
            ////
            //// refreshPaymentMethods() reconstruit toute la liste. Quand cela
            //// tombait pendant que le client saisissait sa carte, sa tuile
            //// perdait la classe `selected` ; or le gestionnaire des conditions
            //// est lié à `.payment-method-item.selected #terms-acceptance`, si
            //// bien qu'il cessait de s'appliquer et que « Payer » n'était jamais
            //// réactivé — devant un formulaire pourtant complet. Le client
            //// clique, rien ne se passe, rien ne l'explique.
            ////
            //// Le seul motif légitime de reconstruire est un montant différent
            //// (l'étiquette « Payer CHF X » deviendrait fausse) — et dans ce cas
            //// il est normal de faire reconfirmer. Un rafraîchissement qui
            //// n'apprend rien ne doit plus détruire une saisie en cours.
            //// Le montant réellement débité vient de toute façon du serveur
            //// (rounded_total), jamais du navigateur.
            if (!this.isUpdatingPayment && $('.step-section.active').attr('id') === 'step-payment' && !notReload) {
                const montant = doc ? (doc.rounded_total || doc.grand_total || null) : null;
                if (montant === null || montant !== this._dernierMontantPaiement) {
                    this._dernierMontantPaiement = montant;
                    this.refreshPaymentMethods();
                }
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
                    //// Neoffice — 1, not true. frappe.call serialises the
                    //// boolean as the string "true", and the server reads this
                    //// flag with cint(), for which "true" is 0. The parameter
                    //// was therefore ignored on every call ever made here: the
                    //// response came back as a bare {name}, which is truthy —
                    //// so the code moved on happily and fetched the cart again
                    //// right after. That second call is what this one replaces.
                    with_items: 1,
                    //// Neoffice — multi-warehouse: keep the edit on the right line.
                    warehouse: warehouse !== undefined ? warehouse : undefined
                },
                //// Neoffice — update_cart now returns the quotation next to the
                //// rendered HTML, so the get_cart_quotation that used to follow
                //// is gone: this code was discarding three server-rendered
                //// templates and then asking for the document it had just
                //// caused to be built.
                ////
                //// The screen is released in every branch, failure included —
                //// previously an error left the summary frozen until the old
                //// 3-second auto-release kicked in.
                callback: (r) => {
                    try {
                        if (r.message) {
                            webshop.webshop.shopping_cart.set_cart_count(false);
                            if (r.message.doc) {
                                this.updateOrderSummaryFromDoc(r.message.doc);
                            }
                        }
                    } finally {
                        this.unfreezeElements(['order-summary']);
                    }
                },
                error: (err) => {
                    console.error('checkout: update_cart failed', err);
                    this.unfreezeElements(['order-summary']);
                    frappe.msgprint({
                        title: __('Error'),
                        message: __('The quantity could not be updated. Please try again.'),
                        indicator: 'red'
                    });
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
            //// Neoffice — the flag used to be raised at the very bottom of this
            //// method, synchronously, right after the request was SENT. During
            //// the whole round trip it was still false, so a second caller
            //// walked straight in and started its own empty()/fill cycle on the
            //// same container — two renders racing, and the step blinking.
            //// Raised before the call now, and lowered again if it fails.
            if (this.paymentMethodsInitialized || this._paymentMethodsLoading) {
                return;
            }
            this._paymentMethodsLoading = true;
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
                                            <input type="checkbox" class="form-check-input terms-acceptance" id="terms-acceptance" required>
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
                                //// Neoffice — the container was emptied and then
                                //// refilled one card at a time. Each append is a
                                //// separate layout pass, and between the empty()
                                //// and the last insert the payment step is visibly
                                //// blank: that is the flicker. Built as one string
                                //// and written once, the swap is a single frame.
                                const methodsHtml = [];
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
                                    methodsHtml.push(methodHtml);
                                });
                                container.html(methodsHtml.join(''));

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
                                        //// Neoffice — ne rien imposer si le client a déjà
                                        //// choisi. Ce callback arrive une à cinq secondes
                                        //// après l'affichage des cartes, et il rappelait
                                        //// handlePaymentMethodChange sans condition : un
                                        //// client qui cliquait plus vite que le réseau
                                        //// voyait son mode remplacé, sans un mot, par
                                        //// celui de la facture. Il payait alors avec un
                                        //// autre moyen que celui qu'il avait désigné.
                                        //// `currentMethod` est posé par
                                        //// handlePaymentMethodChange, donc sa présence
                                        //// signifie exactement « quelqu'un a déjà choisi ».
                                        if (this.currentMethod) {
                                            return;
                                        }
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

                            //// Neoffice — marked done only once the cards are
                            //// actually on screen, not when the request left.
                            this.paymentMethodsInitialized = true;
                            this._paymentMethodsLoading = false;
                            this.unfreeze('step-section');
                        },
                        error: (err) => {
                            console.error('checkout: payment methods failed', err);
                            this._paymentMethodsLoading = false;
                            this.unfreeze('step-section');
                            $('#payment-methods-container').html(
                                `<div class="alert alert-danger">${__('Payment methods could not be loaded. Please try again.')}</div>`
                            );
                        }
                    });
                },
                error: (err) => {
                    console.error('checkout: get_payment_methods failed', err);
                    this._paymentMethodsLoading = false;
                    this.unfreeze('step-section');
                    $('#payment-methods-container').html(
                        `<div class="alert alert-danger">${__('Payment methods could not be loaded. Please try again.')}</div>`
                    );
                }
            });
        }

        //// Neoffice — NE PAS SUPPRIMER : sans appel dans ce fichier, mais
        //// invoquée sur checkout_manager par templates/payments/paypal.html et
        //// wallee.html. Les gabarits de passerelle appellent des méthodes de
        //// cette classe : chercher un usage sans inclure templates/payments/
        //// fait conclure à tort qu'une méthode est morte.
        isValidEmail(email) {
            return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email || '');
        }

        handlePaymentMethodChange(methodId) {
            //// Neoffice — currentMethod was read when rendering the cards, to
            //// tick the method already chosen, but nothing ever assigned it:
            //// the pre-selection only worked when there was a single method.
            //// It matters on a re-render — without it the shopper's choice is
            //// lost and the list comes back unticked.
            this.currentMethod = methodId;
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
            //// Neoffice — les conditions générales, avant l'action.
            ////
            //// Une méthode passée aux intentions est dessinée ici et non par son
            //// gabarit — et le gabarit était le seul endroit qui portait la case
            //// à cocher. Résultat : sur ce chemin, le client payait sans avoir
            //// rien accepté, alors que c'est impossible sur toutes les autres
            //// tuiles. Cela valait pour TWINT depuis sa bascule, et pour toute
            //// tuile basculée ensuite.
            ////
            //// Le verrou est ici, comme partout ailleurs sur cette page : rien
            //// ne l'enregistre côté serveur, pour aucune passerelle. C'est une
            //// lacune connue et plus large que ce correctif ; celui-ci remet ce
            //// chemin au niveau des autres, il ne prétend pas la combler.
            const rendu = this.renderIntentAction(a, cleanId);
            if (!rendu) return false;
            $form.html(this.wrapWithTerms(rendu, cleanId)).show();
            this.bindIntentTerms($form);
            if (a.action === 'qr') this.watchIntent(a.intent, $form);
            return true;
        }

        //// Neoffice — enveloppe une action d'intention dans la même case à cocher
        //// que les gabarits : mêmes classes, même lien, pour que l'écran soit
        //// celui que le client connaît et que le style suive sans rien ajouter.
        wrapWithTerms(inner, cleanId) {
            const id = 'terms-intent-' + cleanId;
            //// Neoffice — le lien est HORS du libellé, comme dans les six
            //// gabarits de paiement. Un <a> à l'intérieur d'un <label> vole le
            //// clic : le navigateur suit le lien au lieu de cocher. Mesuré ici
            //// avant correction — le lien occupait 164 des 262 pixels du
            //// libellé et son centre tombait dessus, si bien que cliquer
            //// « J'accepte les conditions générales » ne cochait rien et
            //// l'action restait cachée. Chacun fait maintenant une seule
            //// chose : le libellé coche, le lien ouvre les conditions.
            return '<div class="form-check mb-3">' +
                '<input type="checkbox" class="form-check-input cursor-pointer terms-acceptance" id="' + id + '" required>' +
                '<label class="form-check-label cursor-pointer" for="' + id + '">' +
                __('I accept the') + '</label> ' +
                '<a href="#terms-title" class="terms-link">' +
                __('terms and conditions') + '</a></div>' +
                '<div class="intent-action" style="position:relative">' +
                '<div class="intent-voile" style="position:absolute; inset:0; z-index:2; ' +
                'background:rgba(255,255,255,.72); display:flex; align-items:center; ' +
                'justify-content:center; text-align:center; padding:1rem">' +
                '<span class="text-muted">' + __('Accept the terms and conditions to pay') + '</span>' +
                '</div>' + inner + '</div>';
        }

        //// Neoffice — l'action reste cachée tant que la case n'est pas cochée.
        //// Cachée plutôt que désactivée : un QR visible EST le moyen de payer,
        //// le griser ne l'empêcherait pas d'être scanné.
        //// Neoffice — l'action se voit, mais ne s'utilise pas tant que les
        //// conditions ne sont pas acceptées.
        ////
        //// Elle était simplement cachée : on cliquait une tuile et on ne voyait
        //// qu'une case, sans savoir ce qui allait apparaître. Les autres tuiles
        //// font l'inverse — le formulaire est là, seul le bouton est grisé — et
        //// c'est ce qu'un client comprend.
        ////
        //// Un cadre de paiement ne peut pas être seulement grisé : il resterait
        //// utilisable. On le laisse donc voilé et inerte sous un message, ce qui
        //// montre ce qui vient sans permettre de payer.
        bindIntentTerms($form) {
            const $case = $form.find('.terms-acceptance');
            const $action = $form.find('.intent-action');
            if (!$action.length) return;

            $action.show();
            const $voile = $action.find('.intent-voile');
            const suivre = () => {
                const accepte = $case.prop('checked');
                $action.toggleClass('intent-bloquee', !accepte);
                $action.find('a.btn, button.btn').toggleClass('disabled', !accepte)
                    .attr('aria-disabled', accepte ? null : 'true');
                $voile.toggle(!accepte);
            };
            //// Un clic sur l'action bloquée doit dire POURQUOI. Sans ça le client
            //// clique dans le vide et conclut que la boutique est cassée.
            $action.off('click.intent').on('click.intent', 'a.btn, button.btn, .intent-voile', (e) => {
                if (!$case.prop('checked')) {
                    e.preventDefault();
                    e.stopPropagation();
                    frappe.msgprint(__('Please accept the terms and conditions first.'));
                }
            });
            $case.off('change.intent').on('change.intent', suivre);
            suivre();
        }

        //// Neoffice — le contenu de l'action, sans les conditions.
        renderIntentAction(a, cleanId) {
            if (a.action === 'redirect' && a.url) {
                //// Neoffice — la saisie de carte reste sur la boutique.
                ////
                //// Un formulaire de carte n'a aucune raison d'exiger de quitter le
                //// site : le client perd le fil, revient sur une page de retour, et
                //// se demande si sa commande existe encore. La page hébergée de
                //// Payrexx s'encadre sans rien refuser (ni `X-Frame-Options` ni
                //// `frame-ancestors`, vérifié le 2026-08-31), et ses champs carte
                //// s'affichent depuis notre domaine.
                ////
                //// Réservé aux méthodes qui sont des formulaires. TWINT bascule vers
                //// le téléphone et ne peut pas le faire depuis un cadre — sa tuile
                //// garde donc le lien, et c'est le commerçant qui tranche, tuile par
                //// tuile, avec `render_inline`.
                if (a.inline) {
                    return '<div class="intent-frame py-2">' +
                        '<iframe src="' + frappe.utils.escape_html(a.url) + '" ' +
                        'style="width:100%; min-height:620px; border:0" ' +
                        'allow="payment" title="' + __('Payment') + '"></iframe>' +
                        '<p class="text-muted small mt-2 mb-0 text-center">' +
                        '<a href="' + frappe.utils.escape_html(a.url) + '" target="_blank" rel="noopener">' +
                        __('Open the payment page in a new tab') + '</a></p></div>';
                }
                return '<div class="text-center py-4"><a class="btn btn-primary" href="' +
                    frappe.utils.escape_html(a.url) + '">' + __('Continue to payment') + '</a></div>';
            }
            if (a.action === 'qr' && a.payload && a.payload.qr_svg) {
                const code = a.payload.pairing_token
                    ? '<p class="text-muted mt-2">' + __('Or type {0} in the app.', [a.payload.pairing_token]) + '</p>'
                    : '';
                const html = '<div class="text-center py-4"><div class="d-inline-block p-3 bg-white border rounded">' +
                    a.payload.qr_svg + '</div>' + code +
                    '<p class="text-muted mt-3 intent-attente">' + __('Waiting for your payment…') + '</p></div>';
                //// Neoffice — un QR ne redirige pas : sans surveillance, le client
                //// paie sur son téléphone et la page reste figée pour toujours.
                //// Le signal principal est l'évènement `payment.intent.<nom>.updated`
                //// que publie chaque pilote de `payments` — le même que son propre
                //// dialogue TWINT écoute — et le sondage n'est qu'un filet si la
                //// socket tombe. C'est la Payment Request qui tranche, pas
                //// l'intention : elle seule dit que la commande est passée.
                return html;
            }
            return null;
        }

        //// Neoffice — la surveillance d'une intention, jusqu'à la commande.
        watchIntent(intent, $form) {
            if (!intent) return;
            //// Changer de méthode de paiement rappelle watchIntent. L'ancienne
            //// surveillance doit mourir ici : sinon son setInterval continue de
            //// sonder le serveur toutes les 5 s, et — pire — son arreter() lisait
            //// this._intentTimer, qui pointe désormais sur le NOUVEAU timer : en
            //// expirant, l'ancienne surveillance tuait la nouvelle.
            this.stopIntentWatch();

            const canal = 'payment.intent.' + intent + '.updated';
            const DUREE_MAX = 5 * 60 * 1000;          // on abandonne au bout de 5 min
            const debut = Date.now();
            let fini = false;
            let timer = null;
            //// arreter() ne ferme que SUR SES PROPRES ressources (timer local,
            //// pas un champ d'instance partagé), donc deux surveillances qui se
            //// chevauchent ne peuvent plus s'annuler mutuellement.
            const arreter = () => {
                if (timer) { clearTimeout(timer); timer = null; }
                if (this._intentStop === arreter) this._intentStop = null;
                window.removeEventListener('pagehide', arreter);
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
            //// Le filet derrière le temps réel, espacé selon ce dont on dispose.
            ////
            //// frappe.realtime.on() connecte la socket, et c'est elle qui prévient
            //// dès que la passerelle a répondu — le sondage n'est là que pour le
            //// cas où elle tombe (ou n'existe pas: sur une page publique, rien ne
            //// garantit qu'un proxy laisse passer /socket.io). Sonder toutes les
            //// 5 s pendant 5 minutes coûtait 60 requêtes par paiement pour, la
            //// plupart du temps, ne rien apprendre que la socket n'ait déjà dit.
            ////
            //// setTimeout récursif plutôt que setInterval: l'intervalle peut
            //// alors varier, et deux tours ne peuvent pas se chevaucher si le
            //// serveur répond lentement.
            const prochainDelai = () => {
                const socketVivante = !!(frappe.realtime && frappe.realtime.socket
                    && frappe.realtime.socket.connected);
                const ecoule = Date.now() - debut;
                //// Les 30 premières secondes restent serrées: c'est là que le
                //// client attend devant son écran, et là que la socket peut
                //// n'être pas encore établie.
                if (ecoule < 30000) return 5000;
                return socketVivante ? 30000 : 10000;
            };
            const tour = () => {
                if (fini) return;
                if (Date.now() - debut >= DUREE_MAX) {
                    arreter();
                    $form.find('.intent-attente').text(__('Payment not received. You can try again.'));
                    return;
                }
                demander();
                timer = setTimeout(tour, prochainDelai());
            };
            timer = setTimeout(tour, prochainDelai());
            this._intentStop = arreter;
            demander();
            //// Retiré par arreter() : sans cela chaque changement de méthode
            //// laissait un écouteur de plus accroché à window.
            window.addEventListener('pagehide', arreter);
        }

        //// Neoffice — arrête la surveillance en cours, s'il y en a une.
        stopIntentWatch() {
            if (this._intentStop) this._intentStop();
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
                        //// Neoffice — `amount` was read from this.grandTotal,
                        //// a field never assigned anywhere in the class: the
                        //// gateway template received `undefined`. Harmless in
                        //// practice — get_payment_template falls back to the
                        //// quotation's rounded_total — but the fallback is
                        //// also the only trustworthy source: the amount to pay
                        //// must not be something the browser gets to state.
                        //// So we send nothing and let the server decide.
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
            //// Neoffice — isUpdatingPayment was raised and lowered around a
            //// call that is asynchronous: it was already false while the
            //// reload was still running, so the guard it exists for protected
            //// nothing. Worse, clearing paymentMethodsInitialized re-opened
            //// setupPaymentMethods to a caller that could arrive mid-flight.
            ////
            //// A reload asked for while one is already running is now simply
            //// dropped — the one in progress is about to render the same
            //// thing, and two of them racing is exactly what made the payment
            //// step blink.
            if (this._paymentMethodsLoading) return;
            this.isUpdatingPayment = true;
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

            //// Neoffice — was document.querySelector('.error.payment-message'),
            //// which takes the FIRST match in the document.
            ////
            //// Every payment method renders its own message zone, so the first
            //// one belongs to whichever method sits at the top of the list — not
            //// to the one the customer is paying with. A declined card therefore
            //// wrote its message inside a collapsed, unselected tile: the text
            //// was in the DOM, and the customer saw nothing at all.
            //// Verified with Stripe's declined test card: the whole chain ran
            //// (create_payment_request → make_payment → handle_payment_failure)
            //// and the screen stayed silent.
            const $selectionnee = $('.payment-method-item.selected');
            const messageEl = ($selectionnee.length
                ? $selectionnee.find('.' + type + '.payment-message')[0]
                : null) || document.querySelector('.' + type + '.payment-message');
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


        //// Neoffice — this was `async` but never awaited its own work: the
        //// frappe.call was fire-and-forget, so the promise resolved before
        //// isGiftCardOnly had been assigned. Callers doing
        //// `await this.checkGiftCardOnly()` read the value from the PREVIOUS
        //// run, which sent an all-gift-card cart to the shipping step instead
        //// of straight to payment.
        ////
        //// It also asked the server about one item at a time, in series. The
        //// whole cart is now one question — and the quotation it needs is
        //// passed in when the caller already has it, instead of being fetched
        //// again.
        async checkGiftCardOnly(quotation = null) {
            try {
                if (!quotation) {
                    const r = await frappe.call({
                        method: 'webshop.webshop.shopping_cart.cart.get_cart_quotation'
                    });
                    quotation = r && r.message ? r.message.doc : null;
                }
                const items = (quotation && quotation.items) || [];
                if (!items.length) {
                    this.isGiftCardOnly = false;
                    return false;
                }

                const codes = [...new Set(items.map(i => i.item_code))];
                const r2 = await frappe.call({
                    method: 'webshop.webshop.shopping_cart.cart.are_gift_card_items',
                    args: {item_codes: codes}
                });
                const map = (r2 && r2.message) || {};
                this.isGiftCardOnly = codes.every(c => map[c]);
            } catch (err) {
                console.error('checkout: gift card detection failed', err);
                //// Falling back to false keeps the shipping step in the flow —
                //// showing one step too many is recoverable, skipping the step
                //// that collects the delivery address is not.
                this.isGiftCardOnly = false;
            }
            return this.isGiftCardOnly;
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
                    const $termsCheckbox = $item.find('.terms-acceptance');
                    
                    if ($item.hasClass('selected') && $termsCheckbox.prop('checked')) {
                        $submitBtn.prop('disabled', false);
                    }
                });
            }
            
            // Clear the resetting flag
            this._isResetting = false;
        }

        // Check if payment is in progress

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