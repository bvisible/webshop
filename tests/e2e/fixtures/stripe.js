//// Neoffice — added file (no upstream equivalent).
//// Driving the Stripe payment form.
////
//// The card numbers below are Stripe's PUBLIC test numbers, documented at
//// https://docs.stripe.com/testing. They are not anyone's card: they only work
//// against a test key (the site runs pk_test_…), move no money, and reach no
//// real bank. Never put a real card number in this file.

const {expect} = require('@playwright/test');

const CARTES = {
	//// Payment accepted immediately, without 3-D Secure.
	acceptee: '4242424242424242',
	//// Generic issuer decline — the customer must see a message, not a frozen screen.
	refusee: '4000000000000002',
	//// Insufficient funds.
	fondsInsuffisants: '4000000000009995',
};

/** The payment method tile whose title mentions Stripe. */
function tuileStripe(page) {
	return page.locator('.payment-method-item').filter({hasText: /stripe/i }).first();
}

//// Select Stripe and fill the card form.
////
//// The card fields live in an iframe served by Stripe: they are deliberately
//// unreachable from the page's own JavaScript (that is the point of Elements),
//// so they are driven through frameLocator.
async function remplirCarte(page, numero, {nom = 'Test E2E', email = 'test.e2e@example.com'} = {}) {
	const tuile = tuileStripe(page);
	await expect(tuile, 'aucune méthode Stripe proposée').toHaveCount(1);
	await tuile.click();

	//// The form is mounted only after selection, and Stripe.js loads from its
	//// CDN: wait for the field, not a fixed delay.
	const porteur = tuile.locator('#cardholder-name');
	await expect(porteur).toBeVisible({timeout: 30_000});
	await porteur.fill(nom);
	await tuile.locator('#cardholder-email').fill(email);

	const cadre = tuile.frameLocator('[name="card-element"] iframe').first();
	await cadre.locator('input[name="cardnumber"]').fill(numero);
	await cadre.locator('input[name="exp-date"]').fill(dateFuture());
	await cadre.locator('input[name="cvc"]').fill('123');
	//// Some configurations also require the postal code.
	const postal = cadre.locator('input[name="postal"]');
	if (await postal.count()) await postal.fill('1003');

	await accepterConditions(tuile);
	return tuile;
}

//// Tick the terms box.
////
//// This used to click the LABEL, because the handler in checkout.js listened
//// for "change click" on both the box and the label and flipped the box by
//// hand: check() ticked it, the handler fired and untickd it, and "Payer"
//// stayed disabled. That double-flip made the box genuinely unreliable — for a
//// customer too, not just for a test — and has been fixed in checkout.js, so
//// the box is now a plain checkbox and check() is enough.
////
//// Scoped to the Stripe tile, and matched by CLASS. The id used to be
//// `terms-acceptance` on every method at once — five elements sharing one id,
//// so each `<label for>` bound to the first box in the document and clicking
//// Wallee's label ticked Facture's. The id is now keyed on the method
//// (`terms-submit_wallee`); `.terms-acceptance` is what every tile has in
//// common.
async function accepterConditions(tuile) {
	const cases = tuile.locator('.terms-acceptance');
	if ((await cases.count()) === 0) return;

	const boite = cases.first();
	if (!(await boite.isChecked())) await boite.check();
	await expect(boite, 'les conditions n’ont pas pu être acceptées').toBeChecked();
}

//// Submit the Stripe form.
////
//// Re-asserts the tile is still selected first. The payment step reloads its
//// method list while the customer is filling the card in, and the tile can lose
//// its `selected` class — at which point the terms handler, which is bound to
//// `.payment-method-item.selected .terms-acceptance`, stops applying and the
//// Pay button is never enabled, with the form still sitting there fully filled.
//// Seen in test as a disabled button on a completed form; a customer would see
//// exactly the same thing.
async function validerPaiement(page, tuile) {
	const bouton = tuile.locator('.btn-submit-payment:visible').first();

	//// Up to three attempts: the refresh can kick in again mid re-selection.
	//// A real customer would also click again.
	for (let essai = 1; essai <= 3; essai += 1) {
		if (await bouton.isEnabled().catch(() => false)) break;
		if (!(await tuile.evaluate((e) => e.classList.contains('selected')))) {
			await tuile.click();
			await page.waitForTimeout(2000);
		}
		await accepterConditions(tuile);
		await page.waitForTimeout(1500);
	}

	await expect(
		bouton,
		'le bouton « Payer » est resté verrouillé : la tuile a perdu sa sélection ' +
			'pendant la saisie (rafraîchissement des méthodes de paiement)'
	).toBeEnabled({timeout: 30_000});
	await bouton.click();
}

/** MM/YY two years out — a card must not expire mid-suite. */
function dateFuture() {
	const d = new Date();
	const annee = String((d.getFullYear() + 2) % 100).padStart(2, '0');
	return `12${annee}`;
}

module.exports = {
	CARTES,
	tuileStripe,
	remplirCarte,
	accepterConditions,
	validerPaiement,
	dateFuture,
};
