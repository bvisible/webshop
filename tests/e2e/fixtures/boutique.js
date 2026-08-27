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
	const reponse = await page.request.post('/api/method/login', {
		form: {usr: identifiants.utilisateur, pwd: identifiants.motDePasse},
	});
	expect(
		reponse.ok(),
		`connexion refusée (${reponse.status()}) — limite de tentatives Frappe ?`
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
	const devis = await lireDevis(page);
	const lignes = (devis && devis.doc && devis.doc.items) || [];
	//// En série volontairement: deux update_cart concurrents écrivent le même
	//// devis et le dernier écrase le premier.
	for (const ligne of lignes) {
		await page.request.post('/api/method/webshop.webshop.shopping_cart.cart.update_cart', {
			form: {
				item_code: ligne.item_code,
				qty: 0,
				...(ligne.warehouse ? {warehouse: ligne.warehouse} : {}),
			},
		});
	}
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
		//// Repli: le design n'expose pas de label cliquable.
		await radio.check({force: true});
		await radio.dispatchEvent('change');
	}
	await page.waitForTimeout(3000);
	return radio.getAttribute('value');
}

//// Walk a filled cart from /checkout to the payment step.
//// Shared by every payment scenario so the journey is written once.
async function allerJusquAuPaiement(page) {
	//// Ne recharge PAS si l'on est déjà sur le tunnel: un goto efface un
	//// formulaire d'adresse qui vient d'être saisi, et l'étape suivante reste
	//// alors inaccessible — un échec qui accuse le checkout alors qu'il vient
	//// du helper.
	if (!page.url().includes('/checkout')) {
		await page.goto('/checkout');
		await page.waitForLoadState('networkidle');
	}
	await expect(page.locator('#step-address')).toHaveClass(/active/, {timeout: 40_000});

	await page.locator('#step-address .next-step').click();
	//// Saisir une adresse ouvre un dialogue de confirmation (« enregistrer ces
	//// informations ? »). Il faut le valider, comme le client: sans cela l'étape
	//// ne bascule jamais et le test conclut à un tunnel bloqué.
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
		return false;   // pas de dialogue: rien à confirmer
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
	const [route] = await articlesDuCatalogue(page, 1);
	if (!route) return null;
	const code = await codeArticleDeLaFiche(page, route);
	return code ? {route, item_code: code} : null;
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
	return page.evaluate(() => {
		const e = document.querySelector('[data-item-code]');
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
