//// Neoffice — added file (no upstream equivalent).
//// Shared helpers. Everything that is *not* the subject of a test happens
//// through the API here: signing in via the dialog is tested once, in
//// 01-authentification, and every other spec logs in through /api/method/login
//// so a broken dialog fails one test instead of the whole suite.

const {expect} = require('@playwright/test');

const IDENTIFIANTS = {
	utilisateur: process.env.WEBSHOP_E2E_USER,
	motDePasse: process.env.WEBSHOP_E2E_PASSWORD,
};

//// Signing in again when the stored session is already valid is what tripped
//// Frappe's rate limit and failed unrelated specs. Check first, sign in only
//// if needed.
async function connecter(page, identifiants = IDENTIFIANTS) {
	if ((await utilisateurCourant(page)) === identifiants.utilisateur) return;

	if (!identifiants.utilisateur || !identifiants.motDePasse) {
		throw new Error('WEBSHOP_E2E_USER / WEBSHOP_E2E_PASSWORD manquants');
	}
	//// Three spaced-out tries: the site intermittently refuses (404, 417,
	//// timeout) when under load or when attempts follow each other closely. A
	//// failure here brings down a test that has nothing to do with signing in.
	let reponse = null;
	for (let essai = 1; essai <= 3; essai += 1) {
		try {
			reponse = await page.request.post('/api/method/login', {
				form: {usr: identifiants.utilisateur, pwd: identifiants.motDePasse},
			});
			if (reponse.ok()) return;
		} catch (err) {
			reponse = null;
		}
		if (essai < 3) await page.waitForTimeout(4000 * essai);
	}
	expect(
		reponse && reponse.ok(),
		`connexion refusée (${reponse ? reponse.status() : 'aucune réponse'}) après 3 essais — ` +
			'serveur chargé ou limite de tentatives Frappe ?'
	).toBeTruthy();
}

/** The logged-in user as the server sees it — the only trustworthy check. */
async function utilisateurCourant(page) {
	const r = await page.request.get('/api/method/frappe.auth.get_logged_user');
	if (!r.ok()) return 'Guest';
	const corps = await r.json();
	return corps.message || 'Guest';
}

/** Call a whitelisted method from the page's own session. */
async function appeler(page, methode, args = {}) {
	return page.evaluate(
		([m, a]) =>
			new Promise((res) =>
				frappe.call({method: m, args: a, callback: (r) => res(r.message), error: () => res(null)})
			),
		[methode, args]
	);
}

//// Empty the cart so a spec never inherits the previous one's state.
////
//// Goes through page.request rather than page.evaluate + frappe.call: the same
//// endpoints, without a page load or a round trip through the DOM for each
//// line. Emptying a cart of a dozen lines used to blow the 90 s test budget.
async function viderPanier(page) {
	//// Several passes: one is not always enough. The cart can carry two lines
	//// of the same item (two warehouses), and an update_cart call that fails —
	//// the site intermittently refuses under load — used to leave lines
	//// behind. The next spec would then find a supposedly "empty" cart holding
	//// three items and blame the page.
	for (let passe = 1; passe <= 3; passe += 1) {
		const devis = await lireDevis(page);
		const lignes = (devis && devis.doc && devis.doc.items) || [];
		if (lignes.length === 0) return true;

		//// Deliberately sequential: two concurrent update_cart calls write to the
		//// same quotation and the last one overwrites the first.
		for (const ligne of lignes) {
			await page.request.post('/api/method/webshop.webshop.shopping_cart.cart.update_cart', {
				form: {
					item_code: ligne.item_code,
					qty: 0,
					...(ligne.warehouse ? {warehouse: ligne.warehouse} : {}),
				},
			});
		}
		await page.waitForTimeout(1000);
	}

	const reste = await lireDevis(page);
	return ((reste && reste.doc && reste.doc.items) || []).length === 0;
}

/** The cart quotation, read over HTTP (no page needed). */
async function lireDevis(page) {
	return lireJson(page, '/api/method/webshop.webshop.shopping_cart.cart.get_cart_quotation');
}

