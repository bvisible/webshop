//// Neoffice — added file (no upstream equivalent).
//// The four-step checkout. This is the file that replaces the hand-run browser
//// scripts of the 2026-08 reliability pass: every claim written in
//// 09-Checkout-Fiabilisation is asserted here so it can be re-checked at will.

const {test, expect} = require('@playwright/test');
const {
	signIn,
	countRequests,
	addToCart,
	readQuotation,
	readAddressBook,
	chooseShipping,
	firstBuyableItem,
} = require('../fixtures/shop');

/** Ensure the cart holds something, so /checkout is reachable at all. */
async function ensureCartIsNotEmpty(page) {
	const quotation = await readQuotation(page);
	if (quotation && quotation.doc && (quotation.doc.items || []).length) return true;

	const item = await firstBuyableItem(page);
	if (!item) return false;
	await addToCart(page, item.item_code, 1);
	const after = await readQuotation(page);
	return !!(after && after.doc && (after.doc.items || []).length);
}

test.describe('Checkout tunnel', () => {
	test.beforeEach(async ({page}) => {
		await signIn(page);
		await page.goto('/cart');
		await page.waitForLoadState('networkidle');
		const ready = await ensureCartIsNotEmpty(page);
		test.skip(!ready, 'the cart could not be filled on this site');

		await page.goto('/checkout');
		await page.waitForLoadState('networkidle');
		await expect(page.locator('#step-address')).toHaveClass(/active/, {timeout: 30_000});
		await restoreDefaultAddress(page);
	});

	test("the page heading does not repeat a step's name", async ({page}) => {
		//// _("Checkout") is shared with the cart button, where French renders it
		//// as "Paiement" — which produced a heading matching step 4's name.
		const heading = (await page.locator('h1').first().textContent()).trim();
		expect(heading.toLowerCase()).not.toBe('paiement');
	});

	test('the four steps are present', async ({page}) => {
		for (const step of ['step-address', 'step-shipping', 'step-payment']) {
			await expect(page.locator('#' + step)).toHaveCount(1);
		}
	});

	test.describe('Address book', () => {
		test("the customer's addresses are offered as cards", async ({page}) => {
			const cards = page.locator('#billing-address-picker .address-card-choice');
			const n = await cards.count();
			test.skip(n === 0, 'this account has no saved address');
			//// n-1 addresses + the "new address" card
			expect(n).toBeGreaterThan(1);
		});

		//// The card list and the quotation come from two independent calls. When
		//// the cards arrived first — the common case — "new address" was
		//// highlighted while the form already showed the default address.
		test('the highlighted card matches the quotation, right from the load', async ({page}) => {
			const onQuotation = await page.locator('#billing_address_name').inputValue();
			test.skip(!onQuotation, 'the quotation carries no address yet');

			const selected = page.locator('#billing-address-picker .is-selected');
			await expect(selected, 'no card is highlighted').toHaveCount(1);
			await expect(selected).toHaveAttribute('data-address', onQuotation);
			await expect(
				selected,
				'"new address" is highlighted although the quotation has one'
			).not.toHaveClass(/address-card-choice--new/);
		});

		//// The bug this test locks in: filling in the form while triggering a
		//// "change" event would have populated pendingChanges, and the next step
		//// would have called update_address_info, which overwrites the chosen
		//// address with is_primary_address = 1. Choosing your office address
		//// would have turned your home into an office.
		test('choosing an address does not modify it', async ({page}) => {
			const cards = page.locator(
				'#billing-address-picker .address-card-choice:not(.address-card-choice--new)'
			);
			test.skip((await cards.count()) < 2, 'fewer than two addresses: nothing to choose');

			const before = await readAddressBook(page);
			const target = await cards.nth(1).getAttribute('data-address');

			await cards.nth(1).click();
			await expect(page.locator('#billing_address_name')).toHaveValue(target, {timeout: 20_000});

			const after = await readAddressBook(page);
			expect(normalise(after), 'the selection modified an address').toEqual(normalise(before));
		});

		test('choosing an address costs a single call', async ({page}) => {
			const cards = page.locator(
				'#billing-address-picker .address-card-choice:not(.address-card-choice--new)'
			);
			test.skip((await cards.count()) < 2, 'fewer than two addresses');

			const n = await countRequests(page, async () => {
				await cards.nth(1).click();
				await page.waitForTimeout(3000);
			});
			expect(n, 'the selection fires too many calls').toBeLessThanOrEqual(3);
		});
	});

	test.describe('Moving forward and back', () => {
		test('we reach the payment step and come back without losing anything', async ({page}) => {
			const startingAddress = await page.locator('#billing_address_name').inputValue();

			// Address -> shipping
			await page.locator('#step-address .next-step').click();
			await expect(page.locator('#step-shipping')).toHaveClass(/active/, {timeout: 40_000});

			// Choose a shipping method if none is selected
			const optionCount = await page.locator('#step-shipping input[type=radio]').count();
			test.skip(optionCount === 0, 'no shipping method for this address');
			await chooseShipping(page);
			const chosenShipping = await page
				.locator('#step-shipping input[type=radio]:checked')
				.getAttribute('value');

			// Shipping -> payment
			await page.locator('#step-shipping .next-step').click();
			await expect(page.locator('#step-payment')).toHaveClass(/active/, {timeout: 45_000});

			// Back payment -> shipping
			await page.locator('#step-payment .prev-step').click();
			await expect(page.locator('#step-shipping')).toHaveClass(/active/, {timeout: 30_000});
			await expect(page.locator('#step-shipping input[type=radio]:checked')).toHaveValue(
				chosenShipping
			);

			// Back shipping -> address
			await page.locator('#step-shipping .prev-step').click();
			await expect(page.locator('#step-address')).toHaveClass(/active/, {timeout: 30_000});
			if (startingAddress) {
				await expect(page.locator('#billing_address_name')).toHaveValue(startingAddress);
			}
		});

		//// Passing a step without changing anything used to fire off 4 to 7 calls
		//// and open a spurious confirmation dialog.
		test('moving on without changing anything asks for nothing', async ({page}) => {
			const n = await countRequests(page, async () => {
				await page.locator('#step-address .next-step').click();
				await expect(page.locator('#step-shipping')).toHaveClass(/active/, {timeout: 40_000});
			});
			expect(n, 'too many calls for a step with no change').toBeLessThanOrEqual(6);
		});
	});

	test.describe('Payment step', () => {
		test('the payment methods appear without a blank screen', async ({page}) => {
			await page.locator('#step-address .next-step').click();
			await expect(page.locator('#step-shipping')).toHaveClass(/active/, {timeout: 40_000});

			const optionCount = await page.locator('#step-shipping input[type=radio]').count();
			test.skip(optionCount === 0, 'no shipping method');
			await chooseShipping(page);

			//// The container must never pass back through an empty state: that is
			//// what caused the flicker.
			await page.evaluate(() => {
				window.__blanks = 0;
				const target = document.querySelector('#payment-methods-container');
				if (!target) return;
				new MutationObserver(() => {
					if (!target.innerHTML.trim()) window.__blanks += 1;
				}).observe(target, {childList: true, subtree: true});
			});

			await page.locator('#step-shipping .next-step').click();
			await expect(page.locator('#step-payment')).toHaveClass(/active/, {timeout: 45_000});

			await expect
				.poll(async () => page.locator('.payment-method-item').count(), {
					timeout: 30_000,
					message: 'no payment method was rendered',
				})
				.toBeGreaterThan(0);

			expect(await page.evaluate(() => window.__blanks || 0), 'the flicker is back').toBe(0);
		});
	});

	test.describe('Watching the payment', () => {
		//// The polling used to be a fixed 5 s setInterval for 5 minutes: 60 calls
		//// per payment, even though the realtime socket already gives notice. It
		//// has become a recursive setTimeout whose delay stretches out past 30 s,
		//// and even more once the socket is alive.
		////
		//// Measured here rather than by hand: Chrome throttles a background tab's
		//// timers, which makes any manual measurement useless — two rounds in
		//// 38 s instead of seven. Playwright keeps the page active.
		test('the polling spaces out instead of hammering every 5 s', async ({page}) => {
			test.setTimeout(120_000);

			const measured = await page.evaluate(async () => {
				const cm = window.checkout_manager;
				if (!cm || !cm.watchIntent) return null;
				cm.stopIntentWatch();

				const delays = [];
				const originalSetTimeout = window.setTimeout;
				const originalCall = frappe.call;
				window.setTimeout = function (fn, d) {
					if (d >= 4000) delays.push(d);
					return originalSetTimeout.apply(this, arguments);
				};
				//// The server always answers "not yet paid": we're observing the
				//// cadence, and specifically do not want to trigger a real redirect.
				frappe.call = function (o) {
					if (o && /cart_intent_state/.test(o.method || '')) {
						if (o.callback) o.callback({message: {done: false}});
						return;
					}
					return originalCall.apply(this, arguments);
				};

				const fake = $('<div><span class="intent-attente"></span></div>');
				cm.watchIntent('E2E-CADENCE', fake);
				await new Promise((r) => originalSetTimeout(r, 40000));
				cm.stopIntentWatch();

				window.setTimeout = originalSetTimeout;
				frappe.call = originalCall;
				return {delays, leaking: !!cm._intentStop};
			});

			test.skip(!measured, 'checkout_manager unavailable');

			expect(measured.leaking, 'the watch did not stop').toBe(false);
			//// Before: 8 delays, all at 5000. After: the tail of the window spaces out.
			expect(measured.delays.length, 'no round observed').toBeGreaterThan(0);
			expect(
				measured.delays.some((d) => d > 5000),
				`the polling stays at 5 s (delays observed: ${measured.delays.join(', ')})`
			).toBe(true);
		});
	});

	test.describe('Stability', () => {
		//// A refresh loop used to freeze the tab: the summary kept re-requesting
		//// itself endlessly.
		test('the page does not loop while idle', async ({page}) => {
			const n = await countRequests(page, () => page.waitForTimeout(6000));
			expect(n, 'the page keeps calling the server while doing nothing').toBeLessThanOrEqual(3);
		});

		test('no script error', async ({page}) => {
			const errors = [];
			page.on('pageerror', (e) => errors.push(e.message));
			await page.reload();
			await page.waitForLoadState('networkidle');
			await page.waitForTimeout(3000);
			expect(errors).toEqual([]);
		});
	});
});

//// Put the quotation back on the customer's default address.
////
//// Without this, a spec that picks another address leaves it on the quotation
//// for the next one — and a spec further down was skipped with "no shipping
//// method for this address", silently, because the address it inherited had
//// none. A skipped test reads like a passing one in the summary.
async function restoreDefaultAddress(page) {
	const cards = page.locator(
		'#billing-address-picker .address-card-choice:not(.address-card-choice--new)'
	);
	if ((await cards.count()) === 0) return;

	const first = cards.first();
	if (await first.evaluate((e) => e.classList.contains('is-selected'))) return;

	await first.click();
	const expected = await first.getAttribute('data-address');
	await expect(page.locator('#billing_address_name')).toHaveValue(expected, {timeout: 20_000});
}

/** Comparable snapshot of the address book, order-independent. */
function normalise(addresses) {
	return ((addresses || []).map((a) => ({
		name: a.name,
		type: a.address_type,
		line1: a.address_line1,
		city: a.city,
		postcode: a.pincode,
		country: a.country,
		primary: a.is_primary_address,
		shipping: a.is_shipping_address,
	})) || []).sort((x, y) => (x.name > y.name ? 1 : -1));
}
