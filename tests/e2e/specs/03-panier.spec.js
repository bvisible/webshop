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

	//// A route can be designated in ~/.config/webshop-e2e.env
	//// (WEBSHOP_E2E_MULTISOURCE_ROUTE). The automatic detection below only
	//// sees the first page of the catalogue: on a site where the
	//// multi-source item sits further down, all these tests went silent.
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
			(
				document.querySelector('.product-page-content .btn-add-to-cart[data-item-code]') ||
				document.querySelector('.product-page-content [data-item-code]')
			)?.getAttribute('data-item-code') || null,
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
		//// Either an empty-state message, or no line at all: never a silent screen
		//// with ghost lines.
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

		//// The theme renders the cart TWICE: the page's table, and a side drawer
		//// (#builder-cart-drawer) carrying the same data-item-code values.
		//// Targeting without distinguishing grabs the drawer, off-screen, and the
		//// test fails on « element is not visible », blaming the page.
		await expect(page.locator(`.cart-table [data-item-code="${article.item_code}"]`).first()).toBeVisible();
	});

	test('augmenter la quantité met à jour le devis', async ({page}) => {
		expect(await viderPanier(page), 'le panier n’a pas pu être vidé').toBe(true);
		const article = await premierArticleAchetable(page);
		test.skip(!article, 'aucun article publié');

		await ajouterAuPanier(page, article.item_code, 1);
		await page.goto('/cart');
		await page.waitForLoadState('networkidle');

		//// On the page, the quantity is a field (the drawer, on the other hand, has buttons).
		const champ = page.locator('.cart-table input.cart-qty').first();
		test.skip((await champ.count()) === 0, 'pas de contrôle de quantité sur ce thème');

		await champ.fill('2');
		await champ.press('Enter');

		await expect
			.poll(async () => quantiteTotale(page), {timeout: 25_000, message: 'la quantité n’a pas suivi'})
			.toBe(2);
	});

	//// The defect this test locks in: emptying the cart DELETES the quotation,
	//// and that deletion is refused as soon as a payment request is linked to
	//// it (LinkExistsError). After a declined card — a mundane case — the
	//// customer could no longer remove their last item: a technical error,
	//// cart stuck for good. Payment requests that were never honored are now
	//// cancelled, while ones that succeeded remain intact.
	test('un panier se vide même après un paiement refusé', async ({page}) => {
		test.setTimeout(120_000);
		expect(await viderPanier(page), 'le panier n’a pas pu être vidé').toBe(true);

		const article = await premierArticleAchetable(page);
		test.skip(!article, 'aucun article publié');
		await ajouterAuPanier(page, article.item_code, 1);

		//// The decline isn't simulated here (that would need a real Stripe
		//// attempt): 05-paiement-stripe leaves one behind, and this test
		//// runs after it. What matters is that emptying succeeds no matter
		//// what the quotation is carrying.
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

	//// The heart of the feature: the same item taken from two different
	//// sources is NOT the same item from the customer's point of view
	//// (different lead times), so it must stay two lines and never merge.
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

		//// Filtered on the WAREHOUSE as much as on the item: without this, a line
		//// left behind by the other source (previous test, incomplete emptying)
		//// counts as a duplicate and the test wrongly blames the merge for not happening.
		const devis = await lireDevis(page);
		const lignes = ((devis && devis.doc && devis.doc.items) || []).filter(
			(l) => l.item_code === article.item_code && l.warehouse === entrepot
		);
		expect(lignes.length, 'une seconde ligne a été créée pour la même source').toBe(1);
		expect(lignes[0].qty).toBe(2);
	});

	//// The customer must be able to choose their source BEFORE adding to cart,
	//// with each one's stock in plain sight.
	test('la fiche produit propose les sources avec leur stock', async ({page}) => {
		const article = await articleMultiSource(page);
		test.skip(!article, 'aucun article multi-sources sur ce site');

		await page.goto('/' + article.route);
		await page.waitForLoadState('networkidle');

		const options = page.locator('.webshop-source-option');
		expect(await options.count(), 'le sélecteur de source a disparu').toBeGreaterThanOrEqual(2);
		await expect(options.first()).toBeVisible();
		//// A source without its stock does not allow an informed choice: that is
		//// the whole point of displaying the sources.
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
		//// The customer must see where their goods ship from, otherwise two
		//// identical lines at the same price make no sense.
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
