// Address Management Page JavaScript

let addressDialog = null;
let currentAddressName = null;

frappe.ready(function() {
	// Dialog will be created on demand
});

function getCountryOptions() {
	let countrySelect = document.getElementById('country-options');
	if (countrySelect) {
		return countrySelect.innerHTML;
	}
	return '';
}

function showAddressForm() {
	currentAddressName = null;
	createAddressDialog(__('Add New Address'));
	addressDialog.show();
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
				createAddressDialog(__('Edit Address'), r.message);
				addressDialog.show();
			}
		}
	});
}

function createAddressDialog(title, data) {
	data = data || {};

	addressDialog = new frappe.ui.Dialog({
		title: title,
		size: 'large',
		fields: [
			{
				fieldname: 'address_title',
				label: __('Address Title'),
				fieldtype: 'Data',
				reqd: 1,
				default: data.address_title || '',
				placeholder: __('e.g., Home, Office')
			},
			{
				fieldtype: 'Section Break'
			},
			{
				fieldname: 'address_line1',
				label: __('Address Line 1'),
				fieldtype: 'Data',
				reqd: 1,
				default: data.address_line1 || ''
			},
			{
				fieldname: 'address_line2',
				label: __('Address Line 2'),
				fieldtype: 'Data',
				default: data.address_line2 || '',
				placeholder: __('Apartment, suite, etc. (optional)')
			},
			{
				fieldtype: 'Column Break'
			},
			{
				fieldname: 'pincode',
				label: __('Postal Code'),
				fieldtype: 'Data',
				reqd: 1,
				default: data.pincode || ''
			},
			{
				fieldname: 'city',
				label: __('City'),
				fieldtype: 'Data',
				reqd: 1,
				default: data.city || ''
			},
			{
				fieldtype: 'Section Break'
			},
			{
				fieldname: 'state',
				label: __('State/Region'),
				fieldtype: 'Data',
				default: data.state || ''
			},
			{
				fieldname: 'country',
				label: __('Country'),
				fieldtype: 'Link',
				options: 'Country',
				reqd: 1,
				default: data.country || window.default_country || 'Switzerland'
			},
			{
				fieldtype: 'Column Break'
			},
			{
				fieldname: 'phone',
				label: __('Phone'),
				fieldtype: 'Data',
				default: data.phone || ''
			},
			{
				fieldname: 'email_id',
				label: __('Email'),
				fieldtype: 'Data',
				default: data.email_id || ''
			},
			{
				fieldtype: 'Section Break'
			},
			{
				fieldname: 'is_primary_address',
				label: __('Set as primary address'),
				fieldtype: 'Check',
				default: data.is_primary_address || 0
			},
			{
				fieldname: 'is_shipping_address',
				label: __('Set as shipping address'),
				fieldtype: 'Check',
				default: data.is_shipping_address || 0
			}
		],
		primary_action_label: __('Save'),
		primary_action: function() {
			saveAddress();
		}
	});
}

function deleteAddress(addressName) {
	frappe.confirm(
		__('Are you sure you want to delete this address?'),
		function() {
			// Yes
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
	);
}

function saveAddress() {
	let values = addressDialog.get_values();
	if (!values) return;

	let addressData = {
		address_title: values.address_title,
		address_line1: values.address_line1,
		address_line2: values.address_line2,
		city: values.city,
		state: values.state,
		country: values.country,
		pincode: values.pincode,
		phone: values.phone,
		email_id: values.email_id,
		is_primary_address: values.is_primary_address ? 1 : 0,
		is_shipping_address: values.is_shipping_address ? 1 : 0
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
					addressDialog.hide();
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
					addressDialog.hide();
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
