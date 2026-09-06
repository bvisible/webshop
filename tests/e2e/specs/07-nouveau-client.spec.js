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
const {
	activationDisponible,
	activerCompte,
	raisonEchecActivation,
	supprimerCompte,
} = require('../fixtures/activation');
const {CARTES, remplirCarte, validerPaiement} = require('../fixtures/stripe');

//// Throwaway address: @yopmail.com, never a real inbox.
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

	//// Unknown address: the dialog asks for the name, not a password.
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

		//// The on-screen confirmation proves nothing: ask the server instead.
		//// Via lireJson, which survives an HTML response — what the site returns
		//// when it's under load, and which would kill an r.json() call with a
		//// parsing error unrelated to what is being tested.
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

		//// And yet they must not be signed in: the account is created without a
		//// password, activation goes through the link received. An "account
		//// created" that opened a session without a password would be a hole.
		expect(await utilisateurCourant(page), 'session ouverte sans activation').toBe('Guest');
	});

	test('il active son compte par le lien reçu', async ({page}) => {
		test.setTimeout(120_000);
		test.skip(!email, 'le compte n’a pas pu être créé');
		test.skip(
			!activationDisponible(),
			'activation indisponible (WEBSHOP_E2E_SSH_HOST / WEBSHOP_E2E_SITE absents)'
		);

		//// The account is created WITHOUT a password: without this step, it
		//// cannot sign in, and that is exactly what a real customer experiences.
		const active = await activerCompte(page, email, MOT_DE_PASSE);
		expect(active, `activation impossible : ${raisonEchecActivation()}`).toBe(true);
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

		//// A brand-new customer has NO address at all: the tunnel must let them
		//// enter one, not block them. That is the point this scenario tests,
		//// and no other one covers it.
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
////
//// Waits for the form before touching it: the address step is rendered by
//// JavaScript and, measured on this site, is still empty six seconds after the
//// page reports "networkidle". Reading it too early shows zero fields and looks
//// exactly like a checkout that refuses to serve a new customer.
////
//// Then fills every REQUIRED field left empty, rather than a hard-coded list:
//// the form differs by site (company, VAT number, house number…), and a single
//// missing required field silently blocks the step with no message.
async function remplirAdresse(page) {
	await expect
		.poll(() => page.locator('#step-address input:visible').count(), {
			timeout: 40_000,
			message: 'le formulaire d’adresse ne s’est jamais affiché',
		})
		.toBeGreaterThan(3);

	const valeurs = {
		first_name: 'E2E',
		last_name: 'Nouveau',
		email: 'ne-pas-repondre@yopmail.com',
		phone: '+41791234567',
		address_1: 'Rue du Test 1',
		address_2: '',
		house_number: '1',
		city: 'Lausanne',
		postcode: '1003',
		state: 'Vaud',
		country: 'Switzerland',
	};

	const aRemplir = await page.evaluate(() =>
		[...document.querySelectorAll('#step-address input, #step-address select')]
			.filter((e) => e.type !== 'hidden' && e.type !== 'checkbox' && e.offsetHeight > 0)
			.filter((e) => e.required && !e.value)
			.map((e) => e.name || e.id)
	);

	for (const nom of aRemplir) {
		const cle = Object.keys(valeurs).find((k) => nom.endsWith(k));
		if (!cle || !valeurs[cle]) continue;
		const champ = page.locator(`[name="${nom}"], #${nom}`).first();
		if ((await champ.count()) === 0) continue;
		await champ.fill(valeurs[cle]);
	}

	//// The country drives the shipping rules: without it, no method is
	//// offered and the next step becomes a dead end.
	const pays = page.locator('[name="billing_country"], #billing_country').first();
	if ((await pays.count()) && !(await pays.inputValue())) {
		await pays.fill(valeurs.country);
	}
	await page.waitForTimeout(2500);
}
