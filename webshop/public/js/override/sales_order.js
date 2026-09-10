//// Neoffice — added file (no upstream equivalent).
//
// Everything a bank-transfer order needs, on the order itself.
//
// The shop can ask to be paid before it ships. That conversation happens around
// ONE document — the order — so it is driven from there: raise the request, print
// the order (the QR bill is inside it, see the Oslo sales_order template), book
// the money when it lands. ERPNext scatters those across the order, the payment
// request and a payment entry, and the last of them cannot even be reached from
// the first.
frappe.ui.form.on("Sales Order", {
	//// The answer is fetched once and kept on the form, and the buttons are drawn
	//// SYNCHRONOUSLY on every refresh after that.
	////
	//// Drawing them straight from the server callback did not hold: `refresh` runs
	//// several times while a form settles, and each run rebuilds the action bar —
	//// so a button added by a callback that came back late was wiped by the next
	//// redraw. It showed on screen as a group that appeared, then vanished. The
	//// dashboard indicator this file used to add died the same way.
	onload(frm) {
		frm.__webshop_request = undefined;
	},

	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;
		//// Nothing to ask for on an order already invoiced in full.
		if (frm.doc.per_billed >= 100) return;

		if (frm.__webshop_request !== undefined) {
			draw(frm, frm.__webshop_request);
			return;
		}
		//// null while the answer travels, so a second refresh does not ask again.
		frm.__webshop_request = null;
		frappe.call({
			method: "webshop.webshop.shopping_cart.offline_payment.open_payment_request",
			args: { sales_order: frm.doc.name },
			callback: (r) => {
				frm.__webshop_request = (r && r.message) || null;
				draw(frm, frm.__webshop_request);
			},
		});
	},
});

//// Whatever we knew is stale once an action ran: forget it, then reload.
function refresh_after(frm) {
	frm.__webshop_request = undefined;
	frm.reload_doc();
}

function draw(frm, request) {
	const group = __("Payment request");

	if (!request) {
		frm.add_custom_button(__("Request payment"), () => ask(frm), group);
		return;
	}

	frm.add_custom_button(
		__("Open request {0}", [request.name]),
		() => frappe.set_route("Form", "Payment Request", request.name),
		group
	);

	if (request.status !== "Paid") {
		//// The amount is ON the button, not in a dashboard indicator: the form
		//// dashboard redraws after this callback and swallowed the indicator every
		//// time. It also belongs here — the figure matters where the decision is made.
		frm.add_custom_button(
			__("Payment received ({0})", [
				format_currency(request.outstanding_amount, frm.doc.currency),
			]),
			() => book(frm, request),
			group
		);
	}
}

function ask(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Request payment"),
		fields: [
			{
				fieldname: "hold",
				fieldtype: "Check",
				label: __("Hold the order until it is paid"),
				default: 1,
				description: __(
					"The order is put On Hold and the request says the goods are reserved. Uncheck for a deposit on an order that ships anyway."
				),
			},
			{
				fieldname: "mode_of_payment",
				fieldtype: "Link",
				label: __("Mode of Payment"),
				options: "Mode of Payment",
				//// Decides which bank account the QR bill points at, and where the
				//// payment entry lands.
				description: __("Decides the account on the QR bill."),
			},
		],
		primary_action_label: __("Create"),
		primary_action(values) {
			dialog.hide();
			frappe.call({
				method: "webshop.webshop.shopping_cart.offline_payment.request_payment_for_order",
				args: {
					sales_order: frm.doc.name,
					hold: values.hold ? 1 : 0,
					mode_of_payment: values.mode_of_payment || null,
				},
				freeze: true,
				freeze_message: __("Raising the request…"),
				callback: (r) => {
					if (!r.message) return;
					frappe.show_alert({ message: __("Payment request created"), indicator: "green" });
					refresh_after(frm);
				},
			});
		},
	});
	dialog.show();
}

function book(frm, request) {
	frappe.confirm(
		__("Book {0} as received, and raise the invoice?", [
			format_currency(request.outstanding_amount, frm.doc.currency),
		]),
		() => {
			frappe.call({
				method: "webshop.webshop.shopping_cart.offline_payment.settle",
				args: { payment_request: request.name },
				freeze: true,
				freeze_message: __("Booking the payment…"),
				callback: (r) => {
					if (!r.message) return;
					frappe.show_alert({ message: __("Payment booked"), indicator: "green" });
					refresh_after(frm);
				},
			});
		}
	);
}
