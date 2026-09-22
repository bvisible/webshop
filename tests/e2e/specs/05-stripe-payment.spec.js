//// Neoffice — added file (no upstream equivalent).
//// The checkout, all the way to a real Stripe charge.
////
//// The other specs stop at the payment step. These go through it, against
//// Stripe's TEST key (pk_test_…) with Stripe's public test card numbers: no
//// money moves and no real bank is reached, but everything else is real —
//// a Payment Request is created, the charge is made, and an order comes out.
////
//// They therefore leave real documents on the target site. See README.md
//// ("What these tests leave behind") for how to clean up.

const {test, expect} = require('@playwright/test');
const {
	signIn,
	emptyCart,
	addToCart,
	readQuotation,
	goToPaymentStep,
	firstBuyableItem,
} = require('../fixtures/shop');
const {CARDS, fillCard, submitPayment} = require('../fixtures/stripe');
//// One copy of "what became of this quotation", in fixtures/payment.js: the
//// loyalty and gift-card specs read the same answer, and a second copy here
//// would be the one nobody updates.
const {quotationState} = require('../fixtures/payment');

//// A payment goes through Stripe then two server calls: generous, but bounded.
const PAYMENT_TIMEOUT = 90_000;

//// Record what the payment actually did, so a failure says WHY.
////
//// A payment crosses three parties (Stripe's tokenisation, create_payment_request,
//// make_payment); when it stalls, "the quotation stayed a draft" names the
//// symptom and nothing else. This attaches the exchange to the report.
function watchPayment(page) {
	const exchanges = [];
	page.on('response', async (r) => {
		if (!/api\.stripe\.com|make_payment|create_payment_request|handle_payment_failure/.test(r.url())) {
			return;
		}
		let body = '';
		try {
			body = (await r.text()).slice(0, 300).replace(/\s+/g, ' ');
		} catch (error) {
			body = '(body unreadable)';
		}
		exchanges.push(`${r.status()} ${r.url().split('?')[0].slice(-45)} → ${body}`);
	});
	page.on('pageerror', (e) => exchanges.push(`JS ERROR: ${String(e).slice(0, 200)}`));
	//// The Stripe form sometimes refuses the click and only says so in the
	//// console ("Payment already in progress, ignoring click"): without this, a
	//// silent refusal looks just like a mute server.
	page.on('console', (m) => {
		const text = m.text();
		if (/payment|paiement|stripe|token|declin|refus/i.test(text)) {
			exchanges.push(`CONSOLE ${m.type()}: ${text.slice(0, 180)}`);
		}
	});
	return exchanges;
}

/** Put exactly one item in the cart, so amounts stay predictable. */
async function minimalCart(page) {
	await emptyCart(page);
	const item = await firstBuyableItem(page);
	if (!item) return null;
	await addToCart(page, item.item_code, 1);
	const quotation = await readQuotation(page);
	return quotation && quotation.doc ? quotation.doc : null;
}

