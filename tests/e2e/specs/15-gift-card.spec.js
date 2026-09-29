//// //// Neoffice — added file (no upstream equivalent).
////
//// The gift-card path at checkout, because no test covered it and a live shop
//// holds 128 of them (measured 2026-09-22). What this proves: a card the
//// customer owns pays part of the basket, it locks the loyalty block while it
//// is on, removing it hands the original total back, and none of it burns the
//// card — so the spec can run every day on the same card.
const {test, expect} = require('@playwright/test');
const {
	signIn,
	emptyCart,
	addToCart,
	firstBuyableItem,
	goToPaymentStep,
	readQuotation,
} = require('../fixtures/shop');
const {pressUntil} = require('../fixtures/payment');

const TIMEOUT = 90_000;

async function quotationTotal(page) {
	const answer = await readQuotation(page);
	return Number(((answer && (answer.doc || answer)) || {}).grand_total);
}

//// The codes the customer sees on their own page. Empty when the shop has gift
//// cards switched off, or when this account owns none.
async function customerGiftCards(page) {
	await page.goto('/gift_cards');
	await page.waitForLoadState('networkidle');
	return page.locator('.gift-card-code').allInnerTexts();
}

test.describe('Gift card at checkout', () => {
	test.setTimeout(TIMEOUT);

	test("a customer's own card pays part of the basket, locks the points, and comes off unspent", async ({
		page,
	}) => {
		await signIn(page);
		const cards = await customerGiftCards(page);
		test.skip(
			cards.length === 0,
			'this account holds no gift card on this instance: seed one (README, "gift cards")'
		);
		const code = cards[0].trim();

		await emptyCart(page);
		const item = await firstBuyableItem(page);
		expect(item, 'no buyable article in the catalogue').toBeTruthy();
		//// an object, not a code (see 14-loyalty-points): the object adds nothing.
		await addToCart(page, item.item_code, 1);
		//// The coupon block lives inside step 4 and is hidden before it: reading it
		//// earlier finds nothing and the spec skips itself for a false reason.
		expect(await goToPaymentStep(page), 'the tunnel does not reach the payment step').toBeTruthy();

		const before = await quotationTotal(page);
		expect(before, 'the cart is empty, there is nothing to pay').toBeGreaterThan(0);

		//// Wait on the quotation, not on the button: the button comes back before
		//// the document is saved (see `waitForQuotation` in fixtures/payment.js).
		const withCard = await pressUntil(
			page,
			async () => {
				await page.locator('.txtcoupon').fill(code);
				await page.locator('.bt-coupon').click();
			},
			(doc) => Number(doc.grand_total) < before
		);
		expect(withCard, `the bill did not go down after the gift card (${before})`).toBeTruthy();

		//// Points and coupon are exclusive: the block says so, and the shop must
		//// hold the line, or a basket could be paid twice with the same value.
		const pointsField = page.locator('#loyalty-point-to-redeem');
		if ((await pointsField.count()) > 0) {
			await expect(pointsField, 'the points stay open while a card is applied').toBeDisabled();
		}

		const restored = await pressUntil(
			page,
			async () => {
				await page
					.locator('.bt-remove-coupon')
					.click()
					.catch(() => {});
			},
			(doc) => Math.abs(Number(doc.grand_total) - before) < 0.01
		);
		expect(restored, 'the gift card could not be removed, the original bill is not handed back').toBeTruthy();

		//// Applying then removing must not spend the card: otherwise a customer
		//// who changes their mind loses it, and this spec could run once.
		expect(
			(await customerGiftCards(page)).map((c) => c.trim()),
			'the card disappeared from the account after a mere try'
		).toContain(code);

		await emptyCart(page);
	});

	//// #650: a card applied at step 4 vanished when the customer went back, changed the shipping method
	//// and pressed Next on a slow connection, and they paid in full. The two updates (the method chosen,
	//// then the method re-applied on entering the payment step) each removed the coupon and put it back,
	//// and overlapped. Every call of the page is slowed here so they certainly do.
	test('a card applied at step 4 survives a shipping change made on a slow connection', async ({page}) => {
		test.setTimeout(600_000);
		await signIn(page);
		const cards = await customerGiftCards(page);
		test.skip(
			cards.length === 0,
			'this account holds no gift card on this instance: seed one (README, "gift cards")'
		);
		const code = cards[0].trim();

		await emptyCart(page);
		const item = await firstBuyableItem(page);
		expect(item, 'no buyable article in the catalogue').toBeTruthy();
		await addToCart(page, item.item_code, 1);
		expect(await goToPaymentStep(page), 'the tunnel does not reach the payment step').toBeTruthy();

		const before = await quotationTotal(page);
		const withCard = await pressUntil(
			page,
			async () => {
				await page.locator('.txtcoupon').fill(code);
				await page.locator('.bt-coupon').click();
			},
			(doc) => Number(doc.grand_total) < before
		);
		expect(withCard, `the bill did not go down after the gift card (${before})`).toBeTruthy();

		//// Every call of the page is slowed, by a delay that varies from one call to the next, so the two
		//// updates (the method just chosen, then the method re-applied by Next) overlap in a different way
		//// each round: one of the orders loses the coupon (the second update reads the quotation without it,
		//// or writes a stale copy over the coupon the first one just put back). The loss is a matter of
		//// timing, hence several rounds.
		let calls = 0;
		await page.route(
			(url) => url.pathname === '/',
			async (route) => {
				if (/cmd=/.test(route.request().postData() || '')) {
					calls += 1;
					await new Promise((resolve) => setTimeout(resolve, 300 + ((calls * 397) % 1400)));
				}
				await route.continue();
			}
		);

		for (let round = 1; round <= 6; round++) {
			await page.locator('#step-payment .prev-step').click();
			await expect(page.locator('#step-shipping')).toHaveClass(/active/, {timeout: 60_000});
			const radios = page.locator('#step-shipping input[type=radio]');
			const count = await radios.count();
			if (count > 1) {
				const id = await radios.nth(round % count).getAttribute('id');
				const label = id ? page.locator(`label[for="${id}"]`).first() : null;
				if (label && (await label.count())) await label.click().catch(() => {});
			}
			await page.locator('#step-shipping .next-step').click();
			await expect(page.locator('#step-payment')).toHaveClass(/active/, {timeout: 90_000});
			await expect
				.poll(
					async () => {
						const answer = await readQuotation(page);
						const doc = (answer && (answer.doc || answer)) || {};
						return Boolean(doc.gift_card_coupon) && Number(doc.grand_total) < before;
					},
					{timeout: 40_000, message: `the gift card is gone after round ${round}: the customer pays in full`}
				)
				.toBeTruthy();
		}

		//// leave the account as it was: the card off the basket, unspent
		await page.unroute(() => true).catch(() => {});
		await page
			.locator('.bt-remove-coupon')
			.click()
			.catch(() => {});
		await page.waitForTimeout(3000);
		await emptyCart(page);
	});
});
