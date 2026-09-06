//// Neoffice — added file (no upstream equivalent).
//// The B2B checkout, which is a different page with different rules.
////
//// Unlike the B2C tunnel, /checkout_b2b is a SINGLE page — company, address,
//// shipping, "Place Order" — with no payment step at all: a B2B customer
//// orders now and is billed according to their account terms. So the assertion
//// that matters is not "was it paid", it is "was an order created, and could
//// only the right people create it".
////
//// Runs under the `b2b` project, whose session belongs to a customer whose
//// group is listed in Webshop Settings → B2B Customer Group.

const {test, expect} = require('@playwright/test');
const {
	viderPanier,
	ajouterAuPanier,
	lireDevis,
	lireJson,
	choisirLivraison,
	premierArticleAchetable,
	utilisateurCourant,
} = require('../fixtures/boutique');

const ROUTE_B2B = '/checkout_b2b';

/** Is this session actually recognised as a B2B customer? */
async function estClientB2B(page) {
	const panier = await lireJson(
		page,
		'/api/method/webshop.webshop.shopping_cart.cart.get_cart_quotation'
	);
	return !!(panier && panier.is_b2b_customer);
}

async function panierGarni(page) {
	const devis = await lireDevis(page);
	if (devis && devis.doc && (devis.doc.items || []).length) return true;
	const article = await premierArticleAchetable(page);
	if (!article) return false;
	await ajouterAuPanier(page, article.item_code, 1);
	const apres = await lireDevis(page);
	return !!(apres && apres.doc && (apres.doc.items || []).length);
}

test.describe('Reconnaissance du client B2B', () => {
	test('la session de test est bien un client B2B', async ({page}) => {
		await page.goto('/');
		const utilisateur = await utilisateurCourant(page);
		test.skip(utilisateur === 'Guest', 'aucune session B2B (WEBSHOP_E2E_B2B_USER absent ?)');
		expect(await estClientB2B(page), `${utilisateur} n’est pas reconnu comme client B2B`).toBe(true);
	});

	//// The bug this test locks in: B2B recognition looked up Customer by its
	//// LABEL (customer_name) instead of its identifier. The two coincide as
	//// long as a customer is named after themselves; as soon as a homonym
	//// forces a series ("Acme Corp - 2"), the lookup found nothing and the
	//// customer was sent back to the B2C tunnel without a word.
	test('un client dont le nom diffère du libellé reste reconnu', async ({page}) => {
		await page.goto('/');
		test.skip((await utilisateurCourant(page)) === 'Guest', 'aucune session B2B');

		const panier = await lireJson(
			page,
			'/api/method/webshop.webshop.shopping_cart.cart.get_cart_quotation'
		);
		const info = panier && panier.customer_info;
		expect(info, 'le client n’a pas pu être résolu').toBeTruthy();

		const devis = panier && panier.doc;
		if (devis && devis.party_name && devis.customer_name && devis.party_name !== devis.customer_name) {
			//// This is precisely the faulty case: verify that it passes.
			expect(info.name, 'le client résolu n’est pas celui du devis').toBe(devis.party_name);
		}
		expect(panier.is_b2b_customer).toBe(true);
	});
});

test.describe('Accès au tunnel B2B', () => {
	test('un client B2B atteint la page', async ({page}) => {
		test.skip(!(await panierGarni(page)), 'impossible de garnir le panier');
		await page.goto(ROUTE_B2B);
		await expect(page.locator('#b2b-checkout')).toBeVisible({timeout: 30_000});
	});

	test('le titre de page ne reprend pas le nom d’une étape', async ({page}) => {
		test.skip(!(await panierGarni(page)), 'impossible de garnir le panier');
		await page.goto(ROUTE_B2B);
		const titre = (await page.locator('h1').first().textContent()).trim();
		expect(titre.toLowerCase()).not.toBe('paiement');
	});

	//// This test verifies it is the RIGHT company, not merely that there is one.
	////
	//// The weak version — "the page isn't empty" — passed green while the
	//// page displayed « Société : E2E Nouveau » on Test B2B Webshop's
	//// quotation: one company's name shown to another, on the screen where
	//// they confirm an order billed to their own account. A test that asserts
	//// nothing protects nothing.
	test('la société affichée est bien celle du client', async ({page}) => {
		test.skip(!(await panierGarni(page)), 'impossible de garnir le panier');

		const panier = await lireJson(
			page,
			'/api/method/webshop.webshop.shopping_cart.cart.get_cart_quotation'
		);
		const attendue = panier && panier.doc ? panier.doc.customer_name : null;
		test.skip(!attendue, 'le devis n’a pas de client');

		await page.goto(ROUTE_B2B);
		await expect(page.locator('#b2b-checkout')).toBeVisible({timeout: 30_000});
		await expect(
			page.locator('#b2b-checkout'),
			'la page B2B annonce une autre société que celle du devis'
		).toContainText(attendue);
	});

	test('un panier vide ne mène pas au tunnel B2B', async ({page}) => {
		await viderPanier(page);
		await page.goto(ROUTE_B2B);
		//// Placing an order with an empty cart makes no sense: the page must redirect.
		await expect
			.poll(() => page.url(), {timeout: 30_000, message: 'reste sur le tunnel B2B avec un panier vide'})
			.not.toContain('checkout_b2b');
	});
});

