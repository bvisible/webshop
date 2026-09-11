//// Neoffice — added file (no upstream equivalent).
//// The catalogue and the product page, including the layout fixes of 2026-08
//// that were until now only ever checked by eye.

const {test, expect} = require('@playwright/test');
const {connecter, premierArticleAchetable, lireDevis} = require('../fixtures/boutique');

test.describe('Catalogue', () => {
	test('la boutique liste des produits', async ({page}) => {
		await page.goto('/all-products');
		await page.waitForLoadState('networkidle');
		//// The theme renders thumbnails as generic .card elements: the only stable
		//// landmark is the link to the product page.
		const cartes = page.locator('a[href*="/products/"]');
		expect(await cartes.count(), 'la boutique doit afficher des produits').toBeGreaterThan(0);
	});

	test('un seul titre visible sur le catalogue', async ({page}) => {
		await page.goto('/all-products');
		await page.waitForLoadState('networkidle');
		expect(await compterTitresVisibles(page), 'double titre revenu').toBe(1);
	});
});

test.describe('Fiche produit', () => {
	test.beforeEach(async ({page}) => {
		const article = await premierArticleAchetable(page);
		test.skip(!article, 'aucun article publié sur ce site');
		await page.goto('/' + article.route);
		await page.waitForLoadState('networkidle');
	});

	//// The theme already renders the title in its header; the product template
	//// used to add a second one. Both still exist in the DOM — one is
	//// hidden — so the test counts what is VISIBLE, not what exists.
	test('un seul titre visible', async ({page}) => {
		expect(await compterTitresVisibles(page), 'le double titre est revenu').toBe(1);
	});

	test('le prix est affiché', async ({page}) => {
		const prix = page.locator('.product-price, [itemprop="price"]').first();
		await expect(prix).toBeVisible();
		await expect(prix).toContainText(/\d/);
	});

	test('le bouton d’ajout au panier est présent et actionnable', async ({page}) => {
		const bouton = page.locator('.btn-add-to-cart').first();
		await expect(bouton).toBeVisible();
		await expect(bouton).toBeEnabled();
	});

	//// The empty reviews block must not take up screen space just to say « 0 avis ».
	test('le bloc d’avis vide n’affiche pas un zéro inutile', async ({page}) => {
		const bloc = page.locator('.reviews-section, #reviews');
		if ((await bloc.count()) === 0) return;              // no block: as expected
		if (!(await bloc.first().isVisible())) return;        // hidden: as expected
		await expect(bloc.first()).not.toHaveText(/^\s*0\s*avis\s*$/i);
	});

	test('l’image du produit se charge réellement', async ({page}) => {
		//// The gallery draws one layout for a wide screen and a swipe strip for a phone;
		//// the other is in the DOM but hidden. The picture to check is the visible one.
		const image = page.locator('.product-image img, .website-image img, img.product-image').filter({ visible: true }).first();
		if ((await image.count()) === 0) test.skip(true, 'produit sans image');
		await expect(image).toBeVisible();
		//// naturalWidth = 0: the tag is there but the file failed to load.
		expect(await image.evaluate((i) => i.naturalWidth), 'image cassée').toBeGreaterThan(0);
	});
});

test.describe('Ajout au panier', () => {
	test('ajouter un article incrémente le panier', async ({page}) => {
		await connecter(page);
		const article = await premierArticleAchetable(page);
		test.skip(!article, 'aucun article publié');

		await page.goto('/' + article.route);
		await page.waitForLoadState('networkidle');

		const avant = await quantiteAuPanier(page);
		await page.locator('.btn-add-to-cart').first().click();
		//// Adding is asynchronous: wait for the total, not an arbitrary delay.
		await expect
			.poll(async () => quantiteAuPanier(page), {timeout: 20_000, message: 'le panier n’a pas bougé'})
			.toBeGreaterThan(avant);
	});
});

/** Titles that actually occupy space on screen. */
async function compterTitresVisibles(page) {
	return page.evaluate(
		() =>
			[...document.querySelectorAll('h1')].filter((h) => {
				const cs = getComputedStyle(h);
				return cs.display !== 'none' && cs.visibility !== 'hidden' && h.getBoundingClientRect().height > 0;
			}).length
	);
}

//// Read over HTTP, not through page.evaluate: clicking "add to cart" navigates
//// on some themes, and a frappe.call started just before that dies with
//// "Execution context was destroyed" — an error about the test harness, blamed
//// on the shop.
async function quantiteAuPanier(page) {
	const devis = await lireDevis(page);
	const lignes = (devis && devis.doc && devis.doc.items) || [];
	return lignes.reduce((somme, l) => somme + (l.qty || 0), 0);
}
