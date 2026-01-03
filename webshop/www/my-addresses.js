// Address Management Page JavaScript

let addressModal = null;
let deleteModal = null;
let addressToDelete = null;

frappe.ready(function() {
	// Initialize Bootstrap modals
	addressModal = new bootstrap.Modal(document.getElementById('addressModal'));
	deleteModal = new bootstrap.Modal(document.getElementById('deleteModal'));

	// Handle delete confirmation
	document.getElementById('confirm-delete-btn').addEventListener('click', function() {
		if (addressToDelete) {
			confirmDelete(addressToDelete);
		}
	});
});

function showAddressForm() {
	// Reset form for new address
	document.getElementById('address-form').reset();
	document.getElementById('address_name').value = '';
	document.getElementById('addressModalLabel').textContent = __('Add New Address');
	addressModal.show();
}

function editAddress(addressName) {
	// Fetch address data and populate form
	frappe.call({
		method: 'webshop.webshop.templates.pages.addresses.get_address',
		args: { address_name: addressName },
		freeze: true,
		freeze_message: __('Loading...'),
		callback: function(r) {
			if (r.message) {
				let addr = r.message;
				document.getElementById('address_name').value = addr.name;
				document.getElementById('address_title').value = addr.address_title || '';
				document.getElementById('address_line1').value = addr.address_line1 || '';
				document.getElementById('address_line2').value = addr.address_line2 || '';
				document.getElementById('city').value = addr.city || '';
				document.getElementById('state').value = addr.state || '';
				document.getElementById('country').value = addr.country || '';
				document.getElementById('pincode').value = addr.pincode || '';
				document.getElementById('phone').value = addr.phone || '';
				document.getElementById('email_id').value = addr.email_id || '';
				document.getElementById('is_primary_address').checked = addr.is_primary_address;
				document.getElementById('is_shipping_address').checked = addr.is_shipping_address;

				document.getElementById('addressModalLabel').textContent = __('Edit Address');
				addressModal.show();
			}
		}
	});
}

function deleteAddress(addressName) {
	addressToDelete = addressName;
	deleteModal.show();
}

function confirmDelete(addressName) {
	frappe.call({
		method: 'webshop.webshop.templates.pages.addresses.delete_address',
		args: { address_name: addressName },
		freeze: true,
		freeze_message: __('Deleting...'),
		callback: function(r) {
			if (r.message && r.message.success) {
				// Remove card from UI
				let card = document.getElementById('address-card-' + addressName);
				if (card) {
					card.remove();
				}

				// Check if no more addresses
				let addressList = document.getElementById('addresses-list');
				if (addressList && addressList.children.length === 0) {
					addressList.innerHTML = `
						<div class="col-12">
							<div class="alert alert-info">
								${__("You don't have any saved addresses yet.")}
							</div>
						</div>
					`;
				}

				deleteModal.hide();
				frappe.msgprint({
					message: __('Address deleted successfully'),
					indicator: 'green'
				});
			}
		}
	});
	addressToDelete = null;
}

function saveAddress() {
	let form = document.getElementById('address-form');

	// Validate required fields
	if (!form.checkValidity()) {
		form.reportValidity();
		return;
	}

	let addressName = document.getElementById('address_name').value;
	let addressData = {
		address_title: document.getElementById('address_title').value,
		address_line1: document.getElementById('address_line1').value,
		address_line2: document.getElementById('address_line2').value,
		city: document.getElementById('city').value,
		state: document.getElementById('state').value,
		country: document.getElementById('country').value,
		pincode: document.getElementById('pincode').value,
		phone: document.getElementById('phone').value,
		email_id: document.getElementById('email_id').value,
		is_primary_address: document.getElementById('is_primary_address').checked ? 1 : 0,
		is_shipping_address: document.getElementById('is_shipping_address').checked ? 1 : 0
	};

	if (addressName) {
		// Update existing address
		frappe.call({
			method: 'webshop.webshop.templates.pages.addresses.update_address',
			args: {
				address_name: addressName,
				address_data: addressData
			},
			freeze: true,
			freeze_message: __('Saving...'),
			callback: function(r) {
				if (r.message && r.message.success) {
					addressModal.hide();
					frappe.msgprint({
						message: __('Address updated successfully'),
						indicator: 'green'
					});
					// Reload page to show updated data
					setTimeout(function() {
						window.location.reload();
					}, 1000);
				}
			}
		});
	} else {
		// Create new address
		frappe.call({
			method: 'webshop.webshop.shopping_cart.cart.add_new_address',
			args: {
				doc: {
					address_title: addressData.address_title,
					address_line1: addressData.address_line1,
					address_line2: addressData.address_line2,
					city: addressData.city,
					state: addressData.state,
					country: addressData.country,
					pincode: addressData.pincode,
					phone: addressData.phone,
					email_id: addressData.email_id,
					is_primary_address: addressData.is_primary_address,
					is_shipping_address: addressData.is_shipping_address
				}
			},
			freeze: true,
			freeze_message: __('Saving...'),
			callback: function(r) {
				if (r.message) {
					addressModal.hide();
					frappe.msgprint({
						message: __('Address created successfully'),
						indicator: 'green'
					});
					// Reload page to show new address
					setTimeout(function() {
						window.location.reload();
					}, 1000);
				}
			}
		});
	}
}
