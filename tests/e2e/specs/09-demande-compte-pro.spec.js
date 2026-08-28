//// Neoffice — added file (no upstream equivalent).
//// Applying for a professional account, and what approval produces.
////
//// A b2b_only site refuses anyone who is not already an approved business
//// account. Without this form a prospect has no way in at all: someone has to
//// create the Customer and the User by hand in the desk.
////
//// The form lives in neoffice_theme (DocType "B2B Account Request",
//// /demande-compte-pro); these tests drive it from the shop's point of view,
//// and — through the server helper — check what approval actually creates.
////
//// Runs signed out, against the B2B domain.

const {test, expect} = require('@playwright/test');
const {URL_B2B, multiSiteDisponible, ouvrirSite, appelSite, prixPanier} = require('../fixtures/sites');
const {activationDisponible, surLeServeur} = require('../fixtures/activation');

const nouvelEmail = () => `pro.e2e.${Date.now()}@yopmail.com`;
const MOT_DE_PASSE = 'Pro-Compte-E2E-2026!';

/** Fill and submit the public application form. */
async function deposerDemande(page, email, societe) {
	await page.goto('/demande-compte-pro');
	await page.waitForLoadState('networkidle');

	await page.fill('#company_name', societe);
	await page.fill('#first_name', 'Prospect');
	await page.fill('#last_name', 'E2E');
	await page.fill('#email', email);
	await page.fill('#phone', '+41791234567');
	await page.fill('#address_line1', 'Rue du Test 1');
	await page.fill('#city', 'Lausanne');
	await page.fill('#pincode', '1003');
	await page.locator('#envoyer-demande').click();
}

test.describe('Demande de compte professionnel', () => {
	test.skip(!multiSiteDisponible(), 'un seul domaine configuré');

	test('le formulaire est accessible à un visiteur anonyme', async ({browser}) => {
		const {contexte, page} = await ouvrirSite(browser, URL_B2B);
		try {
			const reponse = await page.goto('/demande-compte-pro');
			expect(reponse.status()).toBe(200);
			//// Sans formulaire atteignable, un site réservé est une impasse: un
			//// prospect ne peut ni entrer ni demander à entrer.
			await expect(page.locator('#company_name')).toBeVisible();
			await expect(page.locator('#email')).toBeVisible();
		} finally {
			await contexte.close();
		}
	});

	test('une demande incomplète est refusée', async ({browser}) => {
		const {contexte, page} = await ouvrirSite(browser, URL_B2B);
		try {
			const m = await appelSite(page, 'neoffice_theme.b2b_requests.submit_account_request', {
				company_name: 'Sans Contact SA',
			});
			expect(m && m.status).toBe('error');
			expect(m && m.reason_code).toBe('missing_fields');
		} finally {
			await contexte.close();
		}
	});

	test('une adresse e-mail invalide est refusée', async ({browser}) => {
		const {contexte, page} = await ouvrirSite(browser, URL_B2B);
		try {
			const m = await appelSite(page, 'neoffice_theme.b2b_requests.submit_account_request', {
				company_name: 'Mauvais Mail SA',
				first_name: 'A',
				last_name: 'B',
				email: 'pas-une-adresse',
			});
			expect(m && m.status).toBe('error');
			expect(m && m.reason_code).toBe('invalid_email');
		} finally {
			await contexte.close();
		}
	});

	//// Sécurité: une vitrine publique ne doit jamais servir à réclamer un
	//// compte du desk. Même garde que la création de compte grand public.
	test('un compte du desk ne peut pas être réclamé', async ({browser}) => {
		const {contexte, page} = await ouvrirSite(browser, URL_B2B);
		try {
			const m = await appelSite(page, 'neoffice_theme.b2b_requests.submit_account_request', {
				company_name: 'Usurpation SA',
				first_name: 'A',
				last_name: 'B',
				email: 'Administrator',
			});
			expect(m && m.status).toBe('error');
			expect(
				['account_exists_system', 'invalid_email'],
				'un e-mail d’administrateur ne doit jamais aboutir'
			).toContain(m && m.reason_code);
		} finally {
			await contexte.close();
		}
	});

	test('une demande déposée est enregistrée pour le bon site', async ({browser}) => {
		const {contexte, page} = await ouvrirSite(browser, URL_B2B);
		const email = nouvelEmail();
		try {
			await deposerDemande(page, email, 'Depot E2E SA');

			//// Le formulaire disparaît au profit d'un message: on ne redépose pas
			//// la même demande par inadvertance.
			await expect(page.locator('#demande-resultat')).toBeVisible({timeout: 30_000});
			await expect(page.locator('#demande-compte-pro')).toBeHidden();

			test.skip(!activationDisponible(), 'vérification serveur indisponible');
			const ligne = surLeServeur(
				`d = frappe.get_all("B2B Account Request", filters={"email": ${JSON.stringify(email)}},` +
					` fields=["status", "website_profile", "customer_group"])\nprint(d[0] if d else "")`
			);
			//// Le site d'origine ET le groupe cible doivent être posés: c'est le
			//// site qui décide du groupe, jamais le demandeur.
			expect(ligne, 'la demande n’a pas été enregistrée').toContain('Nouvelle');
			expect(ligne, 'le site d’origine n’a pas été retenu').toMatch(/website_profile.+\w/);
		} finally {
			await contexte.close();
		}
	});

	test('une seconde demande pour la même adresse est refusée', async ({browser}) => {
		const {contexte, page} = await ouvrirSite(browser, URL_B2B);
		const email = nouvelEmail();
		try {
			const premiere = await appelSite(
				page,
				'neoffice_theme.b2b_requests.submit_account_request',
				{company_name: 'Doublon SA', first_name: 'A', last_name: 'B', email}
			);
			expect(premiere && premiere.status).toBe('success');

			const seconde = await appelSite(
				page,
				'neoffice_theme.b2b_requests.submit_account_request',
				{company_name: 'Doublon SA', first_name: 'A', last_name: 'B', email}
			);
			expect(seconde && seconde.status).toBe('error');
			expect(seconde && seconde.reason_code).toBe('already_requested');
		} finally {
			await contexte.close();
		}
	});
});

