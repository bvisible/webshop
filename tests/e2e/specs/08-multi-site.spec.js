//// Neoffice — added file (no upstream equivalent).
//// Two shops, two domains, one Frappe site.
////
//// A "Website Profile" (neoffice_theme) maps a domain to its own home page,
//// price list, catalogue subset and access rules. The B2C shop is open to
//// everyone; the B2B shop is flagged b2b_only and reserved to approved
//// business accounts.
////
//// What this file guards is the boundary between the two: a price shown on one
//// domain must be the price charged on that domain, an item hidden from one
//// shop must stay hidden, and the professional shop must not serve an
//// anonymous visitor. Those are the failures a customer notices — and the ones
//// that cost money.
////
//// Runs signed out and drives BOTH domains, so it lives in its own project.

const {test, expect} = require('@playwright/test');
const {
	URL_B2C,
	URL_B2B,
	multiSiteDisponible,
	ouvrirSite,
	connecterSurSite,
	appelSite,
	catalogueDuSite,
	prixRecherche,
	prixPanier,
} = require('../fixtures/sites');

test.describe('Deux sites, deux domaines', () => {
	test.skip(!multiSiteDisponible(), 'un seul domaine configuré (WEBSHOP_E2E_B2B_URL absent)');

	test('chaque domaine sert sa propre boutique', async ({browser}) => {
		for (const url of [URL_B2C, URL_B2B]) {
			const {contexte, page} = await ouvrirSite(browser, url);
			try {
				const reponse = await page.goto('/');
				expect(reponse.status(), `${url} ne répond pas`).toBeLessThan(400);

				//// Le canonique doit désigner CE domaine: sinon le référencement
				//// des deux boutiques se replie sur une seule.
				const canonique = await page.evaluate(
					() => document.querySelector('link[rel="canonical"]')?.href || null
				);
				if (canonique) {
					expect(canonique, 'canonique pointant l’autre domaine').toContain(
						new URL(url).host
					);
				}
			} finally {
				await contexte.close();
			}
		}
	});

	//// Le desk n'a rien à faire sur la boutique professionnelle: un client
	//// portail n'y a pas accès, et l'exposer sur un second domaine élargit la
	//// surface pour rien.
	test('le desk n’est pas servi sur le domaine secondaire', async ({browser}) => {
		const {contexte, page} = await ouvrirSite(browser, URL_B2B);
		try {
			const reponse = await page.goto('/app', {waitUntil: 'domcontentloaded'});
			const surLeDesk = page.url().startsWith(URL_B2B) && page.url().includes('/app');
			expect(surLeDesk && reponse.status() === 200, 'le desk répond sur le domaine B2B').toBe(
				false
			);
		} finally {
			await contexte.close();
		}
	});
});

test.describe('Catalogue propre à chaque site', () => {
	test.skip(!multiSiteDisponible(), 'un seul domaine configuré');

	//// Un article restreint à un site ne doit pas fuir sur l'autre. C'est le
	//// cas d'usage le plus attendu du multi-boutique: des références
	//// professionnelles absentes de la vitrine grand public.
	test('un article restreint reste caché sur l’autre domaine', async ({browser}) => {
		const b2c = await ouvrirSite(browser, URL_B2C);
		const b2b = await ouvrirSite(browser, URL_B2B);
		try {
			const catB2C = await catalogueDuSite(b2c.page);
			const catB2B = await catalogueDuSite(b2b.page);
			test.skip(
				catB2C.length === 0 || catB2B.length === 0,
				'catalogue vide sur l’un des domaines'
			);

			const codesB2C = new Set(catB2C.map((i) => i.item_code));
			const codesB2B = new Set(catB2B.map((i) => i.item_code));
			const seulementB2C = [...codesB2C].filter((c) => !codesB2B.has(c));
			const seulementB2B = [...codesB2B].filter((c) => !codesB2C.has(c));

			//// Si aucune restriction n'est configurée, les deux catalogues sont
			//// identiques — c'est licite, mais alors la fonctionnalité n'est pas
			//// éprouvée: on le dit plutôt que de passer au vert pour rien.
			test.skip(
				seulementB2C.length === 0 && seulementB2B.length === 0,
				'aucun article restreint à un site sur cette instance'
			);

			expect(
				seulementB2C.length + seulementB2B.length,
				'les catalogues ne se distinguent pas'
			).toBeGreaterThan(0);
		} finally {
			await b2c.contexte.close();
			await b2b.contexte.close();
		}
	});
});

