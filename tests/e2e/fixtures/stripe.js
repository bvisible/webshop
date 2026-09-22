//// Neoffice — added file (no upstream equivalent).
//// Driving the Stripe payment form.
////
//// The card numbers below are Stripe's PUBLIC test numbers, documented at
//// https://docs.stripe.com/testing. They are not anyone's card: they only work
//// against a test key (the site runs pk_test_…), move no money, and reach no
//// real bank. Never put a real card number in this file.

const {expect} = require('@playwright/test');

const CARDS = {
	//// Payment accepted immediately, without 3-D Secure.
	accepted: '4242424242424242',
	//// Generic issuer decline — the customer must see a message, not a frozen screen.
	declined: '4000000000000002',
	//// Insufficient funds.
	insufficientFunds: '4000000000009995',
};

/** The payment method tile whose title mentions Stripe. */
function stripeTile(page) {
	return page.locator('.payment-method-item').filter({hasText: /stripe/i}).first();
}

//// Select Stripe and fill the card form.
////
//// The card fields live in an iframe served by Stripe: they are deliberately
//// unreachable from the page's own JavaScript (that is the point of Elements),
//// so they are driven through frameLocator.
async function fillCard(page, number, {name = 'Test E2E', email = 'test.e2e@example.com'} = {}) {
	const tile = stripeTile(page);
	await expect(tile, 'no Stripe method offered').toHaveCount(1);
	await tile.click();

	//// The form is mounted only after selection, and Stripe.js loads from its
	//// CDN: wait for the field, not a fixed delay.
	const holder = tile.locator('#cardholder-name');
	await expect(holder).toBeVisible({timeout: 30_000});
	await holder.fill(name);
	await tile.locator('#cardholder-email').fill(email);

	const frame = tile.frameLocator('[name="card-element"] iframe').first();
	await frame.locator('input[name="cardnumber"]').fill(number);
	await frame.locator('input[name="exp-date"]').fill(futureDate());
	await frame.locator('input[name="cvc"]').fill('123');
	//// Some configurations also require the postal code.
	const postcode = frame.locator('input[name="postal"]');
	if (await postcode.count()) await postcode.fill('1003');

	await acceptTerms(tile);
	return tile;
}

//// Tick the terms box.
////
//// This used to click the LABEL, because the handler in checkout.js listened
//// for "change click" on both the box and the label and flipped the box by
//// hand: check() ticked it, the handler fired and unticked it, and "Pay"
//// stayed disabled. That double-flip made the box genuinely unreliable — for a
//// customer too, not just for a test — and has been fixed in checkout.js, so
//// the box is now a plain checkbox and check() is enough.
////
//// Scoped to the Stripe tile, and matched by CLASS. The id used to be
//// `terms-acceptance` on every method at once — five elements sharing one id,
//// so each `<label for>` bound to the first box in the document and clicking
//// one method's label ticked another's. The id is now keyed on the method
//// (`terms-submit_wallee`); `.terms-acceptance` is what every tile has in
//// common.
async function acceptTerms(tile) {
	const boxes = tile.locator('.terms-acceptance');
	if ((await boxes.count()) === 0) return;

	const box = boxes.first();
	if (!(await box.isChecked())) await box.check();
	await expect(box, 'the terms could not be accepted').toBeChecked();
}

//// Submit the Stripe form.
////
//// Re-asserts the tile is still selected first. The payment step reloads its
//// method list while the customer is filling the card in, and the tile can lose
//// its `selected` class — at which point the terms handler, which is bound to
//// `.payment-method-item.selected .terms-acceptance`, stops applying and the
//// Pay button is never enabled, with the form still sitting there fully filled.
//// Seen in test as a disabled button on a completed form; a customer would see
//// exactly the same thing.
async function submitPayment(page, tile) {
	const button = tile.locator('.btn-submit-payment:visible').first();

	//// Up to three attempts: the refresh can kick in again mid re-selection.
	//// A real customer would also click again.
	for (let attempt = 1; attempt <= 3; attempt += 1) {
		if (await button.isEnabled().catch(() => false)) break;
		if (!(await tile.evaluate((e) => e.classList.contains('selected')))) {
			await tile.click();
			await page.waitForTimeout(2000);
		}
		await acceptTerms(tile);
		await page.waitForTimeout(1500);
	}

	await expect(
		button,
		'the "Pay" button stayed locked: the tile lost its selection while the card ' +
			'was being typed (the payment methods refreshed)'
	).toBeEnabled({timeout: 30_000});
	await button.click();
}

/** MM/YY two years out — a card must not expire mid-suite. */
function futureDate() {
	const now = new Date();
	const year = String((now.getFullYear() + 2) % 100).padStart(2, '0');
	return `12${year}`;
}

module.exports = {
	CARDS,
	stripeTile,
	fillCard,
	acceptTerms,
	submitPayment,
	futureDate,
};
