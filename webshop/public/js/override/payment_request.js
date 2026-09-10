//// Neoffice — added file (no upstream equivalent).
//
// The button that books a shop payment made outside any gateway — a bank transfer
// against an order held for it.
//
// It exists because ERPNext's own "Set as Paid" FAILS on exactly these requests:
// the order is deliberately On Hold until the money is in, and the framework
// refuses to invoice a held order, so the native action raises "Sales Order … is
// On Hold" and books nothing. Ours lifts the hold first, then hands over to
// ERPNext's own code (see shopping_cart/offline_payment.py::settle).
frappe.ui.form.on("Payment Request", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1) return;
		if (frm.doc.status === "Paid") return;
		if (frm.doc.reference_doctype !== "Sales Order") return;
		//// Only for the requests the shop raised itself: an Outward request, or one
		//// carrying a gateway, is settled by the gateway and not by hand here.
		if (frm.doc.payment_request_type !== "Inward" || frm.doc.payment_gateway) return;

		frm.add_custom_button(__("Payment received"), () => {
			frappe.confirm(
				__("Book this payment and raise the invoice?"),
				() => {
					frappe.call({
						method: "webshop.webshop.shopping_cart.offline_payment.settle",
						args: { payment_request: frm.doc.name },
						freeze: true,
						freeze_message: __("Booking the payment…"),
						callback: (r) => {
							if (!r.message) return;
							frappe.show_alert({
								message: __("Payment booked"),
								indicator: "green",
							});
							frm.reload_doc();
						},
					});
				}
			);
		}).addClass("btn-primary");
	},
});
