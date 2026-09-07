//// Neoffice — added file (the quick order, no upstream equivalent).
//// The page as three people see it: a visitor is served where the shop sells to
//// visitors and sent to sign in elsewhere, a plain customer is served, a B2B
//// customer types a reference, fills a grid at the keyboard, loses the page,
//// finds the draft again and sends it to the cart.
const {test, expect} = require('@playwright/test');
const {viderPanier, lireDevis, lireJson, utilisateurCourant} = require('../fixtures/boutique');

const ROUTE = '/quick-order';

//// Neoffice — removed estRevendeur() (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): the page no longer gates on reseller status, so the helper that read is_b2b_customer off the cart is gone.

/** A published model with variants, found through the page's own search endpoint. */
async function premierModele(page, motsCles = ['chemise', 't-shirt', 'top', 'a']) {
	for (const mot of motsCles) {
		const resultats = await lireJson(page, '/api/method/webshop.webshop.quick_order.api.search_references', {query: mot});
		const modele = (resultats || []).find((r) => r.kind === 'template');
		if (modele) return modele;
	}
	return null;
}

test.describe('Commande rapide — accès', () => {
	//// Neoffice — renamed and extended (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): a visitor is now served where the shop sells to visitors, not just sent to sign in — hence the longer timeout below for the search-to-cart round trip.
	test('un visiteur est servi là où la boutique vend aux visiteurs, envoyé se connecter ailleurs', async ({page}, testInfo) => {
		test.skip(testInfo.project.name !== 'invite', 'projet visiteur seulement');
		test.setTimeout(120_000);
		await page.goto(ROUTE);
		if (/\/login/.test(page.url())) {
			//// A shop with no guest cart, or a professional site: the visitor signs in first.
			await expect(page).toHaveURL(/\/login/);
			return;
		}
		await expect(page.locator('#wsh-qo')).toBeVisible();
		//// A visitor's cart is real too: a model, one cell, sent, found in the guest cart.
		const modele = await premierModele(page);
		test.skip(!modele, 'aucun modèle à variantes publié sur cette boutique');
		const champ = page.locator('.wsh-qo__input');
		await champ.fill(modele.name.slice(0, 12));
		await expect(page.locator('.wsh-qo-sugg', {hasText: modele.item_code}).first()).toBeVisible({timeout: 15_000});
		await champ.press('Enter');
		const grille = page.locator(`.wsh-qo-model[data-template="${modele.item_code}"]`);
		await expect(grille).toBeVisible({timeout: 15_000});
		const cases = grille.locator('.wsh-qo-cell:not(.wsh-qo-cell--none)').filter({has: page.locator('.wsh-qo-stock.has-stock, .wsh-qo-stock.is-unlimited')});
		test.skip((await cases.count()) === 0, 'aucune case servable dans la grille');
		const cellule = cases.nth(0).locator('.wsh-qo-qty');
		await cellule.focus();
		await page.keyboard.type('2');
		const code = await cellule.getAttribute('data-item');
		//// The grid's own button: this model goes to the cart on its own.
		await grille.locator('.wsh-qo-model__add').click();
		await expect(page.locator('.wsh-qo__report-ok')).toBeVisible({timeout: 30_000});
		const devis = await lireDevis(page);
		const lignes = ((devis && devis.doc && devis.doc.items) || []).reduce((acc, l) => ({...acc, [l.item_code]: l.qty}), {});
		expect(lignes[code]).toBe(2);
		await viderPanier(page);
	});

	//// Neoffice — renamed, and dropped the reseller check and its redirect to '/' (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): any signed-in customer is served directly now, not just resellers.
	test('un client ordinaire est servi, quel que soit son groupe', async ({page}, testInfo) => {
		test.skip(testInfo.project.name !== 'client', 'projet client seulement');
		await page.goto(ROUTE);
		//// Neoffice — asserts the page and access are open (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"), not that a refusal is shown.
		await expect(page.locator('#wsh-qo')).toBeVisible();
		await expect(page.locator('.wsh-qo-refusal')).toHaveCount(0);
		const r = await page.request.post('/api/method/webshop.webshop.quick_order.api.search_references', {form: {query: 'chemise'}});
		//// Neoffice — expects 200, not 403 (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): the endpoint now admits any signed-in customer.
		expect(r.status(), 'search_references a refusé un client connecté').toBe(200);
	});
});

