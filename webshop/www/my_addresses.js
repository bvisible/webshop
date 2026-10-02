//// Neoffice — added file (no upstream equivalent). Behaviour of the address book:
//// create, edit and delete over our own endpoints in webshop/webshop/api.py, which
//// re-check that the address belongs to the caller's party (a807dc8a10 /
//// 49e4068f7f, 2026-01-03; street + house number 5fd5bda299, 2026-07-17).
// Address Management Page JavaScript

let currentAddressName = null;

//// Neoffice — the page's words, translated by the server (my_addresses.py): __() has no catalogue
//// on this page, so « Add New Address » and the alerts stayed in English (maintenance#1032).
function t(key, fallback) {
	const texts = window.myAddressesText || {};
	return texts[key] || __(fallback);
}

//// Neoffice — the fields a site may lack (fleet custom fields of the Address): read and written only
//// when the form shows them.
const OPTIONAL_FIELDS = ["company", "to_the_attention_of", "custom_house_number", "neo_delivery_instructions"];

function fieldValue(id) {
	const $el = $('#' + id);
	return $el.length ? ($el.val() || '').trim() : undefined;
}

frappe.ready(function() {
	// Nothing to initialize on load
});

function showAddressForm() {
	currentAddressName = null;
	$('#address-form-title').text(t('add', 'Add New Address'));
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
	OPTIONAL_FIELDS.forEach(function (f) { $('#' + f).val(''); });
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
		method: 'webshop.webshop.api.get_address',
		args: { address_name: addressName },
		freeze: true,
		freeze_message: t('loading', 'Loading...'),
		callback: function(r) {
			if (r.message) {
				currentAddressName = addressName;
				$('#address-form-title').text(t('edit', 'Edit Address'));

				// Fill form with data
				$('#address_title').val(r.message.address_title || '');
				$('#address_line1').val(r.message.address_line1 || '');
				OPTIONAL_FIELDS.forEach(function (f) { $('#' + f).val(r.message[f] || ''); });
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
	if (confirm(t('confirm_delete', 'Are you sure you want to delete this address?'))) {
		frappe.call({
			method: 'webshop.webshop.api.delete_address',
			args: { address_name: addressName },
			freeze: true,
			freeze_message: t('deleting', 'Deleting...'),
			callback: function(r) {
				if (r.message && r.message.success) {
					frappe.show_alert({
						message: t('deleted', 'Address deleted successfully'),
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
		frappe.show_alert({ message: t('need_title', 'Address Title is required'), indicator: 'red' });
		$('#address_title').focus();
		return;
	}
	if (!address_line1) {
		frappe.show_alert({ message: t('need_street', 'Address Line 1 is required'), indicator: 'red' });
		$('#address_line1').focus();
		return;
	}
	if (!pincode) {
		frappe.show_alert({ message: t('need_pincode', 'Postal Code is required'), indicator: 'red' });
		$('#pincode').focus();
		return;
	}
	if (!city) {
		frappe.show_alert({ message: t('need_city', 'City is required'), indicator: 'red' });
		$('#city').focus();
		return;
	}
	if (!country) {
		frappe.show_alert({ message: t('need_country', 'Country is required'), indicator: 'red' });
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
	OPTIONAL_FIELDS.forEach(function (f) {
		const value = fieldValue(f);
		if (value !== undefined) addressData[f] = value;
	});

	if (currentAddressName) {
		// Update existing address
		frappe.call({
			method: 'webshop.webshop.api.update_address',
			args: {
				address_name: currentAddressName,
				address_data: addressData
			},
			freeze: true,
			freeze_message: t('saving', 'Saving...'),
			callback: function(r) {
				if (r.message && r.message.success) {
					hideAddressForm();
					frappe.show_alert({
						message: t('updated', 'Address updated successfully'),
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
			freeze_message: t('saving', 'Saving...'),
			callback: function(r) {
				if (r.message) {
					hideAddressForm();
					frappe.show_alert({
						message: t('created', 'Address created successfully'),
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
