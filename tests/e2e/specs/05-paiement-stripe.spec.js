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

//// A payment goes through Stripe then two server calls: generous, but bounded.
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
	//// The Stripe form sometimes refuses the click and only says so in the
	//// console ("Payment already in progress, ignoring click"): without this, a
	//// silent refusal looks just like a mute server.
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

		//// Success is read from the server, never from an on-screen message: that
		//// is the only proof an order genuinely exists.
		await expect
			.poll(async () => etatDuDevis(page, nomDevis), {
				timeout: DELAI_PAIEMENT,
				message: () =>
					'le devis n’a jamais été transformé en commande. Échanges :\n' +
					(echanges.length ? echanges.join('\n') : '(aucun appel de paiement observé)'),
			})
			.not.toBe('brouillon');

		//// And the customer must be taken somewhere other than the card form.
		await expect
			.poll(() => page.url(), {timeout: 30_000, message: 'le client reste sur le checkout'})
			.not.toContain('/checkout');
	});

	//// This test uncovered three defects, all fixed since:
	////
	//// 1. `window.stripe = true` acted as an "already initialized" guard, yet
	////    it said nothing about whether Stripe.js had actually loaded. On the
	////    template's second render, initStripe() would run before
	////    `window.Stripe` existed, leaving the card form inert.
	//// 2. The template's six frappe.call calls had NO `error` handler at all: on
	////    a 404 or a timeout, neither the success nor the error branch would
	////    run — a frozen screen, no message.
	//// 3. showMessagePayment() wrote into the FIRST `.error.payment-message` in
	////    the document, which belongs to the first method in the list rather
	////    than the one being paid: the message existed in the DOM, folded away
	////    in a tile that wasn't selected, and the customer saw nothing.
	////
	//// The whole chain now runs (create_payment_request →
	//// make_payment → handle_payment_failure) and the decline is displayed.
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

		//// A decline must be SEEN. The worst payment failure is one that leaves
		//// the customer in front of an inert screen, with no idea whether they paid.
		////
		//// The message can come from the tile (a Stripe tokenisation error) or
		//// from a Frappe msgprint (declined at the time of the charge, server
		//// side): both count, only silence is a defect.
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

		//// Playwright does not evaluate a message function inside .poll: the
		//// diagnosis is built here, otherwise the failure just says "expected true, got false".
		await test.info().attach('echanges-paiement', {
			body: echanges.join('\n') || '(aucun appel observé)',
			contentType: 'text/plain',
		});
		expect(
			messages.length,
			`refus de carte sans message visible. Échanges :\n${echanges.join('\n') || '(aucun)'}`
		).toBeGreaterThan(0);

		//// And above all: nothing must have been ordered.
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
		//// Goes through validerPaiement, which re-selects the tile if the
		//// methods refresh made it lose that state — without which the click
		//// fails on a locked button, for a reason that has nothing to do with
		//// the double-click being tested.
		await validerPaiement(page, tuile);

		//// Double payment = double charge. The button must lock on the very
		//// first click, even before Stripe has responded.
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
		const conditions = tuile.locator('.terms-acceptance').first();
		test.skip((await conditions.count()) === 0, 'pas de case de conditions sur ce site');

		//// The tile must be selected for the terms handler to apply: without
		//// that, unchecking locks nothing and the test fails, wrongly blaming the
		//// app for accepting a payment without accepting the terms.
		if (!(await tuile.evaluate((e) => e.classList.contains('selected')))) {
			await tuile.click();
			await page.waitForTimeout(2000);
		}
		await conditions.uncheck();
		await expect(conditions).not.toBeChecked();

		//// The refusal shows up as a LOCKED button, not as a click that fails.
		//// Trying to click here used to fail on « element is disabled » —
		//// which is precisely the expected proof, yet read as a failure.
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
//// docstatus 0 = brouillon (cart), 1 = validé (ordered), 2 = annulé.
//// A cart that is still a draft after a payment means no order was created.
async function etatDuDevis(page, nom) {
	const r = await page.request.post(
		'/api/method/webshop.webshop.shopping_cart.cart.get_cart_quotation'
	);
	if (!r.ok()) return 'illisible';
	const devis = (await r.json()).message;
	//// After an order, get_cart_quotation opens a NEW empty cart: the fact that
	//// the original quotation is no longer the current cart is already the
	//// proof that it was consumed.
	const courant = devis && devis.doc ? devis.doc.name : null;
	if (courant && courant !== nom) return 'commande';
	const lignes = devis && devis.doc ? devis.doc.items || [] : [];
	return lignes.length ? 'brouillon' : 'vide';
}
