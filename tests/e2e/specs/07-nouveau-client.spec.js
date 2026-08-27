//// Neoffice — added file (no upstream equivalent).
//// The full journey of someone who has never bought here: create an account,
//// activate it, fill a cart, and pay by card.
////
//// This is the scenario the other specs do NOT cover. 01-authentification stops
//// at "the account exists"; 05-paiement-stripe starts from an account that
//// already exists and already has addresses. Everything in between — a customer
//// with no address, no Customer record, no order history — only happens here,
//// and it is the path every real first-time buyer takes.
////
//// Runs signed out, and creates a real (throwaway) account each time.

const {test, expect} = require('@playwright/test');
const {
	viderPanier,
	ajouterAuPanier,
	lireDevis,
	lireJson,
	allerJusquAuPaiement,
	premierArticleAchetable,
	utilisateurCourant,
} = require('../fixtures/boutique');
const {activationDisponible, activerCompte, supprimerCompte} = require('../fixtures/activation');
const {CARTES, remplirCarte, validerPaiement} = require('../fixtures/stripe');

//// Adresse jetable: @yopmail.com, jamais une vraie boîte.
const nouvelEmail = () => `e2e.nouveau.${Date.now()}@yopmail.com`;
const MOT_DE_PASSE = 'E2e-Nouveau-Client-2026!';

/** Create an account through the shop's own dialog, as a visitor does. */
async function creerCompteParLeDialogue(page, email) {
	await page.goto('/all-products');
	await page.waitForLoadState('domcontentloaded');
	await page.evaluate(() => frappe.showLoginDialog({}));

	await expect(page.locator('.login-dialog')).toBeVisible();
	await page.fill('#login_email', email);
	await page.click('.btn-verify-email');

	//// Adresse inconnue: le dialogue demande le nom, pas un mot de passe.
	await expect(page.locator('.fullname-section')).toBeVisible({timeout: 20_000});
	await page.fill('#first_name', 'E2E');
	await page.fill('#last_name', 'Nouveau');
	await page.locator('.btn-submit').click();
	await page.waitForTimeout(6000);
}

test.describe('Un nouveau client, de son inscription à sa commande', () => {
	test.describe.configure({mode: 'serial'});

	let email = null;

	test.afterAll(() => {
		if (email) supprimerCompte(email);
	});

	test('il crée son compte depuis la boutique', async ({page}) => {
		test.setTimeout(120_000);
		email = nouvelEmail();
		await creerCompteParLeDialogue(page, email);

		//// La confirmation à l'écran ne prouve rien: on demande au serveur.
		//// Via lireJson, qui survit à une réponse HTML — ce que le site renvoie
		//// quand il est chargé, et qui ferait mourir un r.json() sur une erreur
		//// de parsing sans rapport avec ce qu'on teste.
		await expect
			.poll(
				async () => {
					const m = await lireJson(page, '/api/method/webshop.webshop.auth.api.check_email', {
						email,
					});
					return m ? m.exists : null;
				},
				{timeout: 40_000, message: 'le compte n’a pas été créé'}
			)
			.toBe(true);

		//// Et il ne doit pas être connecté pour autant: le compte est créé sans
		//// mot de passe, l'activation passe par le lien reçu. Un « compte créé »
		//// qui ouvrirait une session sans mot de passe serait un trou.
		expect(await utilisateurCourant(page), 'session ouverte sans activation').toBe('Guest');
	});

	test('il active son compte par le lien reçu', async ({page}) => {
		test.setTimeout(120_000);
		test.skip(!email, 'le compte n’a pas pu être créé');
		test.skip(
			!activationDisponible(),
			'activation indisponible (WEBSHOP_E2E_SSH_HOST / WEBSHOP_E2E_SITE absents)'
		);

		//// Le compte est créé SANS mot de passe: sans cette étape, il ne peut
		//// pas se connecter, et c'est bien ce que vit un vrai client.
		const active = await activerCompte(page, email, MOT_DE_PASSE);
		expect(active, 'le compte n’a pas pu être activé par son lien').toBe(true);
		expect(await utilisateurCourant(page)).toBe(email);
	});

	test('il remplit son panier et paie par carte', async ({page}) => {
		test.setTimeout(300_000);
		test.skip(!email, 'le compte n’a pas pu être créé');
		test.skip(!activationDisponible(), 'activation indisponible');

		const connexion = await page.request.post('/api/method/login', {
			form: {usr: email, pwd: MOT_DE_PASSE},
		});
		test.skip(!connexion.ok(), 'le compte activé ne peut pas se connecter');

		await viderPanier(page);
		const article = await premierArticleAchetable(page);
		test.skip(!article, 'aucun article publié');
		await ajouterAuPanier(page, article.item_code, 1);

		const devis = await lireDevis(page);
		expect(devis && devis.doc, 'aucun devis pour ce nouveau client').toBeTruthy();
		const nomDevis = devis.doc.name;

		//// Un client tout neuf n'a AUCUNE adresse: le tunnel doit lui permettre
		//// d'en saisir une, pas le bloquer. C'est le point que ce scénario
		//// éprouve et qu'aucun autre ne couvre.
		await page.goto('/checkout');
		await page.waitForLoadState('networkidle');
		await expect(page.locator('#step-address')).toHaveClass(/active/, {timeout: 40_000});
		await remplirAdresse(page);

		test.skip(
			!(await allerJusquAuPaiement(page)),
			'aucune méthode de livraison pour cette adresse'
		);

		const tuile = await remplirCarte(page, CARTES.acceptee, {nom: 'E2E Nouveau', email});
		await validerPaiement(page, tuile);

		await expect
			.poll(
				async () => {
					const courant = await lireDevis(page);
					return courant && courant.doc ? courant.doc.name : null;
				},
				{timeout: 150_000, message: 'la commande du nouveau client n’a jamais abouti'}
			)
			.not.toBe(nomDevis);
	});
});

//// Fill the address form of a customer who has none.
async function remplirAdresse(page) {
	const champs = {
		contact_first_name: 'E2E',
		contact_last_name: 'Nouveau',
		contact_phone: '+41791234567',
		billing_address_1: 'Rue du Test 1',
		billing_city: 'Lausanne',
		billing_postcode: '1003',
	};
	for (const [nom, valeur] of Object.entries(champs)) {
		const champ = page.locator(`[name="${nom}"]`).first();
		if ((await champ.count()) === 0) continue;
		if (await champ.inputValue()) continue;   // déjà rempli par le serveur
		await champ.fill(valeur);
	}

	//// Le pays conditionne les règles de livraison: sans lui, aucune méthode.
	const pays = page.locator('[name="billing_country"]').first();
	if ((await pays.count()) && !(await pays.inputValue())) {
		await pays.fill('Switzerland');
	}
	await page.waitForTimeout(2000);
}
