//// Neoffice — added file (no upstream equivalent).
//// The checkout, all the way to a real Stripe charge.
////
//// The other specs stop at the payment step. These go through it, against
//// Stripe's TEST key (pk_test_…) with Stripe's public test card numbers: no
//// money moves and no real bank is reached, but everything else is real —
//// a Payment Request is created, the charge is made, and an order comes out.
////
//// They therefore leave real documents on the target site. See README.md
//// (« Ce que ces tests laissent derrière eux ») for how to clean up.

const {test, expect} = require('@playwright/test');
const {
	connecter,
	viderPanier,
	ajouterAuPanier,
	lireDevis,
	allerJusquAuPaiement,
	premierArticleAchetable,
} = require('../fixtures/boutique');
const {CARTES, tuileStripe, remplirCarte, validerPaiement} = require('../fixtures/stripe');

//// Un paiement traverse Stripe puis deux appels serveur: large, mais borné.
const DELAI_PAIEMENT = 90_000;

//// Record what the payment actually did, so a failure says WHY.
////
//// A payment crosses three parties (Stripe's tokenisation, create_payment_request,
//// make_payment); when it stalls, «le devis est resté brouillon» names the
//// symptom and nothing else. This attaches the exchange to the report.
function surveillerPaiement(page) {
	const echanges = [];
	page.on('response', async (r) => {
		if (!/api\.stripe\.com|make_payment|create_payment_request|handle_payment_failure/.test(r.url())) {
			return;
		}
		let corps = '';
		try {
			corps = (await r.text()).slice(0, 300).replace(/\s+/g, ' ');
		} catch (err) {
			corps = '(corps illisible)';
		}
		echanges.push(`${r.status()} ${r.url().split('?')[0].slice(-45)} → ${corps}`);
	});
	page.on('pageerror', (e) => echanges.push(`ERREUR JS: ${String(e).slice(0, 200)}`));
	//// Le formulaire Stripe refuse parfois le clic en le disant UNIQUEMENT dans
	//// la console ("Payment already in progress, ignoring click"): sans cela, un
	//// refus silencieux ressemble à un serveur muet.
	page.on('console', (m) => {
		const texte = m.text();
		if (/payment|paiement|stripe|token|declin|refus/i.test(texte)) {
			echanges.push(`CONSOLE ${m.type()}: ${texte.slice(0, 180)}`);
		}
	});
	return echanges;
}

/** Put exactly one item in the cart, so amounts stay predictable. */
async function panierMinimal(page) {
	await viderPanier(page);
	const article = await premierArticleAchetable(page);
	if (!article) return null;
	await ajouterAuPanier(page, article.item_code, 1);
	const devis = await lireDevis(page);
	return devis && devis.doc ? devis.doc : null;
}