test.describe('Card payment (Stripe, test keys)', () => {
	test.describe.configure({mode: 'serial'});

	test('a signed-in customer pays and their order is created', async ({page}) => {
		test.setTimeout(240_000);
		const exchanges = watchPayment(page);
		await signIn(page);

		const quotation = await minimalCart(page);
		test.skip(!quotation, 'the cart could not be filled');
		const quotationName = quotation.name;

		test.skip(!(await goToPaymentStep(page)), 'no shipping method available');

		const tile = await fillCard(page, CARDS.accepted);
		await submitPayment(page, tile);

		//// Success is read from the server, never from an on-screen message: that
		//// is the only proof an order genuinely exists.
		await expect
			.poll(async () => quotationState(page, quotationName), {
				timeout: PAYMENT_TIMEOUT,
				message: () =>
					'the quotation never became an order. Exchanges:\n' +
					(exchanges.length ? exchanges.join('\n') : '(no payment call observed)'),
			})
			.not.toBe('draft');

		//// And the customer must be taken somewhere other than the card form.
		await expect
			.poll(() => page.url(), {timeout: 30_000, message: 'the customer stays on the checkout'})
			.not.toContain('/checkout');
	});

	//// This test uncovered three defects, all fixed since:
	////
	//// 1. `window.stripe = true` acted as an "already initialized" guard, yet
	////    it said nothing about whether Stripe.js had actually loaded. On the
	////    template's second render, initStripe() would run before
	////    `window.Stripe` existed, leaving the card form inert.
	//// 2. The template's six frappe.call calls had NO `error` handler at all: on
	////    a 404 or a timeout, neither the success nor the error branch would
	////    run — a frozen screen, no message.
	//// 3. showMessagePayment() wrote into the FIRST `.error.payment-message` in
	////    the document, which belongs to the first method in the list rather
	////    than the one being paid: the message existed in the DOM, folded away
	////    in a tile that wasn't selected, and the customer saw nothing.
	////
	//// The whole chain now runs (create_payment_request →
	//// make_payment → handle_payment_failure) and the decline is displayed.
	test('a declined card shows a message and creates no order', async ({page}) => {
		test.setTimeout(240_000);
		const exchanges = watchPayment(page);
		await signIn(page);

		const quotation = await minimalCart(page);
		test.skip(!quotation, 'the cart could not be filled');
		const quotationName = quotation.name;

		test.skip(!(await goToPaymentStep(page)), 'no shipping method available');

		const tile = await fillCard(page, CARDS.declined);
		await submitPayment(page, tile);

		//// A decline must be SEEN. The worst payment failure is one that leaves
		//// the customer in front of an inert screen, with no idea whether they paid.
		////
		//// The message can come from the tile (a Stripe tokenisation error) or
		//// from a Frappe msgprint (declined at the time of the charge, server
		//// side): both count, only silence is a defect.
		const readMessages = () =>
			page.evaluate(() =>
				[
					...document.querySelectorAll(
						'.payment-method-item.selected .payment-message, ' +
							'.payment-method-item.selected [role="alert"], ' +
							'.modal.show, .msgprint, .alert-danger, #payment-error'
					),
				]
					.filter((z) => z.offsetHeight > 0 && z.textContent.trim().length > 3)
					.map((z) => z.textContent.trim().slice(0, 120))
			);

		let messages = [];
		const deadline = Date.now() + PAYMENT_TIMEOUT;
		while (Date.now() < deadline) {
			messages = await readMessages();
			if (messages.length) break;
			await page.waitForTimeout(2000);
		}

		//// Playwright does not evaluate a message function inside .poll: the
		//// diagnosis is built here, otherwise the failure just says "expected
		//// true, got false".
		await test.info().attach('payment-exchanges', {
			body: exchanges.join('\n') || '(no call observed)',
			contentType: 'text/plain',
		});
		expect(
			messages.length,
			`card declined with no visible message. Exchanges:\n${exchanges.join('\n') || '(none)'}`
		).toBeGreaterThan(0);

		//// And above all: nothing must have been ordered.
		expect(
			await quotationState(page, quotationName),
			'an order was created despite the decline'
		).toBe('draft');
		expect(page.url(), 'the customer was taken elsewhere despite the failure').toContain('/checkout');
	});

	test('the payment button cannot be clicked twice', async ({page}) => {
		test.setTimeout(240_000);
		await signIn(page);

		const quotation = await minimalCart(page);
		test.skip(!quotation, 'the cart could not be filled');
		test.skip(!(await goToPaymentStep(page)), 'no shipping method available');

		const tile = await fillCard(page, CARDS.accepted);
		const button = tile.locator('.btn-submit-payment:visible').first();
		//// Goes through submitPayment, which re-selects the tile if the
		//// methods refresh made it lose that state — without which the click
		//// fails on a locked button, for a reason that has nothing to do with
		//// the double-click being tested.
		await submitPayment(page, tile);

		//// Double payment = double charge. The button must lock on the very
		//// first click, even before Stripe has responded.
		await expect
			.poll(async () => button.isDisabled().catch(() => true), {
				timeout: 20_000,
				message: 'the button stays clickable after the first click',
			})
			.toBe(true);
	});
});

test.describe('Terms and conditions', () => {
	test('paying without accepting the terms is refused', async ({page}) => {
		test.setTimeout(240_000);
		await signIn(page);

		const quotation = await minimalCart(page);
		test.skip(!quotation, 'the cart could not be filled');
		const quotationName = quotation.name;
		test.skip(!(await goToPaymentStep(page)), 'no shipping method available');

		const tile = await fillCard(page, CARDS.accepted);
		const terms = tile.locator('.terms-acceptance').first();
		test.skip((await terms.count()) === 0, 'no terms box on this site');

		//// The tile must be selected for the terms handler to apply: without
		//// that, unchecking locks nothing and the test fails, wrongly blaming the
		//// app for accepting a payment without accepting the terms.
		if (!(await tile.evaluate((e) => e.classList.contains('selected')))) {
			await tile.click();
			await page.waitForTimeout(2000);
		}
		await terms.uncheck();
		await expect(terms).not.toBeChecked();

		//// The refusal shows up as a LOCKED button, not as a click that fails.
		//// Trying to click here used to fail on "element is disabled" — which is
		//// precisely the expected proof, yet read as a failure.
		const button = tile.locator('.btn-submit-payment:visible').first();
		await expect(button, 'paying is still possible without accepting the terms').toBeDisabled();

		expect(
			await quotationState(page, quotationName),
			'an order was placed without the terms being accepted'
		).toBe('draft');
	});
});
