//// Neoffice — added file (no upstream equivalent).
//// The cart, including the multi-warehouse behaviour added in 2026-08: the same
//// item taken from two different sources must stay two separate lines.

const {test, expect} = require('@playwright/test');
const {
	connecter,
	viderPanier,
	ajouterAuPanier,
	lireDevis,
	premierArticleAchetable,
	articlesDuCatalogue,
} = require('../fixtures/boutique');

//// Find a product the shop itself offers from two sources.
////
//// Neither the doctype nor a whitelisted helper is reachable from a customer
//// session (Website Users get a 403 on frappe.client.get_list, and rightly so),
//// so this reads the source selector the product page actually draws — the same
//// thing the customer sees and clicks.
//// Cached for the whole file: the search costs one page load per product, and
//// five specs need the same answer. Without this the multi-warehouse block
//// spent minutes re-walking the catalogue, and the earlier 8-product limit
//// stopped before reaching the only item that has two sources — so every one of
//// those specs was skipped, silently, and the run still looked green.
let _multiSource;

async function articleMultiSource(page) {
	if (_multiSource !== undefined) return _multiSource;

	//// Une route peut être désignée dans ~/.config/webshop-e2e.env
	//// (WEBSHOP_E2E_MULTISOURCE_ROUTE). La détection automatique ci-dessous ne
	//// voit que la première page du catalogue: sur un site où l'article
	//// multi-sources est plus loin, tous ces tests se taisaient.
	const designee = process.env.WEBSHOP_E2E_MULTISOURCE_ROUTE;
	if (designee) {
		const trouve = await sourcesDeLaFiche(page, designee.replace(/^\//, ''));
		if (trouve) {
			_multiSource = trouve;
			return _multiSource;
		}
		throw new Error(
			`WEBSHOP_E2E_MULTISOURCE_ROUTE pointe /${designee}, qui n’offre pas deux sources.`
		);
	}

	_multiSource = null;
	for (const route of await articlesDuCatalogue(page, 25)) {
		const trouve = await sourcesDeLaFiche(page, route);
		if (trouve) {
			_multiSource = trouve;
			break;
		}
	}
	return _multiSource;
}

/** Read a product page's source selector; null unless it offers two or more. */
async function sourcesDeLaFiche(page, route) {
	await page.goto('/' + route);
	await page.waitForLoadState('domcontentloaded');
	//// The product's own code, not the first data-item-code on the page: the
	//// theme's cart drawer sits in the header and its lines carry that
	//// attribute too, so a leftover in the cart used to be taken for the
	//// product under test.
	const lu = await page.evaluate(() => ({
		item_code:
			document
				.querySelector('.product-page-content .btn-add-to-cart[data-item-code], .product-page-content [data-item-code]')
				?.getAttribute('data-item-code') || null,
		entrepots: [
			...new Set(
				[...document.querySelectorAll('input[name="webshop-warehouse-source"]')]
					.map((r) => r.value)
					.filter(Boolean)
			),
		],
	}));
	return lu.item_code && lu.entrepots.length >= 2 ? {route, ...lu} : null;
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
		expect(await viderPanier(page), 'le panier n’a pas pu être vidé').toBe(true);
		await page.goto('/cart');
		await page.waitForLoadState('networkidle');
		//// Soit un message d'état vide, soit aucune ligne: jamais un écran muet
		//// avec des lignes fantômes.
		const lignes = await page.locator('.cart-table [data-item-code]').count();
		expect(lignes).toBe(0);
	});

	test('un article ajouté apparaît dans le panier', async ({page}) => {
		expect(await viderPanier(page), 'le panier n’a pas pu être vidé').toBe(true);
		const article = await premierArticleAchetable(page);
		test.skip(!article, 'aucun article publié');

		await ajouterAuPanier(page, article.item_code, 2);
		await page.goto('/cart');
		await page.waitForLoadState('networkidle');

		//// Le thème rend le panier DEUX fois: le tableau de la page, et un tiroir
		//// latéral (#builder-cart-drawer) qui porte les mêmes data-item-code.
		//// Cibler sans distinguer attrape le tiroir, hors écran, et le test
		//// échoue sur « element is not visible » en accusant la page.
		await expect(page.locator(`.cart-table [data-item-code="${article.item_code}"]`).first()).toBeVisible();
	});

	test('augmenter la quantité met à jour le devis', async ({page}) => {
		expect(await viderPanier(page), 'le panier n’a pas pu être vidé').toBe(true);
		const article = await premierArticleAchetable(page);
		test.skip(!article, 'aucun article publié');

		await ajouterAuPanier(page, article.item_code, 1);
		await page.goto('/cart');
		await page.waitForLoadState('networkidle');

		//// Sur la page, la quantité est un champ (le tiroir, lui, a des boutons).
		const champ = page.locator('.cart-table input.cart-qty').first();
		test.skip((await champ.count()) === 0, 'pas de contrôle de quantité sur ce thème');

		await champ.fill('2');
		await champ.press('Enter');

		await expect
			.poll(async () => quantiteTotale(page), {timeout: 25_000, message: 'la quantité n’a pas suivi'})
			.toBe(2);
	});

	//// Le défaut que ce test verrouille: vider le panier SUPPRIME le devis, et
	//// cette suppression est refusée dès qu'une demande de paiement y est liée
	//// (LinkExistsError). Après une carte refusée — cas banal — le client ne
	//// pouvait plus retirer son dernier article: erreur technique, panier bloqué
	//// pour de bon. Les demandes jamais honorées sont désormais annulées, celles
	//// qui ont abouti restent intactes.
	test('un panier se vide même après un paiement refusé', async ({page}) => {
		test.setTimeout(120_000);
		expect(await viderPanier(page), 'le panier n’a pas pu être vidé').toBe(true);

		const article = await premierArticleAchetable(page);
		test.skip(!article, 'aucun article publié');
		await ajouterAuPanier(page, article.item_code, 1);

		//// On ne simule pas le refus ici (il faudrait une vraie tentative
		//// Stripe): 05-paiement-stripe en laisse derrière lui, et ce test
		//// s'exécute après. Ce qui compte est que le vidage aboutisse quel que
		//// soit ce que le devis traîne.
		expect(await viderPanier(page), 'le panier reste bloqué').toBe(true);
		const devis = await lireDevis(page);
		expect((devis && devis.doc && devis.doc.items) || []).toHaveLength(0);
	});

	test('retirer un article vide la ligne', async ({page}) => {
		expect(await viderPanier(page), 'le panier n’a pas pu être vidé').toBe(true);
		const article = await premierArticleAchetable(page);
		test.skip(!article, 'aucun article publié');

		await ajouterAuPanier(page, article.item_code, 1);
		expect(await quantiteTotale(page)).toBe(1);

		await ajouterAuPanier(page, article.item_code, 0);
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
			await ajouterAuPanier(page, article.item_code, 1, entrepot);
		}

		const devis = await lireDevis(page);
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

		expect(await viderPanier(page), 'le panier n’a pas pu être vidé').toBe(true);

		const entrepot = article.entrepots[0];
		for (let i = 0; i < 2; i += 1) {
			await ajouterAuPanier(page, article.item_code, i + 1, entrepot);
		}

		//// Filtré sur l'ENTREPÔT autant que sur l'article: sans cela, une ligne
		//// laissée par l'autre source (test précédent, vidage incomplet) compte
		//// comme un doublon et le test accuse la fusion de ne pas se faire.
		const devis = await lireDevis(page);
		const lignes = ((devis && devis.doc && devis.doc.items) || []).filter(
			(l) => l.item_code === article.item_code && l.warehouse === entrepot
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
		await ajouterAuPanier(page, article.item_code, 1, article.entrepots[0]);

		await page.goto('/cart');
		await page.waitForLoadState('networkidle');
		//// Le client doit voir d'où part sa marchandise, sinon deux lignes
		//// identiques au même prix sont incompréhensibles.
		const ligne = page.locator(`.cart-table [data-item-code="${article.item_code}"]`).first();
		await expect(ligne).toBeVisible();
		expect(
			await page.locator('.cart-table [data-warehouse]').count(),
			'aucune source affichée sur les lignes'
		).toBeGreaterThan(0);
	});
});

/** Total quantity currently in the cart, straight from the server. */
async function quantiteTotale(page) {
	const devis = await lireDevis(page);
	const lignes = (devis && devis.doc && devis.doc.items) || [];
	return lignes.reduce((somme, l) => somme + (l.qty || 0), 0);
}
