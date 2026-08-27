//// Neoffice — added file (no upstream equivalent).
//// Driving the Stripe payment form.
////
//// The card numbers below are Stripe's PUBLIC test numbers, documented at
//// https://docs.stripe.com/testing. They are not anyone's card: they only work
//// against a test key (the site runs pk_test_…), move no money, and reach no
//// real bank. Never put a real card number in this file.

const {expect} = require('@playwright/test');

const CARTES = {
	//// Paiement accepté immédiatement, sans 3-D Secure.
	acceptee: '4242424242424242',
	//// Refus générique de l'émetteur — le client doit voir un message, pas un écran figé.
	refusee: '4000000000000002',
	//// Fonds insuffisants.
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

	//// Le formulaire n'est monté qu'après sélection, et Stripe.js se charge
	//// depuis son CDN: attendre le champ, pas un délai.
	const porteur = tuile.locator('#cardholder-name');
	await expect(porteur).toBeVisible({timeout: 30_000});
	await porteur.fill(nom);
	await tuile.locator('#cardholder-email').fill(email);

	const cadre = tuile.frameLocator('[name="card-element"] iframe').first();
	await cadre.locator('input[name="cardnumber"]').fill(numero);
	await cadre.locator('input[name="exp-date"]').fill(dateFuture());
	await cadre.locator('input[name="cvc"]').fill('123');
	//// Certaines configurations demandent aussi le code postal.
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
//// #terms-acceptance is duplicated (one per payment method), so this is always
//// scoped to the Stripe tile.
async function accepterConditions(tuile) {
	const cases = tuile.locator('#terms-acceptance');
	if ((await cases.count()) === 0) return;

	const boite = cases.first();
	if (!(await boite.isChecked())) await boite.check();
	await expect(boite, 'les conditions n’ont pas pu être acceptées').toBeChecked();
}

/** Submit the Stripe form and wait for the outcome. */
async function validerPaiement(page, tuile) {
	const bouton = tuile.locator('.btn-submit-payment:visible').first();
	await expect(bouton).toBeEnabled();
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
