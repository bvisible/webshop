// Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ready(() => {
	var loyalty_points_input = document.getElementById("loyalty-point-to-redeem");
	var loyalty_points_status = document.getElementById("loyalty-points-status");

	if (loyalty_points_input) {
		loyalty_points_input.onblur = apply_loyalty_points;
	}

	function apply_loyalty_points() {
		var loyalty_points = parseInt(loyalty_points_input.value);

		if (!loyalty_points) return;

		const callback = async (r) => {
			if (!r) return;

			var message = ""
			let loyalty_amount = flt(r.message * loyalty_points);

			if (doc_info.grand_total && doc_info.grand_total < loyalty_amount) {
				let redeemable_amount = parseInt(doc_info.grand_total/r.message);
				message = "You can only redeem max " + redeemable_amount + " points in this order.";
				frappe.msgprint(__(message));
				return;
			}

			message = loyalty_points + " Loyalty Points of amount "+ loyalty_amount + " is applied."
			loyalty_points_status.innerHTML = message;
			frappe.msgprint(__(message));

			const args_obj = {
				dn: doc_info.doctype_name,
				dt: doc_info.doctype,
				submit_doc: 1,
				order_type: "Shopping Cart",
				loyalty_points,
			}

			//// Neoffice — from the server, in the page: a portal account has no right on Webshop Settings any more
			//// (webshop_settings.json), where any account read the shop's whole configuration.
			{%- set gateway_account = frappe.db.get_single_value('Webshop Settings', 'payment_gateway_account') %}
			const payment_gateway_account = {{ gateway_account | tojson }};

			if (payment_gateway_account) {
				args_obj.payment_gateway_account = payment_gateway_account;
			}

			// //// Neoffice — the Pay button is a POST form since #2222 (order.html): the redeemed points and the
			// //// gateway account travel as hidden fields of that form, no longer in the query string of a link.
			const form = document.getElementById("pay-for-order-form");
			for (const [name, value] of Object.entries(args_obj)) {
				let input = form.querySelector(`input[name="${name}"]`);
				if (!input) {
					input = document.createElement("input");
					input.type = "hidden";
					input.name = name;
					form.appendChild(input);
				}
				input.value = value;
			}

			var payment_button = document.getElementById("pay-for-order");
			payment_button.innerHTML = __("Pay Remaining");
			// //// Neoffice — no href to set any more: the Pay button submits its form (#2222).
		}

		frappe.call({
			// //// Neoffice — the shop's own get_redemption_factor (order.py), not erpnext's get_redeemption_factor:
			// //// upstream opens that one to a desk right only (v15.123.0); the order names the customer, not the browser
			method: "webshop.templates.pages.order.get_redemption_factor",
			args: {
				dt: doc_info.doctype,
				dn: doc_info.doctype_name,
			},
			callback,
		});
	}
})
