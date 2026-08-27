// Exploration: structure reelle de l'etape paiement + iframe Stripe.
const {chromium} = require('@playwright/test');
const fs = require('fs');
const os = require('os');
const path = require('path');

for (const l of fs.readFileSync(path.join(os.homedir(), '.config/webshop-e2e.env'), 'utf8').split('\n')) {
	const m = l.match(/^([A-Z0-9_]+)=(.*)$/);
	if (m) process.env[m[1]] = m[2];
}
const BASE = process.env.WEBSHOP_E2E_URL;

(async () => {
	const nav = await chromium.launch();
	const ctx = await nav.newContext({baseURL: BASE, locale: 'fr-CH'});
	const page = await ctx.newPage();

	await page.request.post('/api/method/login', {
		form: {usr: process.env.WEBSHOP_E2E_USER, pwd: process.env.WEBSHOP_E2E_PASSWORD},
	});

	// Garnir le panier
	const devis = await page.request.post('/api/method/webshop.webshop.shopping_cart.cart.get_cart_quotation');
	const doc = (await devis.json()).message;
	if (!doc || !doc.doc || !(doc.doc.items || []).length) {
		await page.goto('/all-products');
		const route = await page.evaluate(() => {
			const a = document.querySelector('a[href*="/products/"]');
			return a ? new URL(a.href, location.origin).pathname : null;
		});
		await page.goto(route);
		const code = await page.evaluate(
			() => document.querySelector('[data-item-code]')?.getAttribute('data-item-code')
		);
		await page.request.post('/api/method/webshop.webshop.shopping_cart.cart.update_cart', {
			form: {item_code: code, qty: 1},
		});
	}

	await page.goto('/checkout');
	await page.waitForLoadState('networkidle');
	await page.waitForTimeout(4000);

	// Avancer jusqu'au paiement
	await page.locator('#step-address .next-step').click();
	await page.waitForTimeout(6000);

	const radios = page.locator('#step-shipping input[type=radio]');
	if ((await radios.count()) && !(await radios.first().isChecked())) {
		const id = await radios.first().getAttribute('id');
		const lab = page.locator(`label[for="${(id || '').replace(/"/g, '\\"')}"]`);
		if (await lab.count()) await lab.first().click();
		else await radios.first().check({force: true});
		await page.waitForTimeout(4000);
	}
	await page.locator('#step-shipping .next-step').click();
	await page.waitForTimeout(12000);

	const rapport = {
		etape: await page.evaluate(() => document.querySelector('.step-section.active')?.id),
		methodes: await page.evaluate(() =>
			[...document.querySelectorAll('.payment-method-item')].map((e) => ({
				id: e.getAttribute('data-method-id'),
				titre: (e.querySelector('.payment-method-title, h5, label')?.textContent || '').trim().slice(0, 40),
			}))
		),
		iframes: page.frames().map((f) => f.url().slice(0, 90)),
		champs_stripe: await page.evaluate(() => ({
			cardholder_name: !!document.querySelector('#cardholder-name'),
			cardholder_email: !!document.querySelector('#cardholder-email'),
			terms: !!document.querySelector('#terms-acceptance'),
			submit: [...document.querySelectorAll('.btn-submit-payment')].map((b) => b.id),
			card_elements: [...document.querySelectorAll('[name="card-element"]')].map((e) => e.id),
		})),
	};
	console.log(JSON.stringify(rapport, null, 2));

	// Selectionner Stripe et inspecter son formulaire
	const stripe = page.locator('.payment-method-item[data-method-id="Stripe___CHF"]');
	await stripe.click();
	await page.waitForTimeout(10000);

	console.log('=== APRES SELECTION DE STRIPE ===');
	console.log(JSON.stringify({
		champs: await page.evaluate(() => ({
			cardholder_name: !!document.querySelector('#cardholder-name'),
			cardholder_email: !!document.querySelector('#cardholder-email'),
			card_elements: [...document.querySelectorAll('[name="card-element"]')].map((e) => e.id),
			submit: [...document.querySelectorAll('.btn-submit-payment')].map((b) => ({id: b.id, visible: b.offsetHeight > 0})),
			terms: [...document.querySelectorAll('#terms-acceptance')].length,
		})),
		iframes: page.frames().map((f) => ({url: f.url().slice(0, 70), nom: f.name()})),
	}, null, 2));


	// Etat de la tuile Stripe et de sa case
	const tuile = page.locator('.payment-method-item').filter({hasText: /stripe/i}).first();
	console.log('=== ETAT APRES CLIC ===');
	console.log(JSON.stringify(await tuile.evaluate((e) => ({
		classes: e.className,
		selected: e.classList.contains('selected'),
		nb_cases: e.querySelectorAll('#terms-acceptance').length,
		case_cochee: e.querySelector('#terms-acceptance')?.checked,
		case_visible: (() => { const c = e.querySelector('#terms-acceptance'); if (!c) return null;
			const cs = getComputedStyle(c); return cs.display !== 'none' && cs.visibility !== 'hidden' && c.offsetHeight > 0; })(),
		bouton_disabled: e.querySelector('.btn-submit-payment')?.disabled,
	})), null, 2));

	// Cocher via le label, puis reobserver
	const label = tuile.locator('.form-check-label').first();
	if (await label.count()) await label.click();
	await page.waitForTimeout(1500);
	console.log('=== APRES CLIC SUR LE LABEL ===');
	console.log(JSON.stringify(await tuile.evaluate((e) => ({
		case_cochee: e.querySelector('#terms-acceptance')?.checked,
		bouton_disabled: e.querySelector('.btn-submit-payment')?.disabled,
	})), null, 2));

	await nav.close();
})();