test.describe('Commande B2B', () => {
	test.describe.configure({mode: 'serial'});

	test('le bouton de commande est verrouillé tant que la livraison manque', async ({page}) => {
		test.skip(!(await panierGarni(page)), 'impossible de garnir le panier');
		await page.goto(ROUTE_B2B);
		await expect(page.locator('#b2b-checkout')).toBeVisible({timeout: 30_000});

		const bouton = page.locator('.btn-place-order');
		await expect(bouton).toHaveCount(1);
		//// Placing an order without a shipping method produces an incomplete
		//// order that someone will have to fix by hand.
		await expect(bouton, 'commande possible sans mode de livraison').toBeDisabled();
	});

	test('choisir une livraison déverrouille la commande', async ({page}) => {
		test.setTimeout(150_000);
		test.skip(!(await panierGarni(page)), 'impossible de garnir le panier');
		await page.goto(ROUTE_B2B);
		await expect(page.locator('#b2b-checkout')).toBeVisible({timeout: 30_000});

		const options = page.locator('#shipping-methods-container input[type=radio]');
		await expect
			.poll(() => options.count(), {timeout: 40_000, message: 'aucune méthode de livraison proposée'})
			.toBeGreaterThan(0);

		await choisirLivraisonB2B(page);
		await expect(page.locator('.btn-place-order')).toBeEnabled({timeout: 30_000});
	});

	test('passer commande crée une commande et vide le panier', async ({page}) => {
		test.setTimeout(180_000);
		test.skip(!(await panierGarni(page)), 'impossible de garnir le panier');

		const avant = await lireDevis(page);
		const nomDevis = avant && avant.doc ? avant.doc.name : null;
		test.skip(!nomDevis, 'aucun devis courant');

		await page.goto(ROUTE_B2B);
		await expect(page.locator('#b2b-checkout')).toBeVisible({timeout: 30_000});

		const options = page.locator('#shipping-methods-container input[type=radio]');
		await expect.poll(() => options.count(), {timeout: 40_000}).toBeGreaterThan(0);
		await choisirLivraisonB2B(page);

		const bouton = page.locator('.btn-place-order');
		await expect(bouton).toBeEnabled({timeout: 30_000});
		await bouton.click();

		//// The proof is server-side: the original quotation must no longer be
		//// the current cart. An on-screen message proves nothing.
		await expect
			.poll(
				async () => {
					const devis = await lireDevis(page);
					return devis && devis.doc ? devis.doc.name : null;
				},
				{timeout: 120_000, message: 'le devis n’a jamais été transformé en commande'}
			)
			.not.toBe(nomDevis);
	});
});

//// The B2B shipping radios sit in their own container and, like the B2C ones,
//// may be hidden behind a styled label.
async function choisirLivraisonB2B(page) {
	const options = page.locator('#shipping-methods-container input[type=radio]');
	if ((await options.count()) === 0) return;
	if (await options.first().isChecked()) return;

	const id = await options.first().getAttribute('id');
	const etiquette = id ? page.locator(`label[for="${id.replace(/"/g, '\\"')}"]`) : null;
	if (etiquette && (await etiquette.count()) && (await etiquette.first().isVisible())) {
		await etiquette.first().click();
	} else {
		await options.first().check({force: true});
		await options.first().dispatchEvent('change');
	}
	await page.waitForTimeout(4000);
}

test.describe('Cloisonnement du tunnel B2B', () => {
	//// An ordinary customer must not be able to order under B2B terms
	//// (deferred payment, reseller pricing). This test runs under the B2C
	//// session, not the B2B one.
	test('un client non-B2B est refusé', async ({browser}) => {
		//// Hard-coded path, NOT require('../global-setup'): the config already
		//// imports that module, and Playwright then refuses to load the spec
		//// (« test.describe() called in a file imported by the configuration »),
		//// which makes the ENTIRE suite fail to load.
		const contexte = await browser.newContext({
			storageState: require('path').join(__dirname, '..', '.auth', 'session.json'),
		});
		const page = await contexte.newPage();
		try {
			await page.goto('/');
			test.skip((await utilisateurCourant(page)) === 'Guest', 'session B2C indisponible');
			test.skip(await estClientB2B(page), 'le compte B2C est aussi B2B sur ce site');

			await page.goto(ROUTE_B2B);
			await expect
				.poll(() => page.url(), {timeout: 30_000, message: 'un client non-B2B atteint le tunnel B2B'})
				.not.toContain('checkout_b2b');
		} finally {
			await contexte.close();
		}
	});

	test('un visiteur anonyme est renvoyé à la connexion', async ({browser}) => {
		const contexte = await browser.newContext();
		const page = await contexte.newPage();
		try {
			await page.goto(ROUTE_B2B);
			await page.waitForLoadState('domcontentloaded');

			//// What matters is what the guest SEES, not the displayed URL.
			//// The URL may remain the one requested depending on how the
			//// redirect is served; the tunnel itself must never be shown.
			await expect(
				page.locator('#b2b-checkout'),
				'un invité voit le tunnel B2B'
			).toHaveCount(0);

			//// Never to /app: a portal customer has no desk access, sending them
			//// there is a dead end.
			expect(page.url(), 'un invité est envoyé vers le desk').not.toContain('/app');
		} finally {
			await contexte.close();
		}
	});
});