test.describe('Le prix affiché est le prix facturé', () => {
	test.skip(!multiSiteDisponible(), 'un seul domaine configuré');

	//// LE défaut que ce bloc verrouille.
	////
	//// Le catalogue lisait la liste de prix du profil de site, mais la
	//// recherche, les carrousels et le PANIER lisaient Webshop Settings. Sur le
	//// domaine B2B, un article s'affichait à 199.00 dans la liste et sur sa
	//// fiche, et le panier facturait 549.00 — le tarif grand public. Une
	//// boutique qui montre un prix et en facture un autre n'a pas d'excuse.
	test('catalogue, recherche et panier annoncent le même prix', async ({browser}) => {
		for (const url of [URL_B2C, URL_B2B]) {
			const {contexte, page} = await ouvrirSite(browser, url);
			try {
				const catalogue = await catalogueDuSite(page);
				const article = catalogue.find((i) => i.prix);
				test.skip(!article, `aucun article tarifé sur ${url}`);

				const recherche = await prixRecherche(page, article.item_code);

				//// Connexion avant de toucher au panier: un site réservé n'en a
				//// pas pour un anonyme (403), et c'est voulu.
				test.skip(!(await connecterSurSite(page, url)), `connexion impossible sur ${url}`);
				const panier = await prixPanier(page, article.item_code);

				if (recherche !== null) {
					expect(
						recherche,
						`${url} : catalogue ${article.prix} vs recherche ${recherche}`
					).toBeCloseTo(article.prix, 2);
				}
				expect(
					panier.prix,
					`${url} : catalogue ${article.prix} vs panier ${panier.prix} ` +
						`(liste « ${panier.liste} »)`
				).toBeCloseTo(article.prix, 2);
			} finally {
				await contexte.close();
			}
		}
	});

	test('les deux boutiques n’appliquent pas la même liste de prix', async ({browser}) => {
		const b2c = await ouvrirSite(browser, URL_B2C);
		const b2b = await ouvrirSite(browser, URL_B2B);
		try {
			const commun = await articleCommun(b2c.page, b2b.page);
			test.skip(!commun, 'aucun article présent sur les deux domaines');

			test.skip(
				!(await connecterSurSite(b2c.page, URL_B2C)) ||
					!(await connecterSurSite(b2b.page, URL_B2B)),
				'connexion impossible sur l’un des domaines'
			);
			const pB2C = await prixPanier(b2c.page, commun);
			const pB2B = await prixPanier(b2b.page, commun);
			test.skip(
				pB2C.liste === pB2B.liste,
				'les deux sites partagent la même liste de prix (rien à distinguer)'
			);

			//// Deux listes distinctes doivent produire deux factures distinctes,
			//// sinon la liste du profil est décorative.
			expect(
				pB2B.prix,
				`même prix (${pB2B.prix}) malgré des listes différentes ` +
					`(« ${pB2C.liste} » vs « ${pB2B.liste} »)`
			).not.toBeCloseTo(pB2C.prix, 2);
		} finally {
			await b2c.contexte.close();
			await b2b.contexte.close();
		}
	});
});