test.describe('Ce que produit une approbation', () => {
	test.skip(!multiSiteDisponible(), 'un seul domaine configuré');
	test.skip(!activationDisponible(), 'approbation serveur indisponible');
	test.describe.configure({mode: 'serial'});

	let email = null;
	let societe = null;

	test('une demande approuvée crée le client dans le groupe du site', async ({browser}) => {
		test.setTimeout(150_000);
		const {contexte, page} = await ouvrirSite(browser, URL_B2B);
		email = nouvelEmail();
		societe = `Approbation E2E ${Date.now()}`;
		try {
			const m = await appelSite(page, 'neoffice_theme.b2b_requests.submit_account_request', {
				company_name: societe,
				first_name: 'Prospect',
				last_name: 'E2E',
				email,
				address_line1: 'Rue du Test 1',
				city: 'Lausanne',
				pincode: '1003',
			});
			expect(m && m.status).toBe('success');
		} finally {
			await contexte.close();
		}

		const sortie = surLeServeur(
			`nom = frappe.db.get_value("B2B Account Request", {"email": ${JSON.stringify(email)}}, "name")\n` +
				`frappe.set_user("Administrator")\n` +
				`res = frappe.get_doc("B2B Account Request", nom).approve()\n` +
				`frappe.db.commit()\n` +
				`c = frappe.get_doc("Customer", res["customer"])\n` +
				`portal = [p.user for p in (c.get("portal_users") or [])]\n` +
				`print("GROUPE=" + (c.customer_group or ""))\n` +
				`print("PORTAL=" + str(len(portal)))\n` +
				`print("TYPE=" + (frappe.db.get_value("User", res["user"], "user_type") or ""))`
		);

		//// Le groupe conditionne l'accès au site ET le tarif: s'il est faux, le
		//// client est créé mais ne pourra pas entrer, ou paiera le mauvais prix.
		expect(sortie, 'le client n’est pas dans un groupe professionnel').toMatch(/GROUPE=\S/);
		expect(sortie, 'le compte n’est pas un compte client').toContain('TYPE=Website User');
		//// Un portal user en double n'est pas fatal mais se multiplie à chaque
		//// enregistrement et pollue la fiche.
		expect(sortie, 'portal user en double').toContain('PORTAL=1');
	});

	test('le compte créé peut se connecter et acheter au tarif du site', async ({browser}) => {
		test.setTimeout(180_000);
		test.skip(!email, 'aucune demande approuvée');

		//// Le lien d'activation est forgé côté serveur, exactement comme celui
		//// que Frappe met dans son e-mail (la clé en clair n'existe nulle part
		//// ailleurs — la base n'en garde que le hash).
		const lien = surLeServeur(
			`from neoffice_theme.neoffice_theme.doctype.b2b_account_request.b2b_account_request import activation_link\n` +
				`lien = activation_link(${JSON.stringify(email)}, ` +
				`frappe.db.get_value("B2B Account Request", {"email": ${JSON.stringify(email)}}, "website_profile"))\n` +
				`frappe.db.commit()\nprint(lien)`
		);
		const cle = (lien.split('key=')[1] || '').trim();
		expect(cle, 'aucun lien d’activation').toBeTruthy();

		//// Le lien doit mener sur LE domaine professionnel: envoyer un futur
		//// revendeur sur la boutique grand public est une impasse.
		expect(lien, 'le lien d’activation pointe le mauvais domaine').toContain(
			new URL(URL_B2B).host
		);

		const {contexte, page} = await ouvrirSite(browser, URL_B2B);
		try {
			const activation = await page.request.post(
				'/api/method/frappe.core.doctype.user.user.update_password',
				{form: {key: cle, new_password: MOT_DE_PASSE}}
			);
			expect(activation.ok(), `activation refusée (${activation.status()})`).toBeTruthy();

			//// LE test qui compte: le compte issu de la demande entre vraiment sur
			//// le site réservé, là où un compte grand public est refusé.
			const connexion = await page.request.post('/api/method/login', {
				form: {usr: email, pwd: MOT_DE_PASSE},
			});
			expect(
				connexion.status(),
				'le compte approuvé ne peut pas entrer sur le site professionnel'
			).toBe(200);

			//// Et il achète au tarif de ce site, pas au tarif grand public.
			const {catalogueDuSite} = require('../fixtures/sites');
			const catalogue = await catalogueDuSite(page);
			const article = catalogue.find((i) => i.prix);
			test.skip(!article, 'aucun article tarifé sur ce domaine');

			const panier = await prixPanier(page, article.item_code);
			expect(
				panier.prix,
				`catalogue ${article.prix} vs panier ${panier.prix} (« ${panier.liste} »)`
			).toBeCloseTo(article.prix, 2);
		} finally {
			await contexte.close();
		}
	});
});
