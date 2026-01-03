// Address Management Page JavaScript

let currentAddressName = null;

frappe.ready(function() {
	// Nothing to initialize on load
});

function showAddressForm() {
	currentAddressName = null;
	$('#address-form-title').text(__('Add New Address'));
	clearAddressForm();
	$('#address-form-container').slideDown();
	$('html, body').animate({
		scrollTop: $('#address-form-container').offset().top - 100
	}, 300);
}

function hideAddressForm() {
	$('#address-form-container').slideUp();
	clearAddressForm();
	currentAddressName = null;
}

function clearAddressForm() {
	$('#address_title').val('');
	$('#address_line1').val('');
	$('#address_line2').val('');
	$('#pincode').val('');
	$('#city').val('');
	$('#state').val('');
	$('#country').val(window.default_country || 'Switzerland');
	$('#phone').val('');
	$('#email_id').val('');
	$('#is_primary_address').prop('checked', false);
	$('#is_shipping_address').prop('checked', false);
}

function editAddress(addressName) {
	frappe.call({
		method: 'webshop.webshop.www.my_addresses.get_address',
		args: { address_name: addressName },
		freeze: true,
		freeze_message: __('Loading...'),
		callback: function(r) {
			if (r.message) {
				currentAddressName = addressName;
				$('#address-form-title').text(__('Edit Address'));

				// Fill form with data
				$('#address_title').val(r.message.address_title || '');
				$('#address_line1').val(r.message.address_line1 || '');
				$('#address_line2').val(r.message.address_line2 || '');
				$('#pincode').val(r.message.pincode || '');
				$('#city').val(r.message.city || '');
				$('#state').val(r.message.state || '');
				$('#country').val(r.message.country || window.default_country || 'Switzerland');
				$('#phone').val(r.message.phone || '');
				$('#email_id').val(r.message.email_id || '');
				$('#is_primary_address').prop('checked', r.message.is_primary_address ? true : false);
				$('#is_shipping_address').prop('checked', r.message.is_shipping_address ? true : false);

				$('#address-form-container').slideDown();
				$('html, body').animate({
					scrollTop: $('#address-form-container').offset().top - 100
				}, 300);
			}
		}
	});
}

function deleteAddress(addressName) {
	if (confirm(__('Are you sure you want to delete this address?'))) {
		frappe.call({
			method: 'webshop.webshop.www.my_addresses.delete_address',
			args: { address_name: addressName },
			freeze: true,
			freeze_message: __('Deleting...'),
			callback: function(r) {
				if (r.message && r.message.success) {
					frappe.show_alert({
						message: __('Address deleted successfully'),
						indicator: 'green'
					});
					setTimeout(function() {
						window.location.reload();
					}, 500);
				}
			}
		});
	}
}

function saveAddress() {
	// Validate required fields
	let address_title = $('#address_title').val().trim();
	let address_line1 = $('#address_line1').val().trim();
	let pincode = $('#pincode').val().trim();
	let city = $('#city').val().trim();
	let country = $('#country').val();

	if (!address_title) {
		frappe.show_alert({ message: __('Address Title is required'), indicator: 'red' });
		$('#address_title').focus();
		return;
	}
	if (!address_line1) {
		frappe.show_alert({ message: __('Address Line 1 is required'), indicator: 'red' });
		$('#address_line1').focus();
		return;
	}
	if (!pincode) {
		frappe.show_alert({ message: __('Postal Code is required'), indicator: 'red' });
		$('#pincode').focus();
		return;
	}
	if (!city) {
		frappe.show_alert({ message: __('City is required'), indicator: 'red' });
		$('#city').focus();
		return;
	}
	if (!country) {
		frappe.show_alert({ message: __('Country is required'), indicator: 'red' });
		$('#country').focus();
		return;
	}

	let addressData = {
		address_title: address_title,
		address_line1: address_line1,
		address_line2: $('#address_line2').val().trim(),
		city: city,
		state: $('#state').val().trim(),
		country: country,
		pincode: pincode,
		phone: $('#phone').val().trim(),
		email_id: $('#email_id').val().trim(),
		is_primary_address: $('#is_primary_address').is(':checked') ? 1 : 0,
		is_shipping_address: $('#is_shipping_address').is(':checked') ? 1 : 0
	};

	if (currentAddressName) {
		// Update existing address
		frappe.call({
			method: 'webshop.webshop.www.my_addresses.update_address',
			args: {
				address_name: currentAddressName,
				address_data: addressData
			},
			freeze: true,
			freeze_message: __('Saving...'),
			callback: function(r) {
				if (r.message && r.message.success) {
					hideAddressForm();
					frappe.show_alert({
						message: __('Address updated successfully'),
						indicator: 'green'
					});
					setTimeout(function() {
						window.location.reload();
					}, 500);
				}
			}
		});
	} else {
		// Create new address
		frappe.call({
			method: 'webshop.webshop.shopping_cart.cart.add_new_address',
			args: {
				doc: addressData
			},
			freeze: true,
			freeze_message: __('Saving...'),
			callback: function(r) {
				if (r.message) {
					hideAddressForm();
					frappe.show_alert({
						message: __('Address created successfully'),
						indicator: 'green'
					});
					setTimeout(function() {
						window.location.reload();
					}, 500);
				}
			}
		});
	}
}