//// POST an endpoint and return its message, or null.
////
//// Never lets a non-JSON body throw: under load the site answers 200 with an
//// HTML error page, and `await r.json()` then dies with «Unexpected token '<'»
//// — an error that says nothing about what actually went wrong, three call
//// levels away from the test that will be blamed for it.
async function lireJson(page, chemin, donnees = null) {
	let r;
	try {
		r = await page.request.post(chemin, donnees ? {form: donnees} : undefined);
	} catch (err) {
		return null;
	}
	if (!r.ok()) return null;
	const corps = await r.text();
	try {
		return JSON.parse(corps).message ?? null;
	} catch (err) {
		return null;
	}
}

/** The customer's address book, read over HTTP. */
async function lireCarnetAdresses(page) {
	return (
		(await lireJson(page, '/api/method/webshop.webshop.shopping_cart.cart.get_customer_addresses')) ||
		[]
	);
}

/** Add an item to the cart, optionally from a given warehouse. */
async function ajouterAuPanier(page, itemCode, qty = 1, warehouse = null) {
	const r = await page.request.post('/api/method/webshop.webshop.shopping_cart.cart.update_cart', {
		form: {item_code: itemCode, qty, ...(warehouse ? {warehouse} : {})},
	});
	return r.ok();
}

/** Count the XHR/fetch calls a block of work triggers. */
async function compterRequetes(page, travail) {
	const avant = await page.evaluate(
		() => performance.getEntriesByType('resource').filter((r) => /xmlhttprequest|fetch/.test(r.initiatorType)).length
	);
	await travail();
	return (
		(await page.evaluate(
			() => performance.getEntriesByType('resource').filter((r) => /xmlhttprequest|fetch/.test(r.initiatorType)).length
		)) - avant
	);
}

//// The shipping radios carry class "hide": the visible, clickable thing is the
//// styled label. Clicking the input itself is what a script would do; clicking
//// the label is what a customer does — and only the latter is possible.
async function choisirLivraison(page, index = 0) {
	const radios = page.locator('#step-shipping input[type=radio]');
	if ((await radios.count()) === 0) return null;

	const radio = radios.nth(index);
	if (await radio.isChecked()) return radio.getAttribute('value');

	const id = await radio.getAttribute('id');
	const etiquette = id ? page.locator(`label[for="${cssEchappe(id)}"]`) : null;
	if (etiquette && (await etiquette.count()) && (await etiquette.first().isVisible())) {
		await etiquette.first().click();
	} else {
		//// Fallback: the design does not expose a clickable label.
		await radio.check({force: true});
		await radio.dispatchEvent('change');
	}
	await page.waitForTimeout(3000);
	return radio.getAttribute('value');
}

//// Walk a filled cart from /checkout to the payment step.
//// Shared by every payment scenario so the journey is written once.
async function allerJusquAuPaiement(page) {
	//// Do NOT reload if already on the tunnel: a goto wipes out an address
	//// form that was just filled in, and the next step then stays
	//// unreachable — a failure that blames checkout when it actually comes
	//// from the helper.
	if (!page.url().includes('/checkout')) {
		await page.goto('/checkout');
		await page.waitForLoadState('networkidle');
	}
	await expect(page.locator('#step-address')).toHaveClass(/active/, {timeout: 40_000});

	await page.locator('#step-address .next-step').click();
	//// Filling in an address opens a confirmation dialog (« enregistrer ces
	//// informations ? »). It must be accepted, like a customer would: without
	//// that, the step never advances and the test concludes the tunnel is blocked.
	await confirmerDialogue(page);
	await expect(page.locator('#step-shipping')).toHaveClass(/active/, {timeout: 45_000});

	if ((await page.locator('#step-shipping input[type=radio]').count()) === 0) return false;
	await choisirLivraison(page);

	await page.locator('#step-shipping .next-step').click();
	await expect(page.locator('#step-payment')).toHaveClass(/active/, {timeout: 60_000});
	await expect
		.poll(() => page.locator('.payment-method-item').count(), {timeout: 40_000})
		.toBeGreaterThan(0);
	return true;
}

