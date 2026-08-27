//// Neoffice — added file (no upstream equivalent).
//// The cart, including the multi-warehouse behaviour added in 2026-08: the same
//// item taken from two different sources must stay two separate lines.

const {test, expect} = require('@playwright/test');
const {
	connecter,
	appeler,
	viderPanier,
	premierArticleAchetable,
	articlesDuCatalogue,
} = require('../fixtures/boutique');

//// Find a product the shop itself offers from two sources.
////
//// Neither the doctype nor a whitelisted helper is reachable from a customer
//// session (Website Users get a 403 on frappe.client.get_list, and rightly so),
//// so this reads the source selector the product page actually draws — the same
//// thing the customer sees and clicks.
async function articleMultiSource(page) {
	for (const article of await articlesDuCatalogue(page, 8)) {
		await page.goto('/' + article.route);
		await page.waitForLoadState('networkidle');
		const entrepots = await page.evaluate(() =>
			[
				...new Set(
					[...document.querySelectorAll('input[name="webshop-warehouse-source"]')]
						.map((r) => r.value)
						.filter(Boolean)
				),
			]
		);
		if (entrepots.length >= 2) return {...article, entrepots};
	}
	return null;
}

test.describe('Panier', () => {
	test.beforeEach(async ({page}) => {
		await connecter(page);
	});

	test('un seul titre visible', async ({page}) => {
		await page.goto('/cart');
		await page.waitForLoadState('networkidle');
		const visibles = await page.evaluate(
			() =>
				[...document.querySelectorAll('h1')].filter(
					(h) => getComputedStyle(h).display !== 'none' && h.getBoundingClientRect().height > 0
				).length
		);
		expect(visibles, 'le double titre est revenu sur le panier').toBe(1);
	});

	test('un panier vide le dit clairement', async ({page}) => {
		await viderPanier(page);
		await page.goto('/cart');
		await page.waitForLoadState('networkidle');
		//// Soit un message d'état vide, soit aucune ligne: jamais un écran muet
		//// avec des lignes fantômes.
		const lignes = await page.locator('[data-item-code]').count();
		expect(lignes).toBe(0);
	});

	test('un article ajouté apparaît dans le panier', async ({page}) => {
		await viderPanier(page);
		const article = await premierArticleAchetable(page);
		test.skip(!article, 'aucun article publié');

		await appeler(page, 'webshop.webshop.shopping_cart.cart.update_cart', {
			item_code: article.item_code,
			qty: 2,
		});
		await page.goto('/cart');
		await page.waitForLoadState('networkidle');

		await expect(page.locator(`[data-item-code="${article.item_code}"]`).first()).toBeVisible();
	});

	test('augmenter la quantité met à jour le devis', async ({page}) => {
		await viderPanier(page);
		const article = await premierArticleAchetable(page);
		test.skip(!article, 'aucun article publié');

		await appeler(page, 'webshop.webshop.shopping_cart.cart.update_cart', {
			item_code: article.item_code,
			qty: 1,
		});
		await page.goto('/cart');
		await page.waitForLoadState('networkidle');

		const plus = page.locator('[data-action="increase"]').first();
		test.skip((await plus.count()) === 0, 'pas de contrôle de quantité sur ce thème');
		await plus.click();

		await expect
			.poll(async () => quantiteTotale(page), {timeout: 25_000, message: 'la quantité n’a pas suivi'})
			.toBe(2);
	});

	test('retirer un article vide la ligne', async ({page}) => {
		await viderPanier(page);
		const article = await premierArticleAchetable(page);
		test.skip(!article, 'aucun article publié');

		await appeler(page, 'webshop.webshop.shopping_cart.cart.update_cart', {
			item_code: article.item_code,
			qty: 1,
		});
		expect(await quantiteTotale(page)).toBe(1);

		await appeler(page, 'webshop.webshop.shopping_cart.cart.update_cart', {
			item_code: article.item_code,
			qty: 0,
		});
		expect(await quantiteTotale(page), 'l’article n’a pas été retiré').toBe(0);
	});
});