//// Neoffice — describe block renamed from "le revendeur" (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"): these tests now cover the B2B-specific path only, general access having moved to the "accès" describe above.
test.describe('Commande rapide — le client B2B', () => {
	test.beforeEach(async ({page}, testInfo) => {
		test.skip(testInfo.project.name !== 'b2b', 'projet revendeur seulement');
		await page.goto('/');
		test.skip((await utilisateurCourant(page)) === 'Guest', 'aucune session B2B (WEBSHOP_E2E_B2B_USER absent ?)');
		//// The cart must start empty, and say so when it cannot: a leftover line would
		//// add up with the quantities typed below and blame the page.
		test.skip(!(await viderPanier(page)), 'le panier du compte B2B ne se vide pas');
		//// A draft from a previous run must not leak into this one.
		await page.goto(ROUTE);
		await page.evaluate(() => {
			Object.keys(localStorage).filter((k) => k.startsWith('webshop:quick-order:')).forEach((k) => localStorage.removeItem(k));
		});
	});

	test('la page s’ouvre sur la recherche, sans rien de plus', async ({page}) => {
		await page.goto(ROUTE);
		await expect(page.locator('#wsh-qo')).toBeVisible();
		await expect(page.locator('.wsh-qo__input')).toBeFocused();
		await expect(page.locator('.wsh-qo__send')).toBeDisabled();
	});

	test('une référence tapée ouvre la grille, les quantités se saisissent au clavier et partent au panier', async ({page}) => {
		test.setTimeout(120_000);
		const modele = await premierModele(page);
		test.skip(!modele, 'aucun modèle à variantes publié sur cette boutique');
		await page.goto(ROUTE);

		const champ = page.locator('.wsh-qo__input');
		await champ.fill(modele.name.slice(0, 12));
		const suggestion = page.locator('.wsh-qo-sugg', {hasText: modele.item_code}).first();
		await expect(suggestion).toBeVisible({timeout: 15_000});
		await champ.press('Enter');

		const grille = page.locator(`.wsh-qo-model[data-template="${modele.item_code}"]`);
		await expect(grille).toBeVisible({timeout: 15_000});
		//// Cells with stock, so the shop's rule lets them through.
		const cases = grille.locator('.wsh-qo-cell:not(.wsh-qo-cell--none)').filter({has: page.locator('.wsh-qo-stock.has-stock, .wsh-qo-stock.is-unlimited')});
		expect(await cases.count(), 'aucune case servable dans la grille').toBeGreaterThan(1);

		const premiere = cases.nth(0).locator('.wsh-qo-qty');
		const seconde = cases.nth(1).locator('.wsh-qo-qty');
		await premiere.focus();
		await page.keyboard.type('2');
		await page.keyboard.press('Enter');
		//// Enter moves to the next cell of the grid, which may be a non-servable one:
		//// type into the second servable cell explicitly, the count is what matters.
		await seconde.focus();
		await page.keyboard.type('3');
		await expect(page.locator('.wsh-qo__pieces')).toHaveText('5');
		await expect(page.locator('.wsh-qo__lines')).toHaveText('2');
		await expect(page.locator('.wsh-qo__send')).toBeEnabled();

		const codes = [await premiere.getAttribute('data-item'), await seconde.getAttribute('data-item')];

		//// The page is lost and found again: the draft survives the reload.
		await page.reload();
		await expect(page.locator('.wsh-qo__resume')).toBeVisible();
		await page.locator('.wsh-qo__resume-yes').click();
		await expect(page.locator('.wsh-qo__pieces')).toHaveText('5', {timeout: 15_000});
		await expect(page.locator(`.wsh-qo-qty[data-item="${codes[0]}"]`)).toHaveValue('2');

		await page.locator('.wsh-qo__send').click();
		await expect(page.locator('.wsh-qo__report-ok')).toBeVisible({timeout: 30_000});
		const devis = await lireDevis(page);
		const lignes = ((devis && devis.doc && devis.doc.items) || []).reduce((acc, l) => ({...acc, [l.item_code]: l.qty}), {});
		expect(lignes[codes[0]]).toBe(2);
		expect(lignes[codes[1]]).toBe(3);
		await viderPanier(page);
	});

	test('un code inconnu est dit, pas avalé', async ({page}) => {
		await page.goto(ROUTE);
		const champ = page.locator('.wsh-qo__input');
		await champ.fill('CODE-QUI-N-EXISTE-PAS-123');
		await champ.press('Enter');
		await expect(page.locator('.wsh-qo__notice')).toContainText('CODE-QUI-N-EXISTE-PAS-123');
		await expect(page.locator('.wsh-qo-model')).toHaveCount(0);
	});
});
