//// Neoffice — added file (no upstream equivalent).
//// One button for the site and its shop (2026-09-13): the site chrome draws every button
//// through :where(.u-btn), and that rule is on the shop's pages too — so a reference
//// <a class="u-btn u-btn--primary"> injected into a shop page is measured exactly where
//// the shop draws. The buy button, the cart's and the checkout's buttons must match it
//// in shape (padding, radius, font) and in colour (--btn-primary and its label); the
//// shop's outline buttons must match .u-btn--outline. Skips on a site without the
//// chrome (no :where(.u-btn) rule: the reference has no padding of its own).

const {test, expect} = require('@playwright/test');
const {signIn, addToCart, firstBuyableItem, emptyCart} = require('../fixtures/shop');

const SHAPE = [
	'paddingTop',
	'paddingRight',
	'borderRadius',
	'fontSize',
	'fontWeight',
	'lineHeight',
	'fontFamily',
];
const COLOUR = ['backgroundColor', 'color'];

//// Reads the computed style of the first visible match, next to an injected reference.
async function measure(page, selector, variant = 'u-btn--primary') {
	return page.evaluate(
		({selector, variant, keys}) => {
			const ref = document.createElement('a');
			ref.className = 'u-btn ' + variant;
			ref.textContent = 'Reference';
			(document.querySelector('.page-content-wrapper') || document.body).appendChild(ref);
			const read = (el) => {
				const cs = getComputedStyle(el);
				return Object.fromEntries(
					keys.map((k) => [k, k === 'fontFamily' ? cs[k].split(',')[0] : cs[k]])
				);
			};
			const target = [...document.querySelectorAll(selector)].find(
				(el) => el.getBoundingClientRect().height > 0
			);
			const out = {
				reference: read(ref),
				button: target ? read(target) : null,
				text: target ? target.textContent.trim().slice(0, 40) : null,
			};
			ref.remove();
			return out;
		},
		{selector, variant, keys: [...SHAPE, ...COLOUR]}
	);
}

function sameShape(measured, keys = SHAPE) {
	const gaps = keys
		.filter((k) => measured.button[k] !== measured.reference[k])
		.map((k) => `${k}: ${measured.button[k]} ≠ ${measured.reference[k]}`);
	expect(gaps, `"${measured.text}" differs from the site's own button`).toEqual([]);
}

test.describe("The shop's buttons are the site's", () => {
	test.beforeEach(async ({page}) => {
		await page.goto('/cart');
		await page.waitForLoadState('networkidle');
		const chrome = await page.evaluate(() => {
			const a = document.createElement('a');
			a.className = 'u-btn';
			document.body.appendChild(a);
			const pad = getComputedStyle(a).paddingLeft;
			a.remove();
			return pad !== '0px';
		});
		test.skip(!chrome, 'no Builder chrome on this site: there is no reference button');
	});

	test('the "add to cart" button has the shape and the colour of the site primary', async ({page}) => {
		await signIn(page);
		const item = await firstBuyableItem(page);
		test.skip(!item, 'no buyable article');
		await page.goto(item.route);
		await page.waitForLoadState('networkidle');
		//// A template product shows its button once every attribute is chosen.
		for (const row of await page.locator('.wsp-variants__row').all()) {
			const chip = row.locator('.wsp-variants__chip:not(.is-impossible):not(.is-unavailable)').first();
			if (await chip.count()) await chip.click();
		}
		const measured = await measure(page, '.wsp-buy .btn-add-to-cart, .variant-grid-footer .btn-add-to-cart');
		test.skip(!measured.button, 'no buy button visible for this account');
		sameShape(measured, [...SHAPE, ...COLOUR]);
	});

	test("the cart and the checkout: the site's solid and outline buttons", async ({page}) => {
		await signIn(page);
		const item = await firstBuyableItem(page);
		test.skip(!item, 'no buyable article');
		await emptyCart(page);
		await addToCart(page, item.item_code, 1);
		await page.goto('/cart');
		await page.waitForLoadState('networkidle');
		const solid = await measure(page, '.btn.btn-primary:not(.btn-sm):not(.btn-page):not(.wsp-card__cta)');
		expect(solid.button, 'a solid button on the cart').toBeTruthy();
		sameShape(solid, [...SHAPE, ...COLOUR]);
		const outline = await measure(
			page,
			'.btn.btn-outline-primary, .btn.btn-secondary',
			'u-btn--outline'
		);
		expect(outline.button, 'an outline button on the cart').toBeTruthy();
		sameShape(outline, [...SHAPE, ...COLOUR]);
		await page.goto('/checkout');
		await page.waitForLoadState('networkidle');
		const next = await measure(page, '.btn.btn-primary:not(.btn-sm):not(.btn-page)');
		test.skip(!next.button, 'no checkout tunnel on this site');
		sameShape(next, [...SHAPE, ...COLOUR]);
	});

	test('the tile and the view toggle keep a size of their own', async ({page}) => {
		await page.goto('/all-products');
		await page.waitForLoadState('networkidle');
		const tile = await measure(page, '.wsp-card__cta');
		test.skip(!tile.button, 'no tile carries a button');
		expect(tile.button.paddingTop, "the tile's quiet button").not.toBe(tile.reference.paddingTop);
		const toggle = await measure(page, '#toggle-view .btn-primary');
		if (toggle.button)
			expect(toggle.button.paddingTop, 'the view toggle').not.toBe(toggle.reference.paddingTop);
	});
});
