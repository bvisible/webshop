//// Neoffice — added file (no upstream equivalent).
//// The four-step checkout. This is the file that replaces the hand-run browser
//// scripts of the 2026-08 reliability pass: every claim written in
//// 09-Checkout-Fiabilisation is asserted here so it can be re-checked at will.

const {test, expect} = require('@playwright/test');
const {
	connecter,
	compterRequetes,
	ajouterAuPanier,
	lireDevis,
	lireCarnetAdresses,
	choisirLivraison,
	premierArticleAchetable,
} = require('../fixtures/boutique');

/** Ensure the cart holds something, so /checkout is reachable at all. */
async function garantirPanierNonVide(page) {
	const devis = await lireDevis(page);
	if (devis && devis.doc && (devis.doc.items || []).length) return true;

	const article = await premierArticleAchetable(page);
	if (!article) return false;
	await ajouterAuPanier(page, article.item_code, 1);
	const apres = await lireDevis(page);
	return !!(apres && apres.doc && (apres.doc.items || []).length);
}

test.describe('Tunnel de commande', () => {
	test.beforeEach(async ({page}) => {
		await connecter(page);
		await page.goto('/cart');
		await page.waitForLoadState('networkidle');
		const pret = await garantirPanierNonVide(page);
		test.skip(!pret, 'impossible de garnir le panier sur ce site');

		await page.goto('/checkout');
		await page.waitForLoadState('networkidle');
		await expect(page.locator('#step-address')).toHaveClass(/active/, {timeout: 30_000});
		await remettreAdresseParDefaut(page);
	});

	test('le titre de page ne reprend pas le nom d’une étape', async ({page}) => {
		//// _("Checkout") is shared with the cart button, where French renders it
		//// as « Paiement » — which produced a title matching step 4's name.
		const titre = (await page.locator('h1').first().textContent()).trim();
		expect(titre.toLowerCase()).not.toBe('paiement');
	});

	test('les quatre étapes sont présentes', async ({page}) => {
		for (const etape of ['step-address', 'step-shipping', 'step-payment']) {
			await expect(page.locator('#' + etape)).toHaveCount(1);
		}
	});

	test.describe('Carnet d’adresses', () => {
		test('les adresses du client sont proposées en cartes', async ({page}) => {
			const cartes = page.locator('#billing-address-picker .address-card-choice');
			const n = await cartes.count();
			test.skip(n === 0, 'ce compte n’a aucune adresse enregistrée');
			//// n-1 addresses + the « Nouvelle adresse » card
			expect(n).toBeGreaterThan(1);
		});

		//// The card list and the quotation come from two independent calls. When
		//// the cards arrived first — the common case — « Nouvelle
		//// adresse » was highlighted while the form already showed the default
		//// address.
		test('la carte surlignée correspond au devis, dès le chargement', async ({page}) => {
			const champ = await page.locator('#billing_address_name').inputValue();
			test.skip(!champ, 'le devis n’a pas encore d’adresse');

			const selectionnee = page.locator('#billing-address-picker .is-selected');
			await expect(selectionnee, 'aucune carte surlignée').toHaveCount(1);
			await expect(selectionnee).toHaveAttribute('data-address', champ);
			await expect(
				selectionnee,
				'« Nouvelle adresse » surlignée alors que le devis a une adresse'
			).not.toHaveClass(/address-card-choice--new/);
		});

		//// The bug this test locks in: filling in the form while triggering a
		//// « change » event would have populated pendingChanges, and the next
		//// step would have called update_address_info, which overwrites the
		//// chosen address with is_primary_address = 1. Choosing your office
		//// address would have turned your home into an office.
		test('choisir une adresse ne la modifie pas', async ({page}) => {
			const cartes = page.locator('#billing-address-picker .address-card-choice:not(.address-card-choice--new)');
			test.skip((await cartes.count()) < 2, 'moins de deux adresses: rien à choisir');

			const avant = await lireCarnetAdresses(page);
			const cible = await cartes.nth(1).getAttribute('data-address');

			await cartes.nth(1).click();
			await expect(page.locator('#billing_address_name')).toHaveValue(cible, {timeout: 20_000});

			const apres = await lireCarnetAdresses(page);
			expect(normaliser(apres), 'la sélection a modifié une adresse').toEqual(normaliser(avant));
		});

		test('choisir une adresse ne coûte qu’un appel', async ({page}) => {
			const cartes = page.locator('#billing-address-picker .address-card-choice:not(.address-card-choice--new)');
			test.skip((await cartes.count()) < 2, 'moins de deux adresses');

			const n = await compterRequetes(page, async () => {
				await cartes.nth(1).click();
				await page.waitForTimeout(3000);
			});
			expect(n, 'la sélection déclenche trop d’appels').toBeLessThanOrEqual(3);
		});
	});

	test.describe('Progression et retours', () => {
		test('on avance jusqu’au paiement et on revient sans rien perdre', async ({page}) => {
			const adresseDepart = await page.locator('#billing_address_name').inputValue();

			// Address -> shipping
			await page.locator('#step-address .next-step').click();
			await expect(page.locator('#step-shipping')).toHaveClass(/active/, {timeout: 40_000});

			// Choose a shipping method if none is selected
			const nbOptions = await page.locator('#step-shipping input[type=radio]').count();
			test.skip(nbOptions === 0, 'aucune méthode de livraison pour cette adresse');
			await choisirLivraison(page);
			const livraisonChoisie = await page
				.locator('#step-shipping input[type=radio]:checked')
				.getAttribute('value');

			// Shipping -> payment
			await page.locator('#step-shipping .next-step').click();
			await expect(page.locator('#step-payment')).toHaveClass(/active/, {timeout: 45_000});

			// Back payment -> shipping
			await page.locator('#step-payment .prev-step').click();
			await expect(page.locator('#step-shipping')).toHaveClass(/active/, {timeout: 30_000});
			await expect(page.locator('#step-shipping input[type=radio]:checked')).toHaveValue(livraisonChoisie);

			// Back shipping -> address
			await page.locator('#step-shipping .prev-step').click();
			await expect(page.locator('#step-address')).toHaveClass(/active/, {timeout: 30_000});
			if (adresseDepart) {
				await expect(page.locator('#billing_address_name')).toHaveValue(adresseDepart);
			}
		});

		//// Passing a step without changing anything used to fire off 4 to 7 calls
		//// and open a spurious confirmation dialog.
		test('avancer sans rien modifier ne redemande rien', async ({page}) => {
			const n = await compterRequetes(page, async () => {
				await page.locator('#step-address .next-step').click();
				await expect(page.locator('#step-shipping')).toHaveClass(/active/, {timeout: 40_000});
			});
			expect(n, 'trop d’appels pour une étape sans modification').toBeLessThanOrEqual(6);
		});
	});

	test.describe('Étape paiement', () => {
		test('les méthodes de paiement s’affichent sans écran vide', async ({page}) => {
			await page.locator('#step-address .next-step').click();
			await expect(page.locator('#step-shipping')).toHaveClass(/active/, {timeout: 40_000});

			const nbOptions = await page.locator('#step-shipping input[type=radio]').count();
			test.skip(nbOptions === 0, 'aucune méthode de livraison');
			await choisirLivraison(page);

			//// The container must never pass back through an empty state: that is
			//// what caused the flicker.
			await page.evaluate(() => {
				window.__vides = 0;
				const cible = document.querySelector('#payment-methods-container');
				if (!cible) return;
				new MutationObserver(() => {
					if (!cible.innerHTML.trim()) window.__vides += 1;
				}).observe(cible, {childList: true, subtree: true});
			});

			await page.locator('#step-shipping .next-step').click();
			await expect(page.locator('#step-payment')).toHaveClass(/active/, {timeout: 45_000});

			await expect
				.poll(async () => page.locator('.payment-method-item').count(), {
					timeout: 30_000,
					message: 'aucune méthode de paiement rendue',
				})
				.toBeGreaterThan(0);

			expect(await page.evaluate(() => window.__vides || 0), 'scintillement revenu').toBe(0);
		});
	});

	test.describe('Surveillance du paiement', () => {
		//// The polling used to be a fixed 5 s setInterval for 5 minutes: 60 calls
		//// per payment, even though the realtime socket already gives notice. It
		//// has become a recursive setTimeout whose delay stretches out past 30 s,
		//// and even more once the socket is alive.
		////
		//// Measured here rather than by hand: Chrome throttles a background tab's
		//// timers, which makes any manual measurement useless — two rounds in
		//// 38 s instead of seven. Playwright keeps the page active.
		test('le sondage s’espace au lieu de marteler toutes les 5 s', async ({page}) => {
			test.setTimeout(120_000);

			const mesure = await page.evaluate(async () => {
				const cm = window.checkout_manager;
				if (!cm || !cm.watchIntent) return null;
				cm.stopIntentWatch();

				const delais = [];
				const stOrig = window.setTimeout;
				const callOrig = frappe.call;
				window.setTimeout = function (fn, d) {
					if (d >= 4000) delais.push(d);
					return stOrig.apply(this, arguments);
				};
				//// The server always answers "not yet paid": we're observing the
				//// cadence, and specifically do not want to trigger a real redirect.
				frappe.call = function (o) {
					if (o && /cart_intent_state/.test(o.method || '')) {
						if (o.callback) o.callback({message: {done: false}});
						return;
					}
					return callOrig.apply(this, arguments);
				};

				const faux = $('<div><span class="intent-attente"></span></div>');
				cm.watchIntent('E2E-CADENCE', faux);
				await new Promise((r) => stOrig(r, 40000));
				cm.stopIntentWatch();

				window.setTimeout = stOrig;
				frappe.call = callOrig;
				return {delais, fuite: !!cm._intentStop};
			});

			test.skip(!mesure, 'checkout_manager indisponible');

			expect(mesure.fuite, 'la surveillance ne s’est pas arrêtée').toBe(false);
			//// Before: 8 delays, all at 5000. After: the tail of the window spaces out.
			expect(mesure.delais.length, 'aucun tour observé').toBeGreaterThan(0);
			expect(
				mesure.delais.some((d) => d > 5000),
				`le sondage reste à 5 s (délais observés: ${mesure.delais.join(', ')})`
			).toBe(true);
		});
	});

	test.describe('Stabilité', () => {
		//// A refresh loop used to freeze the tab: the summary kept re-requesting
		//// itself endlessly.
		test('la page ne boucle pas au repos', async ({page}) => {
			const n = await compterRequetes(page, () => page.waitForTimeout(6000));
			expect(n, 'la page continue d’appeler le serveur sans rien faire').toBeLessThanOrEqual(3);
		});

		test('aucune erreur de script', async ({page}) => {
			const erreurs = [];
			page.on('pageerror', (e) => erreurs.push(e.message));
			await page.reload();
			await page.waitForLoadState('networkidle');
			await page.waitForTimeout(3000);
			expect(erreurs).toEqual([]);
		});
	});
});

//// Put the quotation back on the customer's default address.
////
//// Without this, a spec that picks another address leaves it on the quotation
//// for the next one — and a spec further down was skipped with "no shipping
//// method for this address", silently, because the address it inherited had
//// none. A skipped test reads like a passing one in the summary.
async function remettreAdresseParDefaut(page) {
	const cartes = page.locator(
		'#billing-address-picker .address-card-choice:not(.address-card-choice--new)'
	);
	if ((await cartes.count()) === 0) return;

	const premiere = cartes.first();
	if (await premiere.evaluate((e) => e.classList.contains('is-selected'))) return;

	await premiere.click();
	const attendue = await premiere.getAttribute('data-address');
	await expect(page.locator('#billing_address_name')).toHaveValue(attendue, {timeout: 20_000});
}

/** Comparable snapshot of the address book, order-independent. */
function normaliser(adresses) {
	return ((adresses || []).map((a) => ({
		name: a.name,
		type: a.address_type,
		ligne1: a.address_line1,
		ville: a.city,
		npa: a.pincode,
		pays: a.country,
		principale: a.is_primary_address,
		livraison: a.is_shipping_address,
	})) || []).sort((x, y) => (x.name > y.name ? 1 : -1));
}