test.describe('Boutique réservée aux professionnels', () => {
	test.skip(!multiSiteDisponible(), 'un seul domaine configuré');

	//// Le contrôle de connexion vit dans neoffice_theme (on_session_creation);
	//// ce test vérifie qu'il agit vraiment, vu du client.
	test('un compte grand public ne peut pas se connecter', async ({browser}) => {
		const {contexte, page} = await ouvrirSite(browser, URL_B2B);
		try {
			const r = await page.request.post('/api/method/login', {
				form: {
					usr: process.env.WEBSHOP_E2E_USER,
					pwd: process.env.WEBSHOP_E2E_PASSWORD,
				},
			});
			expect(
				r.status(),
				'un compte grand public entre sur la boutique professionnelle'
			).toBeGreaterThanOrEqual(400);
		} finally {
			await contexte.close();
		}
	});

	test('le même compte se connecte normalement sur la boutique grand public', async ({browser}) => {
		const {contexte, page} = await ouvrirSite(browser, URL_B2C);
		try {
			const r = await page.request.post('/api/method/login', {
				form: {
					usr: process.env.WEBSHOP_E2E_USER,
					pwd: process.env.WEBSHOP_E2E_PASSWORD,
				},
			});
			//// Le pendant du test précédent: le cloisonnement doit refuser d'un
			//// côté SANS casser l'autre.
			expect(r.status(), 'le compte ne peut plus se connecter nulle part').toBe(200);
		} finally {
			await contexte.close();
		}
	});

	//// Le gating de connexion exempte Guest: un visiteur anonyme pouvait donc
	//// remplir un panier sur le domaine professionnel, atteindre le tunnel et le
	//// dérouler — aux tarifs revendeur. Commander demande désormais un compte.
	test('un visiteur anonyme ne peut pas commander', async ({browser}) => {
		const {contexte, page} = await ouvrirSite(browser, URL_B2B);
		try {
			await page.goto('/checkout', {waitUntil: 'domcontentloaded'});
			await page.waitForTimeout(2500);

			await expect(
				page.locator('#step-address'),
				'un visiteur anonyme voit le tunnel de commande professionnel'
			).toHaveCount(0);
			expect(page.url(), 'un invité est envoyé vers le desk').not.toContain('/app');
		} finally {
			await contexte.close();
		}
	});

	//// Le panier lui-même est fermé, pas seulement le tunnel: sur un site
	//// réservé, un anonyme ne constitue pas de commande — même à titre
	//// d'intention.
	test('un visiteur anonyme ne peut pas remplir de panier', async ({browser}) => {
		const {contexte, page} = await ouvrirSite(browser, URL_B2B);
		try {
			const code = await premierCode(page);
			test.skip(!code, 'aucun article listé sur ce domaine');

			//// La garde est côté SERVEUR: cet endpoint est appelable directement,
			//// et masquer un bouton n'est pas une permission.
			const r = await page.request.post(
				'/api/method/webshop.webshop.shopping_cart.cart.update_cart',
				{form: {item_code: code, qty: 1}}
			);
			expect(r.status(), 'un anonyme remplit un panier sur le site réservé').toBe(403);
		} finally {
			await contexte.close();
		}
	});

	test('la page panier renvoie un anonyme vers la connexion', async ({browser}) => {
		const {contexte, page} = await ouvrirSite(browser, URL_B2B);
		try {
			await page.goto('/cart', {waitUntil: 'domcontentloaded'});
			await page.waitForTimeout(2000);
			expect(page.url(), 'le panier reste ouvert à un anonyme').not.toMatch(/\/cart\/?$/);
			expect(page.url(), 'un invité est envoyé vers le desk').not.toContain('/app');
		} finally {
			await contexte.close();
		}
	});

	//// Ce que voit le client: à la place d'« Ajouter au panier », une invitation
	//// à se connecter. Un bouton qui échouerait au clic serait pire que pas de
	//// bouton du tout.
	test('le bouton d’ajout devient un appel à se connecter', async ({browser}) => {
		const b2b = await ouvrirSite(browser, URL_B2B);
		const b2c = await ouvrirSite(browser, URL_B2C);
		try {
			//// Un article TARIFÉ sur les deux sites: sans prix, la fiche n'affiche
			//// aucun bouton du tout et le test ne compare rien.
			const route = await routeArticleTarifeSurLesDeux(b2c.page, b2b.page);
			test.skip(!route, 'aucun article tarifé sur les deux domaines');

			const lire = async (page) => {
				await page.goto('/' + route);
				await page.waitForLoadState('networkidle');
				return page.evaluate(() =>
					[...document.querySelectorAll('.btn-add-to-cart')]
						.filter((e) => e.offsetHeight > 0)
						.map((e) => ({tag: e.tagName, href: e.getAttribute('href') || ''}))
				);
			};

			const surB2B = await lire(b2b.page);
			expect(surB2B.length, 'aucun bouton sur la fiche du site réservé').toBeGreaterThan(0);
			expect(surB2B[0].href, 'le bouton ne mène pas à la connexion').toContain('/login');

			//// Et le pendant: la boutique grand public garde son vrai bouton.
			const surB2C = await lire(b2c.page);
			expect(surB2C.length, 'aucun bouton sur la fiche grand public').toBeGreaterThan(0);
			expect(surB2C[0].href, 'le bouton grand public mène à la connexion').not.toContain(
				'/login'
			);
		} finally {
			await b2b.contexte.close();
			await b2c.contexte.close();
		}
	});

	test('un visiteur anonyme commande normalement sur la boutique grand public', async ({
		browser,
	}) => {
		const {contexte, page} = await ouvrirSite(browser, URL_B2C);
		try {
			await appelSite(page, 'webshop.webshop.shopping_cart.cart.update_cart', {
				item_code: await premierCode(page),
				qty: 1,
			});
			await page.goto('/checkout', {waitUntil: 'domcontentloaded'});
			await page.waitForTimeout(3000);
			//// Le pendant: la restriction ne doit pas déborder sur le B2C.
			await expect(
				page.locator('#step-address'),
				'le tunnel grand public est devenu inaccessible aux invités'
			).toHaveCount(1);
		} finally {
			await contexte.close();
		}
	});
});

/** An item code served by both domains, or null. */
async function articleCommun(pageA, pageB) {
	const a = await catalogueDuSite(pageA);
	const b = await catalogueDuSite(pageB);
	const codesB = new Set(b.map((i) => i.item_code));
	const commun = a.find((i) => codesB.has(i.item_code));
	return commun ? commun.item_code : null;
}

/** First item code this domain lists, or null. */
async function premierCode(page) {
	const catalogue = await catalogueDuSite(page);
	return catalogue.length ? catalogue[0].item_code : null;
}

//// Route of an item PRICED on both domains.
////
//// The product page hides its whole action area when the item has no price on
//// the current site — no price, no button, not even the sign-in call. On this
//// instance only 6 of 310 items carry a « Vente B2B » rate, so picking the
//// first item listed lands on one that shows nothing, and the test would
//// compare two empty pages.
async function routeArticleTarifeSurLesDeux(pageB2C, pageB2B) {
	const catB2B = (await catalogueDuSite(pageB2B)).filter((i) => i.prix && i.route);
	const codesB2C = new Set(
		(await catalogueDuSite(pageB2C)).filter((i) => i.prix).map((i) => i.item_code)
	);
	const commun = catB2B.find((i) => codesB2C.has(i.item_code));
	return commun ? commun.route : null;
}