//// Accept the address-confirmation dialog, if one opened.
////
//// Only appears when the form actually changed — a returning customer who picks
//// a saved card never sees it, a first-time buyer typing their address always
//// does. Silent no-op when there is no dialog.
async function confirmerDialogue(page) {
	const modale = page.locator('.modal.show, .modal.in').first();
	try {
		await modale.waitFor({state: 'visible', timeout: 8000});
	} catch (err) {
		//// Neoffice — comment translated from French to English, no behavior change (4b068b5016 "chore(rule-00): the comments, the docstrings and the last French label leave French behind")
		return false;   // no dialog: nothing to confirm
	}

	const bouton = modale
		.locator('button.btn-primary, .btn-modal-primary, button')
		.filter({hasText: /confirmer|valider|oui|continuer|ok/i})
		.first();
	if ((await bouton.count()) === 0) return false;

	await bouton.click();
	await modale.waitFor({state: 'hidden', timeout: 30_000}).catch(() => {});
	await page.waitForTimeout(2500);
	return true;
}

/** Escape a value for use inside a CSS attribute selector. */
function cssEchappe(valeur) {
	return valeur.replace(/["\\]/g, '\\$&');
}

//// Read the catalogue the way a customer does — from the shop pages.
////
//// The obvious version asked frappe.client.get_list for Website Items and got a
//// clean 403: a Website User is not allowed to list doctypes through the
//// generic API, which is exactly right (see 01-authentification). Every spec
//// that depended on it was silently skipped, and the run still reported
//// "18 passed" — a green suite that tested almost nothing.
async function premierArticleAchetable(page) {
	//// Several candidates: the newest product often is a second-hand unit
	//// (one of a kind, one in stock), which no test can buy twice or keep in
	//// its cart once somebody else has ordered it.
	for (const route of await articlesDuCatalogue(page, 6)) {
		const code = await codeArticleDeLaFiche(page, route);
		if (!code || /-USED-\d+$/.test(code)) continue;
		//// Only the product's own condition block: since the recommendations carousel
		//// badges its used items too, a page-wide count rejected every product whose
		//// neighbours included one, and the whole suite skipped itself.
		if (await page.locator('.product-condition, .wsp-buy .condition-badge, .condition-info').count()) continue;
		return {route, item_code: code};
	}
	return null;
}

//// Routes only — one page load, no matter how many are asked for.
//// Resolving every item_code up front meant navigating to each product page,
//// so asking for 25 candidates cost 26 navigations before a single assertion.
async function articlesDuCatalogue(page, combien = 8) {
	await page.goto('/all-products');
	await page.waitForLoadState('networkidle');

	return page.evaluate((max) => {
		const vues = new Set();
		for (const a of document.querySelectorAll('a[href*="/products/"]')) {
			const chemin = new URL(a.href, location.origin).pathname.replace(/^\//, '');
			if (chemin.startsWith('products/')) vues.add(chemin);
			if (vues.size >= max) break;
		}
		return [...vues];
	}, combien);
}

/** Navigate to a product page and read the item code it carries. */
async function codeArticleDeLaFiche(page, route) {
	await page.goto('/' + route);
	await page.waitForLoadState('domcontentloaded');
	//// The buy button first: the theme's cart drawer lives in the header and
	//// its lines carry data-item-code too.
	return page.evaluate(() => {
		const e =
			document.querySelector('.product-page-content .btn-add-to-cart[data-item-code]') ||
			document.querySelector('.product-page-content [data-item-code]') ||
			document.querySelector('[data-item-code]');
		return e ? e.getAttribute('data-item-code') : null;
	});
}

module.exports = {
	IDENTIFIANTS,
	connecter,
	utilisateurCourant,
	appeler,
	viderPanier,
	compterRequetes,
	choisirLivraison,
	allerJusquAuPaiement,
	confirmerDialogue,
	premierArticleAchetable,
	articlesDuCatalogue,
	codeArticleDeLaFiche,
	lireDevis,
	lireJson,
	lireCarnetAdresses,
	ajouterAuPanier,
};
