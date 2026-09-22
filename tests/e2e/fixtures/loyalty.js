//// //// Neoffice — added file (no upstream equivalent).
////
//// The loyalty ledger, read on the server, because the balance a customer sees
//// cannot prove a redemption on its own.
////
//// Buying EARNS points at the same moment redeeming SPENDS them: an order that
//// redeems 10 and earns 112 leaves the balance 102 higher than before. A test
//// asserting "the balance went down by what I spent" therefore fails on a shop
//// that works perfectly — measured on 2026-09-22, where it read the earning as
//// a missing deduction. What proves the redemption is the ledger: entries of
//// exactly minus what was applied, attached to the invoice of that order, and
//// still there afterwards.
const {onTheServer, activationAvailable} = require('./activation');

//// Resolve the Customer behind a sign-in address, the way the cart does.
const RESOLVE_CUSTOMER = `
email = %EMAIL%
customer = None
for contact in frappe.get_all("Contact Email", filters={"email_id": email}, pluck="parent"):
    for link in frappe.get_all("Dynamic Link", filters={"parent": contact, "link_doctype": "Customer"}, pluck="link_name"):
        customer = link
`;

//// The balance the LEDGER holds, which is not the one the block prints: the
//// checkout rounds down to the nearest ten (`get_loyalty_points_html` in
//// cart.py), so a customer holding 5817 points is offered 5810. Mixing the two
//// figures in one subtraction is how a perfectly working shop fails a test by
//// exactly seven points (measured 2026-09-22).
function ledgerBalance(email) {
	const output = onTheServer(
		RESOLVE_CUSTOMER.replace('%EMAIL%', JSON.stringify(email)) +
			`
from erpnext.accounts.doctype.loyalty_program.loyalty_program import get_loyalty_details
programme = frappe.db.get_value("Customer", customer, "loyalty_program") if customer else None
if not programme:
    print("")
else:
    print(int(get_loyalty_details(customer, programme, include_expired_entry=False).get("loyalty_points") or 0))
`
	);
	const value = output.trim().split('\n').pop();
	return value === '' ? null : Number(value);
}

/** The server's own clock, to bound a reading without trusting the runner's. */
function serverNow() {
	return onTheServer('print(frappe.utils.now())').trim().split('\n').pop();
}

//// What the loyalty ledger recorded for this customer since `since`.
//// { spent, earned, invoices, entries } — `spent` is negative or zero.
function ledgerSince(email, since) {
	const output = onTheServer(
		RESOLVE_CUSTOMER.replace('%EMAIL%', JSON.stringify(email)) +
			`
import json
rows = frappe.get_all(
    "Loyalty Point Entry",
    filters={"customer": customer, "creation": [">=", ${JSON.stringify(since)}]},
    fields=["loyalty_points", "invoice", "invoice_type"],
) if customer else []
report = {
    "spent": sum(r.loyalty_points for r in rows if r.loyalty_points < 0),
    "earned": sum(r.loyalty_points for r in rows if r.loyalty_points > 0),
    "invoices": sorted({r.invoice for r in rows if r.invoice}),
    "entries": len(rows),
}
print(json.dumps(report))
`
	);
	return JSON.parse(output.trim().split('\n').pop());
}

module.exports = {
	ledgerReadable: activationAvailable,
	ledgerBalance,
	serverNow,
	ledgerSince,
};
