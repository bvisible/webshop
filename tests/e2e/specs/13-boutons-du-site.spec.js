//// Neoffice — added file (no upstream equivalent).
//// One button for the site and its shop (2026-09-13): the site chrome draws every button
//// through :where(.u-btn), and that rule is on the shop's pages too — so a reference
//// <a class="u-btn u-btn--primary"> injected into a shop page is measured exactly where
//// the shop draws. The buy button, the cart's and the checkout's buttons must match it
//// in shape (padding, radius, font) and in colour (--btn-primary and its label); the
//// shop's outline buttons must match .u-btn--outline. Skips on a site without the
//// chrome (no :where(.u-btn) rule: the reference has no padding of its own).

const {test, expect} = require('@playwright/test');
const {connecter, ajouterAuPanier, premierArticleAchetable, viderPanier} = require('../fixtures/boutique');

const FORME = ['paddingTop', 'paddingRight', 'borderRadius', 'fontSize', 'fontWeight', 'lineHeight', 'fontFamily'];
const COULEUR = ['backgroundColor', 'color'];

//// Reads the computed style of the first visible match, next to an injected reference.
async function mesurer(page, selecteur, variante = 'u-btn--primary') {
	return page.evaluate(({selecteur, variante, cles}) => {
		const ref = document.createElement('a');
		ref.className = 'u-btn ' + variante;
		ref.textContent = 'Référence';
		(document.querySelector('.page-content-wrapper') || document.body).appendChild(ref);
		const lire = (el) => {
			const cs = getComputedStyle(el);
			return Object.fromEntries(cles.map((k) => [k, k === 'fontFamily' ? cs[k].split(',')[0] : cs[k]]));
		};
		const cible = [...document.querySelectorAll(selecteur)].find((el) => el.getBoundingClientRect().height > 0);
		const out = {reference: lire(ref), bouton: cible ? lire(cible) : null, texte: cible ? cible.textContent.trim().slice(0, 40) : null};
		ref.remove();
		return out;
	}, {selecteur, variante, cles: [...FORME, ...COULEUR]});
}

function memeForme(mesure, cles = FORME) {
	const ecarts = cles.filter((k) => mesure.bouton[k] !== mesure.reference[k]).map((k) => `${k}: ${mesure.bouton[k]} ≠ ${mesure.reference[k]}`);
	expect(ecarts, `« ${mesure.texte} » diffère du bouton du site`).toEqual([]);
}

test.describe('Les boutons de la boutique sont ceux du site', () => {
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
		test.skip(!chrome, 'pas de chrome Builder sur ce site : aucun bouton de référence');
	});

	test('le bouton « ajouter au panier » a la forme et la couleur du bouton primaire du site', async ({page}) => {
		await connecter(page);
		const article = await premierArticleAchetable(page);
		test.skip(!article, 'aucun article achetable');
		await page.goto(article.route);
		await page.waitForLoadState('networkidle');
		//// A template product shows its button once every attribute is chosen.
		for (const row of await page.locator('.wsp-variants__row').all()) {
			const chip = row.locator('.wsp-variants__chip:not(.is-impossible):not(.is-unavailable)').first();
			if (await chip.count()) await chip.click();
		}
		const mesure = await mesurer(page, '.wsp-buy .btn-add-to-cart, .variant-grid-footer .btn-add-to-cart');
		test.skip(!mesure.bouton, 'pas de bouton d\'achat visible pour ce compte');
		memeForme(mesure, [...FORME, ...COULEUR]);
	});

	test('le panier et le tunnel : le bouton plein et le bouton en contour du site', async ({page}) => {
		await connecter(page);
		const article = await premierArticleAchetable(page);
		test.skip(!article, 'aucun article achetable');
		await viderPanier(page);
		await ajouterAuPanier(page, article.item_code, 1);
		await page.goto('/cart');
		await page.waitForLoadState('networkidle');
		const plein = await mesurer(page, '.btn.btn-primary:not(.btn-sm):not(.btn-page):not(.wsp-card__cta)');
		expect(plein.bouton, 'un bouton plein sur le panier').toBeTruthy();
		memeForme(plein, [...FORME, ...COULEUR]);
		const contour = await mesurer(page, '.btn.btn-outline-primary, .btn.btn-secondary', 'u-btn--outline');
		expect(contour.bouton, 'un bouton en contour sur le panier').toBeTruthy();
		memeForme(contour, [...FORME, ...COULEUR]);
		await page.goto('/checkout');
		await page.waitForLoadState('networkidle');
		const suivant = await mesurer(page, '.btn.btn-primary:not(.btn-sm):not(.btn-page)');
		test.skip(!suivant.bouton, 'pas de tunnel de commande sur ce site');
		memeForme(suivant, [...FORME, ...COULEUR]);
	});

	test('la vignette et le sélecteur de vue gardent leur propre taille', async ({page}) => {
		await page.goto('/all-products');
		await page.waitForLoadState('networkidle');
		const vignette = await mesurer(page, '.wsp-card__cta');
		test.skip(!vignette.bouton, 'aucune vignette avec bouton');
		expect(vignette.bouton.paddingTop, 'le bouton discret de la vignette').not.toBe(vignette.reference.paddingTop);
		const bascule = await mesurer(page, '#toggle-view .btn-primary');
		if (bascule.bouton) expect(bascule.bouton.paddingTop, 'le sélecteur de vue').not.toBe(bascule.reference.paddingTop);
	});
});
