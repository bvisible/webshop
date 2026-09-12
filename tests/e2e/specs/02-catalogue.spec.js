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

	//// The one product card (templates/includes/product_card.html): every tile carries
	//// its picture, its name and its price through the same hooks, whatever the page.
	test('chaque carte porte une image, un nom et un prix', async ({page}) => {
		await page.goto('/all-products');
		await page.waitForLoadState('networkidle');
		const cartes = page.locator('.wsp-card--grid');
		expect(await cartes.count(), 'aucune carte du catalogue').toBeGreaterThan(0);
		const premiere = cartes.first();
		await expect(premiere.locator('.wsp-card__media')).toBeVisible();
		await expect(premiere.locator('.wsp-card__title')).toBeVisible();
		await expect(premiere.locator('.wsp-card__title')).not.toHaveText(/^\s*$/);
		//// a gift card shows no price; every other tile does
		const prix = premiere.locator('.wsp-card__price');
		if (await prix.count()) await expect(prix).toContainText(/\d/);
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

	//// The promises (free delivery from, delivery time, returns) come from Webshop
	//// Settings; a shop that set none prints no block at all, so the test can only say
	//// "when there is a block, it says something".
	test('les promesses de la boutique se lisent sous le bouton', async ({page}) => {
		const bloc = page.locator('.wsp-promises');
		test.skip((await bloc.count()) === 0, 'aucune promesse réglée sur ce site');
		await expect(bloc).toBeVisible();
		const lignes = bloc.locator('.wsp-promises__item');
		expect(await lignes.count()).toBeGreaterThan(0);
		await expect(lignes.first()).not.toHaveText(/^\s*$/);
	});

	test('une photo ouvre le zoom, Échap le ferme', async ({page}) => {
		const image = page.locator('.product-image img').filter({ visible: true }).first();
		test.skip((await image.count()) === 0, 'produit sans image');
		await image.click();
		const zoom = page.locator('.image-zoom-view');
		await expect(zoom).toBeVisible();
		await expect(zoom.locator('.zoom-image-container img')).toBeVisible();
		await page.keyboard.press('Escape');
		await expect(zoom).toBeHidden();
	});

	test('la description est un repli ouvert, les autres se déplient', async ({page}) => {
		const replis = page.locator('details.wsp-acc');
		test.skip((await replis.count()) === 0, 'produit sans description ni caractéristiques');
		const premier = replis.first();
		await expect(premier).toHaveAttribute('open', '');
		const ferme = page.locator('details.wsp-acc:not([open])').first();
		if (await ferme.count()) {
			await ferme.locator('summary').click();
			await expect(ferme).toHaveAttribute('open', '');
		}
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