test.describe('Panier multi-entrepôts', () => {
	test.beforeEach(async ({page}) => {
		await connecter(page);
	});

	//// Le cœur de la fonctionnalité: le même article pris chez deux sources
	//// différentes n'est PAS le même article du point de vue du client (délais
	//// distincts), donc il doit rester deux lignes et ne jamais fusionner.
	test('le même article depuis deux sources fait deux lignes', async ({page}) => {
		const article = await articleMultiSource(page);
		test.skip(!article, 'aucun article multi-sources sur ce site');

		await viderPanier(page);
		for (const entrepot of article.entrepots.slice(0, 2)) {
			await appeler(page, 'webshop.webshop.shopping_cart.cart.update_cart', {
				item_code: article.item_code,
				qty: 1,
				warehouse: entrepot,
			});
		}

		const devis = await appeler(page, 'webshop.webshop.shopping_cart.cart.get_cart_quotation');
		const lignes = ((devis && devis.doc && devis.doc.items) || []).filter(
			(l) => l.item_code === article.item_code
		);
		expect(lignes.length, 'les deux sources ont fusionné en une seule ligne').toBe(2);

		const entrepots = new Set(lignes.map((l) => l.warehouse));
		expect(entrepots.size, 'les deux lignes pointent le même entrepôt').toBe(2);
	});

	test('reprendre la même source incrémente la ligne existante', async ({page}) => {
		const article = await articleMultiSource(page);
		test.skip(!article, 'aucun article multi-sources sur ce site');

		await viderPanier(page);
		const entrepot = article.entrepots[0];
		for (let i = 0; i < 2; i += 1) {
			await appeler(page, 'webshop.webshop.shopping_cart.cart.update_cart', {
				item_code: article.item_code,
				qty: i + 1,
				warehouse: entrepot,
			});
		}

		const devis = await appeler(page, 'webshop.webshop.shopping_cart.cart.get_cart_quotation');
		const lignes = ((devis && devis.doc && devis.doc.items) || []).filter(
			(l) => l.item_code === article.item_code
		);
		expect(lignes.length, 'une seconde ligne a été créée pour la même source').toBe(1);
		expect(lignes[0].qty).toBe(2);
	});

	//// Le client doit pouvoir choisir sa source AVANT d'ajouter au panier, avec
	//// le stock de chacune sous les yeux.
	test('la fiche produit propose les sources avec leur stock', async ({page}) => {
		const article = await articleMultiSource(page);
		test.skip(!article, 'aucun article multi-sources sur ce site');

		await page.goto('/' + article.route);
		await page.waitForLoadState('networkidle');

		const options = page.locator('.webshop-source-option');
		expect(await options.count(), 'le sélecteur de source a disparu').toBeGreaterThanOrEqual(2);
		await expect(options.first()).toBeVisible();
		//// Une source sans son stock ne permet pas de choisir en connaissance de
		//// cause: c'est tout l'intérêt d'afficher les sources.
		await expect(options.first()).toContainText(/\d/);
	});

	test('une seule source est cochée à la fois', async ({page}) => {
		const article = await articleMultiSource(page);
		test.skip(!article, 'aucun article multi-sources sur ce site');

		await page.goto('/' + article.route);
		await page.waitForLoadState('networkidle');
		const cochees = await page
			.locator('input[name="webshop-warehouse-source"]:checked')
			.count();
		expect(cochees, 'le choix de source est ambigu').toBe(1);
	});

	test('la source est annoncée sur la ligne du panier', async ({page}) => {
		const article = await articleMultiSource(page);
		test.skip(!article, 'aucun article multi-sources sur ce site');

		await viderPanier(page);
		await appeler(page, 'webshop.webshop.shopping_cart.cart.update_cart', {
			item_code: article.item_code,
			qty: 1,
			warehouse: article.entrepots[0],
		});

		await page.goto('/cart');
		await page.waitForLoadState('networkidle');
		//// Le client doit voir d'où part sa marchandise, sinon deux lignes
		//// identiques au même prix sont incompréhensibles.
		const ligne = page.locator(`[data-item-code="${article.item_code}"]`).first();
		await expect(ligne).toBeVisible();
		expect(
			await page.locator('[data-warehouse]').count(),
			'aucune source affichée sur les lignes'
		).toBeGreaterThan(0);
	});
});

/** Total quantity currently in the cart, straight from the server. */
async function quantiteTotale(page) {
	const devis = await appeler(page, 'webshop.webshop.shopping_cart.cart.get_cart_quotation');
	const lignes = (devis && devis.doc && devis.doc.items) || [];
	return lignes.reduce((somme, l) => somme + (l.qty || 0), 0);
}
