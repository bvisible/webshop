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
});
