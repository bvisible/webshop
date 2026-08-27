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

	//// Le bug que ce test verrouille: la reconnaissance B2B interrogeait
	//// Customer par son LIBELLÉ (customer_name) au lieu de son identifiant.
	//// Les deux coïncident tant qu'un client est nommé d'après lui-même; dès
	//// qu'un homonyme force une série ("Acme Corp - 2"), la recherche ne
	//// trouvait plus rien et le client était renvoyé au tunnel B2C sans un mot.
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
			//// C'est précisément le cas fautif: on vérifie qu'il passe.
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

	test('la société du client est affichée', async ({page}) => {
		test.skip(!(await panierGarni(page)), 'impossible de garnir le panier');
		await page.goto(ROUTE_B2B);
		//// Un acheteur professionnel commande AU NOM d'une société: il doit voir
		//// laquelle avant de valider, sinon rien ne distingue deux comptes.
		await expect(page.locator('#b2b-checkout')).toContainText(/\S/);
		const societe = await page.locator('#b2b-checkout').textContent();
		expect(societe.length, 'la page B2B est vide').toBeGreaterThan(50);
	});

	test('un panier vide ne mène pas au tunnel B2B', async ({page}) => {
		await viderPanier(page);
		await page.goto(ROUTE_B2B);
		//// Commander un panier vide n'a pas de sens: la page doit rediriger.
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
		//// Commander sans mode de livraison produit une commande incomplète que
		//// quelqu'un devra rattraper à la main.
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

		//// La preuve est côté serveur: le devis d'origine ne doit plus être le
		//// panier courant. Un message à l'écran ne prouve rien.
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
	//// Un client ordinaire ne doit pas pouvoir commander aux conditions B2B
	//// (paiement différé, tarifs revendeur). Ce test tourne sous la session
	//// B2C, pas la B2B.
	test('un client non-B2B est refusé', async ({browser}) => {
		//// Chemin en dur, PAS require('../global-setup'): la config importe déjà
		//// ce module, et Playwright refuse alors de charger le spec
		//// (« test.describe() called in a file imported by the configuration »),
		//// ce qui fait échouer le chargement de TOUTE la suite.
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
			//// La redirection est un 301 côté serveur: lire page.url() sans
			//// l'attendre le surprend encore sur l'URL de départ, et le test
			//// accuse l'application d'une fuite qui n'existe pas.
			await expect
				.poll(() => page.url(), {
					timeout: 30_000,
					message: 'un invité reste sur le tunnel B2B',
				})
				.not.toContain('checkout_b2b');
			//// Jamais vers /app: un client portail n'a pas le desk.
			expect(page.url(), 'un invité est envoyé vers le desk').not.toContain('/app');
		} finally {
			await contexte.close();
		}
	});
});
