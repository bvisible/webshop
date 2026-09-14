//// Neoffice — added file (no upstream equivalent).
//// The catalogue and the product page, including the layout fixes of 2026-08
//// that were until now only ever checked by eye.

const {test, expect} = require('@playwright/test');
const {connecter, premierArticleAchetable, lireDevis} = require('../fixtures/boutique');

//// On a phone the filters live in a drawer behind the "Filters" button: open it before
//// touching a filter. A no-op on a wide screen, where the column is always there.
async function fermerLesFiltres(page) {
	const fermer = page.locator('#closeFilterButton');
	if (await fermer.isVisible()) {
		await fermer.click();
		await expect(page.locator('#product-filters')).toBeHidden();
	}
}

async function ouvrirLesFiltres(page) {
	const colonne = page.locator('#product-filters');
	if (await colonne.isVisible()) return;
	const bouton = page.locator('#filterButton');
	if (await bouton.isVisible()) {
		await bouton.click();
		await expect(colonne).toBeVisible();
	}
}

test.describe('Catalogue', () => {
	//// A product that carries a video (Website Item → Videos) wears a play mark on its
	//// tile, and its gallery plays it in the lightbox — a hosted file through the
	//// browser's own player. Skips when the shop under test has no such product.
	test('un produit avec vidéo porte un badge et la lit dans la visionneuse', async ({page}) => {
		await page.goto('/all-products');
		await page.waitForLoadState('networkidle');
		const tuile = page.locator('.wsp-card--grid:has(.wsp-card__play)').first();
		test.skip((await tuile.count()) === 0, 'aucun produit avec vidéo sur cette boutique');
		await tuile.locator('a[href*="/products/"]').first().click();
		await page.waitForLoadState('networkidle');
		//// the gallery draws a layout for a wide screen and a strip for a phone, one of them hidden
		const videoTile = page.locator('.wsp-gallery__tile--video, .wsp-gallery__slide--video').filter({visible: true}).first();
		await expect(videoTile, 'la galerie doit montrer une tuile vidéo').toBeVisible();
		await expect(videoTile.locator('.wsp-gallery__play')).toBeVisible();
		await videoTile.click();
		const player = page.locator('.image-zoom-view .zoom-video');
		await expect(player, 'la visionneuse doit contenir un lecteur').toBeVisible();
		expect(await page.locator('.image-zoom-view').evaluate((e) => e.parentElement.tagName)).toBe('BODY');
		await page.keyboard.press('Escape');
		expect(await page.locator('.image-zoom-view .zoom-image-container').evaluate((e) => e.children.length), 'le lecteur doit être retiré à la fermeture').toBe(0);
	});

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

test.describe('Filtres', () => {
	//// The second-hand toggle sits right after the discount one and works the same way:
	//// a checkbox, a per-visitor preference, and only used units left in the listing.
	test('le filtre des occasions suit celui des promotions et ne garde que les occasions', async ({page}) => {
		await page.goto('/all-products');
		await page.waitForLoadState('networkidle');
		const toggle = page.locator('#second-hand-filters');
		test.skip((await toggle.count()) === 0, 'aucune occasion publiée sur cette boutique');
		await ouvrirLesFiltres(page);
		const blocs = await page.locator('#product-filters .filter-block').evaluateAll((els) => els.map((e) => e.id));
		expect(blocs.indexOf('second-hand-filters'), 'juste après le bloc des promotions').toBe(blocs.indexOf('discount-filters') + 1);
		await page.locator('#showSecondHandOnly').check();
		await page.waitForLoadState('networkidle');
		await expect(page.locator('.active-filter-badge[data-filter-type="second_hand"]')).toBeVisible();
		const cartes = page.locator('.wsp-card--grid');
		await expect(cartes.first()).toBeVisible();
		const total = await cartes.count();
		const occasions = await page.locator('.wsp-card--grid:has(.wsp-card__badge--condition)').count();
		expect(occasions, 'chaque tuile restante est une occasion').toBe(total);
		//// The chip's cross clears the toggle.
		//// the chip sits above the listing, outside the drawer: on a phone, close the drawer first
		await fermerLesFiltres(page);
		await page.locator('.active-filter-badge[data-filter-type="second_hand"]').filter({visible: true}).first().click();
		await page.waitForLoadState('networkidle');
		await expect(page.locator('#showSecondHandOnly')).not.toBeChecked();
		await page.evaluate(() => sessionStorage.removeItem('second_hand_filter_checked'));
	});

	//// "Clear all" and the sidebar's counter only exist under a filter; "Clear all" clears
	//// the toggles too, and a toggle lasts for the visit, not for the next one (2026-09-14).
	test('« Tout effacer » n’apparaît qu’avec un filtre, efface aussi les cases, et une case ne survit pas à la visite', async ({page}) => {
		await page.goto('/all-products');
		await page.evaluate(() => sessionStorage.clear());
		await page.reload();
		await page.waitForLoadState('networkidle');
		const effacer = page.locator('#product-filters .clear-filters');
		await expect(effacer).toBeHidden();
		await expect(page.locator('#results-count-live')).toHaveText('');
		const caseACocher = page.locator('#showDiscountOnly, #showSecondHandOnly').first();
		test.skip((await caseACocher.count()) === 0, 'ni promotion ni occasion sur cette boutique');
		await ouvrirLesFiltres(page);
		await caseACocher.check();
		await ouvrirLesFiltres(page);
		await page.waitForLoadState('networkidle');
		await expect(effacer).toBeVisible();
		await expect(page.locator('#results-count-live')).toContainText(/\d/);
		//// a later visit (another tab) starts clean
		const autre = await page.context().newPage();
		await autre.goto('/all-products');
		await autre.waitForLoadState('networkidle');
		await expect(autre.locator('#showDiscountOnly, #showSecondHandOnly').first()).not.toBeChecked();
		await expect(autre.locator('#product-filters .clear-filters')).toBeHidden();
		await autre.close();
		//// "Clear all" empties the toggles of this visit
		await ouvrirLesFiltres(page);
		await effacer.click();
		await page.waitForLoadState('networkidle');
		await expect(page.locator('#product-filters .clear-filters')).toBeHidden();
		await expect(page.locator('#showDiscountOnly, #showSecondHandOnly').first()).not.toBeChecked();
	});

	//// The quick order is offered next to the search box to whoever may use it.
	test('la commande rapide est proposée à côté de la recherche', async ({page}) => {
		await page.goto('/all-products');
		await page.waitForLoadState('networkidle');
		const lien = page.locator('.toolbar .wsp-quick-order-link');
		await expect(lien).toBeVisible();
		await expect(lien).toHaveAttribute('href', '/quick-order');
		await lien.click();
		await page.waitForURL(/quick-order/);
		await expect(page.locator('.wsh-qo__input')).toBeVisible();
	});

	//// On any screen, the price slider's handles sit inside the filter column (or the drawer).
	test('les poignées du sélecteur de prix restent dans la colonne des filtres', async ({page}) => {
		await page.goto('/all-products');
		await page.waitForLoadState('networkidle');
		const track = page.locator('#price-slider-track');
		test.skip((await track.count()) === 0, 'pas de filtre de prix sur cette boutique');
		await ouvrirLesFiltres(page);
		const colonne = await page.locator('#product-filters').boundingBox();
		for (const poignee of ['#price-slider-min', '#price-slider-max']) {
			const boite = await page.locator(poignee).boundingBox();
			expect(boite.x, `${poignee} ne sort pas à gauche`).toBeGreaterThanOrEqual(colonne.x - 1);
			expect(boite.x + boite.width, `${poignee} ne sort pas à droite`).toBeLessThanOrEqual(colonne.x + colonne.width + 1);
		}
	});

	//// The price slider: a drag moves the handle, rewrites the input and filters the
	//// listing; the handles stay inside the sidebar; a second drag after a filter still
	//// obeys (the handlers used to stack up on every filter change).
	test('le sélecteur de prix se traîne, reste dans la colonne et survit à un filtrage', async ({page}, testInfo) => {
		//// A drag of the mouse is not a finger: the handles listen to touch events on a phone,
		//// which Playwright's mouse never sends. The containment is checked on a phone by the
		//// test below; the drag, on a wide screen.
		test.skip(Boolean(testInfo.project.use && testInfo.project.use.hasTouch), 'le glisser à la souris ne simule pas le doigt');
		await page.goto('/all-products');
		await page.waitForLoadState('networkidle');
		const track = page.locator('#price-slider-track');
		test.skip((await track.count()) === 0, 'pas de filtre de prix sur cette boutique');
		await ouvrirLesFiltres(page);
		const colonne = await page.locator('#product-filters').boundingBox();
		const max = page.locator('#price-slider-max');
		const boiteMax = await max.boundingBox();
		expect(boiteMax.x + boiteMax.width, 'la poignée droite tient dans la colonne').toBeLessThanOrEqual(colonne.x + colonne.width + 1);
		const piste = await track.boundingBox();
		const avant = Number(await page.locator('#price-max').inputValue());
		await max.hover();
		await page.mouse.down();
		await page.mouse.move(piste.x + piste.width * 0.5, piste.y + piste.height / 2, {steps: 8});
		await page.mouse.up();
		await page.waitForLoadState('networkidle');
		await ouvrirLesFiltres(page);
		const apres = Number(await page.locator('#price-max').inputValue());
		expect(apres, 'le maximum a baissé').toBeLessThan(avant);
		expect(page.url()).toContain('price_range');
		//// A second drag, after the listing re-rendered: one handler, one movement.
		const piste2 = await track.boundingBox();
		const max2 = page.locator('#price-slider-max');
		await max2.hover();
		await page.mouse.down();
		await page.mouse.move(piste2.x + piste2.width * 0.9, piste2.y + piste2.height / 2, {steps: 8});
		await page.mouse.up();
		await page.waitForLoadState('networkidle');
		const encore = Number(await page.locator('#price-max').inputValue());
		expect(encore, 'le maximum est remonté').toBeGreaterThan(apres);
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
		await expect(premier).toHaveJSProperty('open', true);
		//// Pin the fold by index: a `:not([open])` locator stops matching the fold the
		//// moment it opens and silently moves on to the next closed one.
		const fermes = await replis.evaluateAll((els) => els.map((e, i) => (e.open ? -1 : i)).filter((i) => i >= 0));
		if (fermes.length) {
			const ferme = replis.nth(fermes[0]);
			await ferme.locator('summary').click();
			await expect(ferme).toHaveJSProperty('open', true);
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
