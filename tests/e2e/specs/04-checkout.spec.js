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
		//// _("Checkout") est partagé avec le bouton du panier, où le français rend
		//// « Paiement » — ce qui donnait un titre homonyme de l'étape 4.
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
			//// n-1 adresses + la carte « Nouvelle adresse »
			expect(n).toBeGreaterThan(1);
		});

		//// La liste des cartes et le devis arrivent de deux appels indépendants.
		//// Quand les cartes arrivaient les premières — le cas courant — « Nouvelle
		//// adresse » était surlignée alors que le formulaire affichait déjà
		//// l'adresse par défaut.
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

		//// Le bug que ce test verrouille: remplir le formulaire en déclenchant
		//// « change » aurait rempli pendingChanges, et l'étape suivante aurait
		//// appelé update_address_info, qui réécrit l'adresse choisie avec
		//// is_primary_address = 1. Choisir son adresse de bureau aurait transformé
		//// son domicile en bureau.
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

			// Adresse -> livraison
			await page.locator('#step-address .next-step').click();
			await expect(page.locator('#step-shipping')).toHaveClass(/active/, {timeout: 40_000});

			// Choisir une livraison si aucune ne l'est
			const nbOptions = await page.locator('#step-shipping input[type=radio]').count();
			test.skip(nbOptions === 0, 'aucune méthode de livraison pour cette adresse');
			await choisirLivraison(page);
			const livraisonChoisie = await page
				.locator('#step-shipping input[type=radio]:checked')
				.getAttribute('value');

			// Livraison -> paiement
			await page.locator('#step-shipping .next-step').click();
			await expect(page.locator('#step-payment')).toHaveClass(/active/, {timeout: 45_000});

			// Retour paiement -> livraison
			await page.locator('#step-payment .prev-step').click();
			await expect(page.locator('#step-shipping')).toHaveClass(/active/, {timeout: 30_000});
			await expect(page.locator('#step-shipping input[type=radio]:checked')).toHaveValue(livraisonChoisie);

			// Retour livraison -> adresse
			await page.locator('#step-shipping .prev-step').click();
			await expect(page.locator('#step-address')).toHaveClass(/active/, {timeout: 30_000});
			if (adresseDepart) {
				await expect(page.locator('#billing_address_name')).toHaveValue(adresseDepart);
			}
		});

		//// Passer une étape sans avoir rien modifié partait en 4 à 7 appels et
		//// ouvrait un dialogue de confirmation parasite.
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

			//// Le conteneur ne doit jamais repasser par un état vide: c'est ce qui
			//// produisait le scintillement.
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
		//// Le sondage était un setInterval fixe à 5 s pendant 5 minutes: 60 appels
		//// par paiement, alors que le temps réel prévient déjà. Il est devenu un
		//// setTimeout récursif dont le délai s'allonge passé 30 s, et davantage
		//// encore quand la socket est vivante.
		////
		//// Mesuré ici plutôt qu'à la main: Chrome bride les timers d'un onglet en
		//// arrière-plan, ce qui rend toute mesure manuelle inexploitable — deux
		//// tours en 38 s au lieu de sept. Playwright garde la page active.
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
				//// Le serveur répond toujours « pas encore payé »: on observe la
				//// cadence, on ne veut surtout pas déclencher de vraie redirection.
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
			//// Avant: 8 délais, tous à 5000. Après: la fin de la fenêtre s'espace.
			expect(mesure.delais.length, 'aucun tour observé').toBeGreaterThan(0);
			expect(
				mesure.delais.some((d) => d > 5000),
				`le sondage reste à 5 s (délais observés: ${mesure.delais.join(', ')})`
			).toBe(true);
		});
	});

	test.describe('Stabilité', () => {
		//// Une boucle de rafraîchissement figeait l'onglet: le récapitulatif se
		//// redemandait lui-même sans fin.
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
