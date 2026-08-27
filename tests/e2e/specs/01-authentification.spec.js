//// Neoffice — added file (no upstream equivalent).
//// Sign-in and account creation, the two doors into the shop. Everything here
//// runs as a guest: the whole point is what an anonymous visitor can do, and
//// what they must not be able to do.

const {test, expect} = require('@playwright/test');
const {IDENTIFIANTS, utilisateurCourant} = require('../fixtures/boutique');

//// Unique per run so a re-run never collides with the account the previous run
//// created. Cleanup: bench console, see README.md.
const PREFIXE_JETABLE = 'e2e.auto.';
const emailJetable = () => `${PREFIXE_JETABLE}${Date.now()}@example.test`;

async function appelInvite(page, methode, donnees) {
	const r = await page.request.post(`/api/method/${methode}`, {form: donnees});
	return {statut: r.status(), corps: r.ok() ? await r.json() : null};
}

test.describe('Vérification d’adresse e-mail', () => {
	test('un compte existant est reconnu', async ({page}) => {
		const {corps} = await appelInvite(page, 'webshop.webshop.auth.api.check_email', {
			email: IDENTIFIANTS.utilisateur,
		});
		expect(corps.message.exists).toBe(true);
		expect(corps.message.first_name, 'le prénom sert à personnaliser le dialogue').toBeTruthy();
	});

	test('un compte inconnu ouvre la création', async ({page}) => {
		const {corps} = await appelInvite(page, 'webshop.webshop.auth.api.check_email', {
			email: 'e2e.inexistant.zz@example.test',
		});
		expect(corps.message.exists).toBe(false);
	});
});

test.describe('Création de compte — refus attendus', () => {
	test('champs manquants', async ({page}) => {
		const {corps} = await appelInvite(page, 'webshop.webshop.auth.api.create_account', {
			email: emailJetable(),
		});
		expect(corps.message.message).toBe('error');
		expect(corps.message.reason_code).toBe('missing_fields');
	});

	test('adresse e-mail invalide', async ({page}) => {
		const {corps} = await appelInvite(page, 'webshop.webshop.auth.api.create_account', {
			email: 'pas-une-adresse', first_name: 'A', last_name: 'B',
		});
		expect(corps.message.message).toBe('error');
		expect(corps.message.reason_code).toBe('invalid_email');
	});

	test('un compte client existant renvoie vers la connexion', async ({page}) => {
		const {corps} = await appelInvite(page, 'webshop.webshop.auth.api.create_account', {
			email: IDENTIFIANTS.utilisateur, first_name: 'A', last_name: 'B',
		});
		expect(corps.message.message).toBe('error');
		expect(corps.message.reason_code).toBe('account_exists_website');
	});

	//// Sécurité: la boutique ne doit jamais pouvoir toucher à un compte du desk.
	//// Sans ce garde, créer un compte avec l'e-mail d'un administrateur ouvrirait
	//// une confusion de privilèges.
	test('un compte du desk ne peut pas être repris par la boutique', async ({page}) => {
		const {corps} = await appelInvite(page, 'webshop.webshop.auth.api.create_account', {
			email: 'Administrator', first_name: 'A', last_name: 'B',
		});
		expect(corps.message.message).toBe('error');
		expect(
			['account_exists_system', 'invalid_email'],
			'un e-mail d’administrateur ne doit jamais aboutir à une création'
		).toContain(corps.message.reason_code);
	});
});

test.describe('Création de compte — parcours réel', () => {
	test('un nouveau visiteur peut créer son compte', async ({page}) => {
		const email = emailJetable();
		const {corps} = await appelInvite(page, 'webshop.webshop.auth.api.create_account', {
			email, first_name: 'E2E', last_name: 'Auto',
		});
		expect(corps.message.message, `création refusée : ${corps.message.reason || ''}`).not.toBe('error');

		//// Le compte doit exister ET rester un compte client : jamais de rôle desk.
		const {corps: verif} = await appelInvite(page, 'webshop.webshop.auth.api.check_email', {email});
		expect(verif.message.exists, 'le compte doit exister juste après sa création').toBe(true);
	});
});

test.describe('Connexion', () => {
	test('le mot de passe correct ouvre la session', async ({page}) => {
		const r = await page.request.post('/api/method/login', {
			form: {usr: IDENTIFIANTS.utilisateur, pwd: IDENTIFIANTS.motDePasse},
		});
		expect(r.ok()).toBeTruthy();
		expect(await utilisateurCourant(page)).toBe(IDENTIFIANTS.utilisateur);
	});

	test('un mauvais mot de passe n’ouvre aucune session', async ({page}) => {
		const r = await page.request.post('/api/method/login', {
			form: {usr: IDENTIFIANTS.utilisateur, pwd: 'mot-de-passe-volontairement-faux'},
		});
		expect(r.status(), 'un refus doit être un refus, pas un 200').toBeGreaterThanOrEqual(400);
		expect(await utilisateurCourant(page)).toBe('Guest');
	});

	test('le dialogue enchaîne e-mail puis mot de passe', async ({page}) => {
		await page.goto('/all-products');
		await page.waitForLoadState('domcontentloaded');
		await page.evaluate(() => frappe.showLoginDialog({}));

		const dialogue = page.locator('.login-dialog');
		await expect(dialogue).toBeVisible();

		await page.fill('#login_email', IDENTIFIANTS.utilisateur);
		await page.click('.btn-verify-email');

		//// Le mot de passe n'apparaît qu'une fois l'adresse reconnue : c'est ce
		//// qui distingue « je me connecte » de « je crée un compte ».
		await expect(page.locator('.password-section')).toBeVisible();
		await expect(page.locator('.fullname-section')).toBeHidden();
	});

	test('le dialogue demande le nom pour une adresse inconnue', async ({page}) => {
		await page.goto('/all-products');
		await page.waitForLoadState('domcontentloaded');
		await page.evaluate(() => frappe.showLoginDialog({}));

		await page.fill('#login_email', emailJetable());
		await page.click('.btn-verify-email');

		await expect(page.locator('.fullname-section')).toBeVisible();
		await expect(page.locator('.password-section')).toBeHidden();
	});
});

test.describe('Cloisonnement d’un visiteur anonyme', () => {
	//// RULE #1sexies: ce que l'invité ne doit pas atteindre se sonde par l'API,
	//// depuis SA session. Masquer un bouton n'est pas une permission.
	test('les réglages de la boutique ne sont pas lisibles', async ({page}) => {
		const r = await page.request.get(
			'/api/method/frappe.client.get_list?doctype=Webshop%20Settings&fields=["name"]'
		);
		expect(r.status(), 'Webshop Settings doit être refusé à un invité').toBeGreaterThanOrEqual(400);
	});

	test('la liste des utilisateurs n’est pas lisible', async ({page}) => {
		const r = await page.request.get(
			'/api/method/frappe.client.get_list?doctype=User&fields=["name","email"]'
		);
		expect(r.status(), 'la liste des comptes doit être refusée').toBeGreaterThanOrEqual(400);
	});

	test('les adresses ne sont pas lisibles', async ({page}) => {
		const r = await page.request.get(
			'/api/method/frappe.client.get_list?doctype=Address&fields=["name","city"]'
		);
		expect(r.status(), 'les adresses clients doivent être refusées').toBeGreaterThanOrEqual(400);
	});
});
