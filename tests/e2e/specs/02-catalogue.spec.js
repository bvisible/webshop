//// Neoffice — added file (no upstream equivalent).
//// The catalogue and the product page, including the layout fixes of 2026-08
//// that were until now only ever checked by eye.

const {test, expect} = require('@playwright/test');
const {connecter, premierArticleAchetable} = require('../fixtures/boutique');

test.describe('Catalogue', () => {
	test('la boutique liste des produits', async ({page}) => {
		await page.goto('/all-products');
		await page.waitForLoadState('networkidle');
		//// Le thème rend les vignettes en .card génériques: le seul repère stable
		//// est le lien vers la fiche produit.
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

	//// Le thème rend déjà le titre dans son en-tête ; le gabarit du produit en
	//// posait un second. Les deux existent toujours dans le DOM — l'un est
	//// masqué — donc le test compte ce qui est VISIBLE, pas ce qui existe.
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

	//// Le bloc d'avis vide ne doit pas occuper l'écran pour dire « 0 avis ».
	test('le bloc d’avis vide n’affiche pas un zéro inutile', async ({page}) => {
		const bloc = page.locator('.reviews-section, #reviews');
		if ((await bloc.count()) === 0) return;              // pas de bloc: conforme
		if (!(await bloc.first().isVisible())) return;        // masqué: conforme
		await expect(bloc.first()).not.toHaveText(/^\s*0\s*avis\s*$/i);
	});

	test('l’image du produit se charge réellement', async ({page}) => {
		const image = page.locator('.product-image img, .website-image img, img.product-image').first();
		if ((await image.count()) === 0) test.skip(true, 'produit sans image');
		await expect(image).toBeVisible();
		//// naturalWidth = 0 : la balise est là mais le fichier n'a pas chargé.
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
		//// L'ajout est asynchrone : on attend le total, pas un délai arbitraire.
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

/** Total quantity in the cart, read from the server. */
async function quantiteAuPanier(page) {
	const devis = await page.evaluate(
		() =>
			new Promise((res) =>
				frappe.call({
					method: 'webshop.webshop.shopping_cart.cart.get_cart_quotation',
					callback: (r) => res(r.message),
					error: () => res(null),
				})
			)
	);
	const lignes = (devis && devis.doc && devis.doc.items) || [];
	return lignes.reduce((somme, l) => somme + (l.qty || 0), 0);
}
