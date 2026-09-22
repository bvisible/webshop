//// //// Neoffice — added file (no upstream equivalent).
////
//// Helpers shared by the specs that exercise the money paths: pick a payment
//// tile by the name the shop prints on it, place an order with a method that
//// calls no provider, and read the loyalty balance the customer is shown.
const {CARDS, stripeTile, fillCard, acceptTerms, submitPayment} = require('./stripe');
const {callMethod, readQuotation} = require('./shop');

//// The QUOTATION is the steady reading, never the button that proves it.
////
//// Applying points or a coupon re-renders the whole of step 4 (the payment tiles
//// refresh with the new total), so the button that says "applied" is destroyed
//// and rebuilt under the test — and it comes back BEFORE the quotation is saved:
//// one run read the pre-discount total through a button that was already there.
//// This polls the shop's own document, which is what the order and the invoice
//// will carry. Answers the quotation once the condition holds, null on timeout,
//// so a caller can press again instead of failing on a click the re-render ate.
async function waitForQuotation(page, condition, timeout = 25_000) {
	const deadline = Date.now() + timeout;
	for (;;) {
		const answer = await readQuotation(page);
		const doc = (answer && (answer.doc || answer)) || {};
		if (condition(doc)) return doc;
		if (Date.now() >= deadline) return null;
		await page.waitForTimeout(1_000);
	}
}

//// A click whose own block re-renders can be swallowed by that re-render: press
//// again rather than fail on an attempt the page never received.
async function pressUntil(page, action, condition, attempts = 3) {
	for (let attempt = 1; attempt <= attempts; attempt++) {
		await action();
		const doc = await waitForQuotation(page, condition);
		if (doc) return doc;
	}
	return null;
}

//// A payment tile, by the name printed on it.
function paymentTile(page, pattern) {
	return page.locator('.payment-method-item').filter({hasText: pattern}).first();
}

//// The tiles that settle without a provider: they place the order and stop.
//// "On account" ships and invoices on terms, "transfer before shipping" holds
//// the order until the money arrives. Either one places a real order without
//// touching a gateway, which is what a test needs. The pattern matches the
//// French labels too: the shop prints what the merchant typed, in their language.
const WITHOUT_GATEWAY = /on account|sur compte|compte client|virement|transfer|bank/i;

//// Place the order with the first method that calls no provider.
//// Returns the tile's name, or null when this shop offers none.
async function orderWithoutGateway(page) {
	const tile = paymentTile(page, WITHOUT_GATEWAY);
	if ((await tile.count()) === 0) return null;

	const name = (await tile.locator('.payment-method-title').first().innerText()).trim();
	await tile.click();
	await page.waitForTimeout(1500);
	await acceptTerms(tile);
	await submitPayment(page, tile);
	return name;
}

//// Place the order, by whatever this shop actually offers.
////
//// A method that calls no provider is preferred: it is the shortest path and no
//// money moves at all. But a shop whose tiles are ALL gateways — osiris, measured
//// 2026-09-22 — would then skip the only test that proves loyalty points are
//// really consumed, and a skip reads exactly like a pass. Stripe's test card is
//// the fallback: a real order against a `pk_test_` key, which is the path a real
//// customer takes anyway.
//// Answers what it used, or null when the shop offers no way to conclude at all.
async function settleTheOrder(page) {
	const offline = await orderWithoutGateway(page);
	if (offline) return {through: 'no gateway', method: offline};

	if ((await stripeTile(page).count()) === 0) return null;
	//// Applying points re-renders the tiles with the new total, which can undo the
	//// selection made a moment earlier: the card form then never mounts and the
	//// failure reads as "Stripe is broken". Fill it again rather than believe that.
	for (let attempt = 1; attempt <= 2; attempt++) {
		try {
			const tile = await fillCard(page, CARDS.accepted);
			await submitPayment(page, tile);
			return {through: 'test card', method: 'Stripe'};
		} catch (error) {
			if (attempt === 2) throw error;
			await page.waitForTimeout(3_000);
		}
	}
}

//// What became of a quotation: 'ordered' when it was consumed by an order,
//// 'draft' when it is still a cart, 'empty' / 'unreadable' otherwise.
////
//// This is the proof an order exists, and the URL is not: on a loaded server the
//// redirect that leaves /checkout can take longer than the order itself, so a
//// test watching the address bar calls a successful purchase a failure.
//// After an order, get_cart_quotation opens a NEW empty cart: that the original
//// quotation is no longer the current one is already the proof it was consumed.
async function quotationState(page, name) {
	//// Through readQuotation, which never throws: a request that times out under
	//// load must let the poll try again, not abort the test on its first slow
	//// second.
	const answer = await readQuotation(page);
	if (!answer) return 'unreadable';
	//// An emptied cart comes back with NO `doc` at all. Falling back to the
	//// envelope then finds no name, and the reading answers 'empty' for ever
	//// while the order sits on the server — measured 2026-09-22, a paid Payment
	//// Request and its order next to a test that called the purchase a failure.
	if (!answer.doc) return 'empty';
	const doc = answer.doc;
	if (doc.name && doc.name !== name) return 'ordered';
	return (doc.items || []).length ? 'draft' : 'empty';
}

//// The loyalty balance as the checkout shows it.
////
//// Read off the shop's own block rather than a doctype: a portal customer may
//// not query Loyalty Point Entry, and this is the figure the buyer sees. The
//// endpoint answers whatever step the tunnel is on, which the block itself does
//// not: it lives inside step 4 and is hidden before that. null when the shop
//// runs no loyalty programme, so a spec can say so instead of inventing a zero.
async function loyaltyBalanceShown(page) {
	const html = await callMethod(page, 'webshop.webshop.shopping_cart.cart.get_loyalty_points_html');
	if (!html || !/loyalty-point-to-redeem/.test(html)) return null;
	//// Points already applied: the input carries them, and the balance left is
	//// the one printed under it.
	if (/bt-remove-loyalty/.test(html)) {
		const left = html.match(/(\d+)\s*(?:<span|<\/p>)/);
		return left ? Number(left[1]) : null;
	}
	const value = html.match(/id="loyalty-point-to-redeem"[\s\S]{0,200}?value="(\d*)"/);
	if (value) return value[1] === '' ? 0 : Number(value[1]);
	return null;
}

module.exports = {
	paymentTile,
	orderWithoutGateway,
	settleTheOrder,
	quotationState,
	loyaltyBalanceShown,
	waitForQuotation,
	pressUntil,
	WITHOUT_GATEWAY,
};
