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
	{nom: 'le catalogue', chemin: '/all-products'},
	{nom: 'les catégories', chemin: '/shop-by-category'},
	{nom: 'la liste de souhaits vide', chemin: '/wishlist'},
];

test.describe('Contraste', () => {
	let auditContrast;
	test.beforeAll(async () => {
		({auditContrast} = await import('../visual/contrast.mjs'));
	});

	for (const {nom, chemin} of PAGES) {
		test(`${nom} se lit sur son fond`, async ({page}) => {
			await page.goto(chemin);
			await page.waitForLoadState('networkidle');
			const {checked, findings} = await auditContrast(page, {minimum: 3});
			expect(checked, 'rien n\'a été lu sur la page').toBeGreaterThan(10);
			expect(findings, findings.map((f) => `${f.ratio}:1 ${JSON.stringify(f.text)} — ${f.path}`).join('\n')).toEqual([]);
		});
	}

	test('la fiche produit se lit sur son fond', async ({page}) => {
		await page.goto('/all-products');
		await page.waitForLoadState('networkidle');
		const lien = page.locator('.wsp-card--grid a[href*="/products/"]').first();
		const route = await lien.getAttribute('href');
		test.skip(!route, 'aucun produit dans le catalogue');
		await page.goto(route);
		await page.waitForLoadState('networkidle');
		const {checked, findings} = await auditContrast(page, {minimum: 3});
		expect(checked, 'rien n\'a été lu sur la fiche').toBeGreaterThan(10);
		expect(findings, findings.map((f) => `${f.ratio}:1 ${JSON.stringify(f.text)} — ${f.path}`).join('\n')).toEqual([]);
	});
});
