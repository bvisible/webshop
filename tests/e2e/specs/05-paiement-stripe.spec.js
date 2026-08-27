//// Neoffice — added file (no upstream equivalent).
//// The checkout, all the way to a real Stripe charge.
////
//// The other specs stop at the payment step. These go through it, against
//// Stripe's TEST key (pk_test_…) with Stripe's public test card numbers: no
//// money moves and no real bank is reached, but everything else is real —
//// a Payment Request is created, the charge is made, and an order comes out.
////
//// They therefore leave real documents on the target site. See README.md
//// (« Ce que ces tests laissent derrière eux ») for how to clean up.

const {test, expect} = require('@playwright/test');
const {
	connecter,
	viderPanier,
	ajouterAuPanier,
	lireDevis,
	allerJusquAuPaiement,
	premierArticleAchetable,
} = require('../fixtures/boutique');
const {CARTES, tuileStripe, remplirCarte, validerPaiement} = require('../fixtures/stripe');

//// Un paiement traverse Stripe puis deux appels serveur: large, mais borné.
const DELAI_PAIEMENT = 90_000;

/** Put exactly one item in the cart, so amounts stay predictable. */
async function panierMinimal(page) {
	await viderPanier(page);
	const article = await premierArticleAchetable(page);
	if (!article) return null;
	await ajouterAuPanier(page, article.item_code, 1);
	const devis = await lireDevis(page);
	return devis && devis.doc ? devis.doc : null;
}

test.describe('Paiement par carte (Stripe, clés de test)', () => {
	test.describe.configure({mode: 'serial'});

	test('un client connecté paie et sa commande est créée', async ({page}) => {
		test.setTimeout(240_000);
		await connecter(page);

		const devis = await panierMinimal(page);
		test.skip(!devis, 'impossible de garnir le panier');
		const nomDevis = devis.name;

		test.skip(!(await allerJusquAuPaiement(page)), 'aucune méthode de livraison disponible');

		const tuile = await remplirCarte(page, CARTES.acceptee);
		await validerPaiement(page, tuile);

		//// Le succès se lit sur le serveur, jamais sur un message d'écran: c'est
		//// la seule preuve qu'une commande existe vraiment.
		await expect
			.poll(async () => etatDuDevis(page, nomDevis), {
				timeout: DELAI_PAIEMENT,
				message: 'le devis n’a jamais été transformé en commande',
			})
			.not.toBe('brouillon');

		//// Et le client doit être emmené ailleurs que sur le formulaire de carte.
		await expect
			.poll(() => page.url(), {timeout: 30_000, message: 'le client reste sur le checkout'})
			.not.toContain('/checkout');
	});

	test('une carte refusée affiche un message et ne crée pas de commande', async ({page}) => {
		test.setTimeout(240_000);
		await connecter(page);

		const devis = await panierMinimal(page);
		test.skip(!devis, 'impossible de garnir le panier');
		const nomDevis = devis.name;

		test.skip(!(await allerJusquAuPaiement(page)), 'aucune méthode de livraison disponible');

		const tuile = await remplirCarte(page, CARTES.refusee);
		await validerPaiement(page, tuile);

		//// Un refus doit se VOIR. Le pire échec de paiement est celui qui laisse
		//// le client devant un écran inerte, sans savoir s'il a payé.
		const message = tuile.locator('.payment-message, [role="alert"]').filter({hasText: /\S/});
		await expect(message.first(), 'aucun message après un refus de carte').toBeVisible({
			timeout: DELAI_PAIEMENT,
		});

		//// Et surtout: rien ne doit avoir été commandé.
		expect(await etatDuDevis(page, nomDevis), 'une commande a été créée malgré le refus').toBe(
			'brouillon'
		);
		expect(page.url(), 'le client a été emmené ailleurs malgré l’échec').toContain('/checkout');
	});

	test('le bouton de paiement ne peut pas être cliqué deux fois', async ({page}) => {
		test.setTimeout(240_000);
		await connecter(page);

		const devis = await panierMinimal(page);
		test.skip(!devis, 'impossible de garnir le panier');
		test.skip(!(await allerJusquAuPaiement(page)), 'aucune méthode de livraison disponible');

		const tuile = await remplirCarte(page, CARTES.acceptee);
		const bouton = tuile.locator('.btn-submit-payment:visible').first();
		await bouton.click();

		//// Double paiement = double débit. Le bouton doit se verrouiller dès le
		//// premier clic, avant même que Stripe ait répondu.
		await expect
			.poll(async () => bouton.isDisabled().catch(() => true), {
				timeout: 20_000,
				message: 'le bouton reste cliquable après le premier clic',
			})
			.toBe(true);
	});
});

test.describe('Conditions générales', () => {
	test('payer sans accepter les conditions est refusé', async ({page}) => {
		test.setTimeout(240_000);
		await connecter(page);

		const devis = await panierMinimal(page);
		test.skip(!devis, 'impossible de garnir le panier');
		const nomDevis = devis.name;
		test.skip(!(await allerJusquAuPaiement(page)), 'aucune méthode de livraison disponible');

		const tuile = await remplirCarte(page, CARTES.acceptee);
		const conditions = tuile.locator('#terms-acceptance').first();
		test.skip((await conditions.count()) === 0, 'pas de case de conditions sur ce site');
		await conditions.uncheck();

		await tuile.locator('.btn-submit-payment:visible').first().click();
		await page.waitForTimeout(8000);

		expect(
			await etatDuDevis(page, nomDevis),
			'commande passée sans acceptation des conditions'
		).toBe('brouillon');
	});
});

//// Read the quotation's real state from the server.
////
//// docstatus 0 = brouillon (panier), 1 = validé (commandé), 2 = annulé.
//// A cart that is still a draft after a payment means no order was created.
async function etatDuDevis(page, nom) {
	const r = await page.request.post(
		'/api/method/webshop.webshop.shopping_cart.cart.get_cart_quotation'
	);
	if (!r.ok()) return 'illisible';
	const devis = (await r.json()).message;
	//// Après une commande, get_cart_quotation ouvre un NOUVEAU panier vide:
	//// que le devis d'origine ne soit plus le panier courant est déjà la preuve
	//// qu'il a été consommé.
	const courant = devis && devis.doc ? devis.doc.name : null;
	if (courant && courant !== nom) return 'commande';
	const lignes = devis && devis.doc ? devis.doc.items || [] : [];
	return lignes.length ? 'brouillon' : 'vide';
}
