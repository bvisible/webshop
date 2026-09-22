//// Neoffice — added file (no upstream equivalent).
//// Every text, control and icon of the shop's public pages reads on the ground it
//// sits on — for the chrome of the site under test. The shop draws with the chrome's
//// tokens, so its colours only exist once a real site renders them: on a reseller's
//// dark site the product title, the filter heading and the icons went dark on dark
//// while every light site looked fine (2026-09-11, neoffice-maintenance #369). The
//// audit itself is tests/e2e/visual/contrast.mjs, so it can also be run by hand
//// against a client's shop, where this suite has no account.

const {test, expect} = require('@playwright/test');

const PAGES = [
	{name: 'the catalogue', path: '/all-products'},
	{name: 'the categories', path: '/shop-by-category'},
	{name: 'the empty wishlist', path: '/wishlist'},
];

test.describe('Contrast', () => {
	let auditContrast;
	test.beforeAll(async () => {
		({auditContrast} = await import('../visual/contrast.mjs'));
	});

	for (const {name, path} of PAGES) {
		test(`${name} reads on its own ground`, async ({page}) => {
			await page.goto(path);
			await page.waitForLoadState('networkidle');
			const {checked, findings} = await auditContrast(page, {minimum: 3});
			//// An empty wishlist has four things to read; what matters is the list
			//// of findings.
			expect(checked, 'nothing was read on the page').toBeGreaterThan(0);
			expect(
				findings,
				findings.map((f) => `${f.ratio}:1 ${JSON.stringify(f.text)} — ${f.path}`).join('\n')
			).toEqual([]);
		});
	}

	test('the product page reads on its own ground', async ({page}) => {
		await page.goto('/all-products');
		await page.waitForLoadState('networkidle');
		const link = page.locator('.wsp-card--grid a[href*="/products/"]').first();
		const route = await link.getAttribute('href');
		test.skip(!route, 'no product in the catalogue');
		await page.goto(route);
		await page.waitForLoadState('networkidle');
		const {checked, findings} = await auditContrast(page, {minimum: 3});
		expect(checked, 'nothing was read on the product page').toBeGreaterThan(10);
		expect(
			findings,
			findings.map((f) => `${f.ratio}:1 ${JSON.stringify(f.text)} — ${f.path}`).join('\n')
		).toEqual([]);
	});
});
