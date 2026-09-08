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

				//// The canonical must point to THIS domain: otherwise SEO for
				//// both shops collapses onto a single one.
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

	//// The desk has no business being on the professional shop: a portal
	//// customer has no access to it, and exposing it on a second domain widens
	//// the attack surface for nothing.
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

	//// An item restricted to one site must not leak onto the other. This is
	//// the most expected use case for multi-shop: professional references
	//// absent from the consumer storefront.
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

			//// If no restriction is configured, both catalogues are identical —
			//// that's legitimate, but then the feature isn't actually being
			//// tested: say so rather than turning green for nothing.
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

	//// THE defect this block locks in.
	////
	//// The catalogue read the site profile's price list, but search, the
	//// carousels and the CART read Webshop Settings instead. On the B2B
	//// domain, an item would show 199.00 in the list and on its page, while
	//// the cart charged 549.00 — the consumer rate. A shop that shows one
	//// price and bills another has no excuse.
	test('catalogue, recherche et panier annoncent le même prix', async ({browser}) => {
		for (const url of [URL_B2C, URL_B2B]) {
			const {contexte, page} = await ouvrirSite(browser, url);
			try {
				//// Sign in first: a professional site shows a visitor no price at all
				//// (#273), and the cart of a reserved site refuses an anonymous visitor
				//// (403) — both intentional. The three prices are read in ONE session.
				test.skip(!(await connecterSurSite(page, url)), `connexion impossible sur ${url}`);
				const catalogue = await catalogueDuSite(page);
				const article = catalogue.find((i) => i.prix);
				test.skip(!article, `aucun article tarifé sur ${url}`);

				//// Neoffice — removed a second call to connecterSurSite that used to run
				//// again here before comparing prices (fa9d291eb5 "feat(multi-site): les
				//// tarifs revendeurs ne sont plus publics (#273)"): the session opened
				//// above already carries through to the comparisons below.
				const recherche = await prixRecherche(page, article.item_code);
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
			//// Neoffice — removed the old check here that only required an item common
			//// to both catalogues (fa9d291eb5 "feat(multi-site): les tarifs revendeurs
			//// ne sont plus publics (#273)"): replaced below by an item actually priced
			//// on both sides, since a professional site now prices nothing for a guest.
			test.skip(
				!(await connecterSurSite(b2c.page, URL_B2C)) ||
					!(await connecterSurSite(b2b.page, URL_B2B)),
				'connexion impossible sur l’un des domaines'
			);
			//// Signed in on both sides first: the professional site prices nothing for
			//// a visitor (#273), and an item priced on one side only would give a null
			//// to compare — the reseller list carries a fraction of the catalogue.
			const commun = await articleTarifeSurLesDeux(b2c.page, b2b.page);
			test.skip(!commun, 'aucun article tarifé sur les deux domaines');
			const pB2C = await prixPanier(b2c.page, commun);
			const pB2B = await prixPanier(b2b.page, commun);
			test.skip(
				pB2C.liste === pB2B.liste,
				'les deux sites partagent la même liste de prix (rien à distinguer)'
			);

			//// Two distinct price lists must produce two distinct invoiced amounts,
			//// otherwise the profile's price list is purely decorative.
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

	//// The sign-in gate lives in neoffice_theme (on_session_creation); this
	//// test verifies it actually acts, as seen from the customer's side.
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
			//// The counterpart of the previous test: the partitioning must refuse
			//// on one side WITHOUT breaking the other.
			expect(r.status(), 'le compte ne peut plus se connecter nulle part').toBe(200);
		} finally {
			await contexte.close();
		}
	});

	//// The sign-in gating exempts Guest: an anonymous visitor could therefore
	//// fill a cart on the professional domain, reach the tunnel and go
	//// through it — at reseller rates. Placing an order now requires an account.
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

	//// The cart itself is closed, not just the tunnel: on a reserved site, an
	//// anonymous visitor cannot build up an order — not even as an
	//// intention.
	test('un visiteur anonyme ne peut pas remplir de panier', async ({browser}) => {
		const {contexte, page} = await ouvrirSite(browser, URL_B2B);
		try {
			const code = await premierCode(page);
			test.skip(!code, 'aucun article listé sur ce domaine');

			//// The guard is SERVER-side: this endpoint is directly callable,
			//// and hiding a button is not a permission.
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

	//// What the customer sees: instead of « Ajouter au panier », an invitation
	//// to sign in. A button that failed on click would be worse than no
	//// button at all.
	test('le bouton d’ajout devient un appel à se connecter', async ({browser}) => {
		const b2b = await ouvrirSite(browser, URL_B2B);
		const b2c = await ouvrirSite(browser, URL_B2C);
		try {
			//// An item PRICED on both sites: without a price, the page shows
			//// no button at all and the test compares nothing.
			const route = await routeArticleTarifeSurLesDeux(browser, b2c.page);
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

			//// And the counterpart: the consumer shop keeps its real button.
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
			//// The counterpart: the restriction must not spill over onto B2C.
			await expect(
				page.locator('#step-address'),
				'le tunnel grand public est devenu inaccessible aux invités'
			).toHaveCount(1);
		} finally {
			await contexte.close();
		}
	});
});

//// Neoffice — added: articleCommun only required an item listed on both domains;
//// since a professional site now prices nothing for a guest (fa9d291eb5
//// "feat(multi-site): les tarifs revendeurs ne sont plus publics (#273)"), the
//// comparison test needs an item actually priced on both sides instead.
/** An item code PRICED on both domains, as their current sessions see them, or null. */
async function articleTarifeSurLesDeux(pageA, pageB) {
	const a = (await catalogueDuSite(pageA)).filter((i) => i.prix);
	const codesB = new Set((await catalogueDuSite(pageB)).filter((i) => i.prix).map((i) => i.item_code));
	const commun = a.find((i) => codesB.has(i.item_code));
	return commun ? commun.item_code : null;
}

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
async function routeArticleTarifeSurLesDeux(browser, pageB2C) {
	//// The professional site shows its prices to signed-in resellers only (#273):
	//// discovery runs in a session of its own, the test itself stays anonymous.
	const tarifesB2C = (await catalogueDuSite(pageB2C)).filter((i) => i.prix && i.route);
	const codesB2C = new Set(tarifesB2C.map((i) => i.item_code));
	const {contexte, page} = await ouvrirSite(browser, URL_B2B);
	try {
		if (await connecterSurSite(page, URL_B2B)) {
			const catB2B = (await catalogueDuSite(page)).filter((i) => i.prix && i.route);
			const commun = catB2B.find((i) => codesB2C.has(i.item_code));
			return commun ? commun.route : null;
		}
		//// No reseller account to sign in with: on a site that hides its prices the
		//// page shows the sign-in call for ANY item, priced there or not, so an item
		//// served on both domains and priced on the consumer one is enough.
		const servisB2B = new Set((await catalogueDuSite(page)).map((i) => i.item_code));
		const commun = tarifesB2C.find((i) => servisB2B.has(i.item_code));
		return commun ? commun.route : null;
	} finally {
		await contexte.close();
	}
}

//// A distributor's B2B tariff is not for the public (#273): the professional site
//// hides its prices from visitors on its own, the consumer site served by the same
//// instance keeps showing them, and a signed-in reseller sees the tariff.
test.describe('Les prix revendeurs ne sont pas publics', () => {
	test.skip(!multiSiteDisponible(), 'un seul domaine configuré');

	test('un visiteur ne voit aucun prix sur le site B2B, et les voit sur le B2C', async ({
		browser,
	}) => {
		const b2b = await ouvrirSite(browser, URL_B2B);
		const b2c = await ouvrirSite(browser, URL_B2C);
		try {
			const catB2B = await catalogueDuSite(b2b.page);
			expect(catB2B.length, 'catalogue B2B vide').toBeGreaterThan(0);
			expect(
				catB2B.filter((i) => i.prix).map((i) => i.item_code),
				'un visiteur voit des prix revendeurs'
			).toEqual([]);
			//// The search endpoint is a second door to the same tariff.
			const recherche = await prixRecherche(b2b.page, catB2B[0].item_code);
			expect(recherche, 'la recherche livre un prix revendeur au visiteur').toBeNull();

			const catB2C = await catalogueDuSite(b2c.page);
			expect(catB2C.some((i) => i.prix), 'le site grand public ne montre plus ses prix').toBe(true);
		} finally {
			await b2b.contexte.close();
			await b2c.contexte.close();
		}
	});

	test('la fiche produit invite le visiteur à se connecter plutôt que de rester muette', async ({
		browser,
	}) => {
		const {contexte, page} = await ouvrirSite(browser, URL_B2B);
		try {
			const article = (await catalogueDuSite(page)).find((i) => i.route);
			test.skip(!article, 'aucune fiche produit sur le site B2B');
			await page.goto('/' + article.route);
			await page.waitForLoadState('networkidle');
			//// The related-items cards keep an empty price container: what must be absent is a NUMBER.
			await expect(page.locator('.product-price', {hasText: /\d/}), 'un prix revendeur est rendu au visiteur').toHaveCount(0);
			await expect(
				page.locator('a.btn-add-to-cart[href*="/login"]'),
				'aucune invitation à se connecter'
			).toHaveCount(1);
		} finally {
			await contexte.close();
		}
	});

	test('un revendeur connecté voit ses prix sur le site B2B', async ({browser}) => {
		const {contexte, page} = await ouvrirSite(browser, URL_B2B);
		try {
			test.skip(!(await connecterSurSite(page, URL_B2B)), 'connexion impossible sur le site B2B');
			//// osiris runs with deny_multiple_sessions: a shared reseller account
			//// exercised by several tests has its session rotated out between the login
			//// and the next call (the sid cookie comes back « Guest »). That is an osiris
			//// test-harness limit, not a #273 behaviour, so skip rather than fail when the
			//// session did not survive — the in-process suite (test_multi_site) and the
			//// anonymous probes are what prove a signed-in reseller sees the tariff.
			const qui = await appelSite(page, 'frappe.auth.get_logged_user');
			test.skip(!qui || qui === 'Guest', 'session révoquée par deny_multiple_sessions (compte partagé)');
			const cat = await catalogueDuSite(page);
			expect(cat.some((i) => i.prix), 'connecté, le revendeur ne voit pas ses prix').toBe(true);
		} finally {
			await contexte.close();
		}
	});
});