test.describe('Paiement par carte (Stripe, clés de test)', () => {
	test.describe.configure({mode: 'serial'});

	test('un client connecté paie et sa commande est créée', async ({page}) => {
		test.setTimeout(240_000);
		const echanges = surveillerPaiement(page);
		await connecter(page);

		const devis = await panierMinimal(page);
		test.skip(!devis, 'impossible de garnir le panier');
		const nomDevis = devis.name;

		test.skip(!(await allerJusquAuPaiement(page)), 'aucune méthode de livraison disponible');

		const tuile = await remplirCarte(page, CARTES.acceptee);
		await validerPaiement(page, tuile);

		//// Le succès se lit sur le serveur, jamais sur un message d'écran: c'est
		//// la seule preuve qu'une commande existe vraiment.
		await expect
			.poll(async () => etatDuDevis(page, nomDevis), {
				timeout: DELAI_PAIEMENT,
				message: () =>
					'le devis n’a jamais été transformé en commande. Échanges :\n' +
					(echanges.length ? echanges.join('\n') : '(aucun appel de paiement observé)'),
			})
			.not.toBe('brouillon');

		//// Et le client doit être emmené ailleurs que sur le formulaire de carte.
		await expect
			.poll(() => page.url(), {timeout: 30_000, message: 'le client reste sur le checkout'})
			.not.toContain('/checkout');
	});

	//// Ce test a mis au jour trois défauts, tous corrigés depuis:
	////
	//// 1. `window.stripe = true` servait de garde « déjà initialisé », alors
	////    qu'il ne dit rien du chargement de Stripe.js. Au second rendu du
	////    gabarit, initStripe() partait avant que `window.Stripe` existe et
	////    laissait un formulaire de carte inerte.
	//// 2. Les six frappe.call du gabarit n'avaient AUCUN handler `error`: sur un
	////    404 ou un délai dépassé, ni la branche succès ni la branche erreur ne
	////    s'exécutaient — écran figé, aucun message.
	//// 3. showMessagePayment() écrivait dans le PREMIER `.error.payment-message`
	////    du document, qui appartient à la première méthode de la liste et non à
	////    celle qu'on paie: le message existait dans le DOM, replié dans une
	////    tuile non sélectionnée, et le client ne voyait rien.
	////
	//// Toute la chaîne s'exécute désormais (create_payment_request →
	//// make_payment → handle_payment_failure) et le refus s'affiche.
	test('une carte refusée affiche un message et ne crée pas de commande', async ({page}) => {
		test.setTimeout(240_000);
		const echanges = surveillerPaiement(page);
		await connecter(page);

		const devis = await panierMinimal(page);
		test.skip(!devis, 'impossible de garnir le panier');
		const nomDevis = devis.name;

		test.skip(!(await allerJusquAuPaiement(page)), 'aucune méthode de livraison disponible');

		const tuile = await remplirCarte(page, CARTES.refusee);
		await validerPaiement(page, tuile);

		//// Un refus doit se VOIR. Le pire échec de paiement est celui qui laisse
		//// le client devant un écran inerte, sans savoir s'il a payé.
		////
		//// Le message peut venir de la tuile (erreur de tokenisation Stripe) ou
		//// d'un msgprint Frappe (refus au moment du débit, côté serveur): les
		//// deux comptent, seul le silence est un défaut.
		const lireMessages = () =>
			page.evaluate(() =>
				[
					...document.querySelectorAll(
						'.payment-method-item.selected .payment-message, ' +
							'.payment-method-item.selected [role="alert"], ' +
							'.modal.show, .msgprint, .alert-danger, #payment-error'
					),
				]
					.filter((z) => z.offsetHeight > 0 && z.textContent.trim().length > 3)
					.map((z) => z.textContent.trim().slice(0, 120))
			);

		let messages = [];
		const limite = Date.now() + DELAI_PAIEMENT;
		while (Date.now() < limite) {
			messages = await lireMessages();
			if (messages.length) break;
			await page.waitForTimeout(2000);
		}

		//// Playwright n'évalue pas une fonction message dans .poll: le diagnostic
		//// est construit ici, sinon l'échec ne dit que « attendu true, reçu false ».
		await test.info().attach('echanges-paiement', {
			body: echanges.join('\n') || '(aucun appel observé)',
			contentType: 'text/plain',
		});
		expect(
			messages.length,
			`refus de carte sans message visible. Échanges :\n${echanges.join('\n') || '(aucun)'}`
		).toBeGreaterThan(0);

		//// Et surtout: rien ne doit avoir été commandé.
		expect(await etatDuDevis(page, nomDevis), 'une commande a été créée malgré le refus').toBe(
			'brouillon'
		);
		expect(page.url(), 'le client a été emmené ailleurs malgré l’échec').toContain('/checkout');
	});

	test('le bouton de paiement ne peut pas être cliqué deux fois', async ({page}) => {
		test.setTimeout(240_000);
		await connecter(page);

		const devis = await panierMinimal(page);
		test.skip(!devis, 'impossible de garnir le panier');
		test.skip(!(await allerJusquAuPaiement(page)), 'aucune méthode de livraison disponible');

		const tuile = await remplirCarte(page, CARTES.acceptee);
		const bouton = tuile.locator('.btn-submit-payment:visible').first();
		//// Passe par validerPaiement, qui re-sélectionne la tuile si le
		//// rafraîchissement des méthodes la lui a fait perdre — sans quoi le
		//// clic échoue sur un bouton verrouillé, pour une raison qui n'a rien à
		//// voir avec le double-clic qu'on veut éprouver.
		await validerPaiement(page, tuile);

		//// Double paiement = double débit. Le bouton doit se verrouiller dès le
		//// premier clic, avant même que Stripe ait répondu.
		await expect
			.poll(async () => bouton.isDisabled().catch(() => true), {
				timeout: 20_000,
				message: 'le bouton reste cliquable après le premier clic',
			})
			.toBe(true);
	});
});

test.describe('Conditions générales', () => {
	test('payer sans accepter les conditions est refusé', async ({page}) => {
		test.setTimeout(240_000);
		await connecter(page);

		const devis = await panierMinimal(page);
		test.skip(!devis, 'impossible de garnir le panier');
		const nomDevis = devis.name;
		test.skip(!(await allerJusquAuPaiement(page)), 'aucune méthode de livraison disponible');

		const tuile = await remplirCarte(page, CARTES.acceptee);
		const conditions = tuile.locator('#terms-acceptance').first();
		test.skip((await conditions.count()) === 0, 'pas de case de conditions sur ce site');

		//// La tuile doit être sélectionnée pour que le gestionnaire des
		//// conditions s'applique: sans cela, décocher ne verrouille rien et le
		//// test échoue en accusant l'application d'accepter un paiement sans CGV.
		if (!(await tuile.evaluate((e) => e.classList.contains('selected')))) {
			await tuile.click();
			await page.waitForTimeout(2000);
		}
		await conditions.uncheck();
		await expect(conditions).not.toBeChecked();

		//// Le refus se manifeste par un bouton VERROUILLÉ, pas par un clic qui
		//// échoue. Tenter de cliquer ici échouait sur « element is disabled » —
		//// ce qui est précisément la preuve attendue, mais lue comme un échec.
		const bouton = tuile.locator('.btn-submit-payment:visible').first();
		await expect(bouton, 'payer reste possible sans accepter les conditions').toBeDisabled();

		expect(
			await etatDuDevis(page, nomDevis),
			'commande passée sans acceptation des conditions'
		).toBe('brouillon');
	});
});

//// Read the quotation's real state from the server.
////
//// docstatus 0 = brouillon (panier), 1 = validé (commandé), 2 = annulé.
//// A cart that is still a draft after a payment means no order was created.
async function etatDuDevis(page, nom) {
	const r = await page.request.post(
		'/api/method/webshop.webshop.shopping_cart.cart.get_cart_quotation'
	);
	if (!r.ok()) return 'illisible';
	const devis = (await r.json()).message;
	//// Après une commande, get_cart_quotation ouvre un NOUVEAU panier vide:
	//// que le devis d'origine ne soit plus le panier courant est déjà la preuve
	//// qu'il a été consommé.
	const courant = devis && devis.doc ? devis.doc.name : null;
	if (courant && courant !== nom) return 'commande';
	const lignes = devis && devis.doc ? devis.doc.items || [] : [];
	return lignes.length ? 'brouillon' : 'vide';
}
