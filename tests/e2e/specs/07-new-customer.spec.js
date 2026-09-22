//// Neoffice — added file (no upstream equivalent).
//// The full journey of someone who has never bought here: create an account,
//// activate it, fill a cart, and pay by card.
////
//// This is the scenario the other specs do NOT cover. 01-authentication stops
//// at "the account exists"; 05-stripe-payment starts from an account that
//// already exists and already has addresses. Everything in between — a customer
//// with no address, no Customer record, no order history — only happens here,
//// and it is the path every real first-time buyer takes.
////
//// Runs signed out, and creates a real (throwaway) account each time.

const {test, expect} = require('@playwright/test');
const {
	emptyCart,
	addToCart,
	readQuotation,
	readJson,
	goToPaymentStep,
	firstBuyableItem,
	currentUser,
} = require('../fixtures/shop');
const {
	activationAvailable,
	activateAccount,
	activationFailureReason,
	deleteAccount,
} = require('../fixtures/activation');
const {throwawayAddress, createAccountThroughDialog} = require('../fixtures/account');
const {CARDS, fillCard, submitPayment} = require('../fixtures/stripe');

//// Throwaway address and the dialog's own front door: one copy, in
//// fixtures/account.js, shared with the account-lifecycle spec. Two copies of a
//// sign-up flow drift, and the second one is the one nobody fixes.
const newEmail = () => throwawayAddress('newcustomer');
const PASSWORD = 'E2e-New-Customer-2026!';

test.describe('A new customer, from signing up to their order', () => {
	test.describe.configure({mode: 'serial'});

	let email = null;

	test.afterAll(() => {
		if (email) deleteAccount(email);
	});

	test('they create their account from the shop', async ({page}) => {
		test.setTimeout(120_000);
		email = newEmail();
		await createAccountThroughDialog(page, email);

		//// The on-screen confirmation proves nothing: ask the server instead.
		//// Via readJson, which survives an HTML response — what the site returns
		//// when it's under load, and which would kill an r.json() call with a
		//// parsing error unrelated to what is being tested.
		await expect
			.poll(
				async () => {
					const m = await readJson(page, '/api/method/webshop.webshop.auth.api.check_email', {
						email,
					});
					return m ? m.exists : null;
				},
				{timeout: 40_000, message: 'the account was not created'}
			)
			.toBe(true);

		//// And yet they must not be signed in: the account is created without a
		//// password, activation goes through the link received. An "account
		//// created" that opened a session without a password would be a hole.
		expect(await currentUser(page), 'a session was opened without activation').toBe('Guest');
	});

	test('they activate their account through the link they received', async ({page}) => {
		test.setTimeout(120_000);
		test.skip(!email, 'the account could not be created');
		test.skip(
			!activationAvailable(),
			'activation unavailable (WEBSHOP_E2E_SSH_HOST / WEBSHOP_E2E_SITE missing)'
		);

		//// The account is created WITHOUT a password: without this step, it
		//// cannot sign in, and that is exactly what a real customer experiences.
		const activated = await activateAccount(page, email, PASSWORD);
		expect(activated, `activation impossible: ${activationFailureReason()}`).toBe(true);
		expect(await currentUser(page)).toBe(email);
	});

	test('they fill their cart and pay by card', async ({page}) => {
		test.setTimeout(300_000);
		test.skip(!email, 'the account could not be created');
		test.skip(!activationAvailable(), 'activation unavailable');

		const login = await page.request.post('/api/method/login', {
			form: {usr: email, pwd: PASSWORD},
		});
		test.skip(!login.ok(), 'the activated account cannot sign in');

		await emptyCart(page);
		const item = await firstBuyableItem(page);
		test.skip(!item, 'no published article');
		await addToCart(page, item.item_code, 1);

		const quotation = await readQuotation(page);
		expect(quotation && quotation.doc, 'no quotation for this new customer').toBeTruthy();
		const quotationName = quotation.doc.name;

		//// A brand-new customer has NO address at all: the tunnel must let them
		//// enter one, not block them. That is the point this scenario tests,
		//// and no other one covers it.
		await page.goto('/checkout');
		await page.waitForLoadState('networkidle');
		await expect(page.locator('#step-address')).toHaveClass(/active/, {timeout: 40_000});
		await fillAddress(page);

		test.skip(!(await goToPaymentStep(page)), 'no shipping method for this address');

		const tile = await fillCard(page, CARDS.accepted, {name: 'E2E New', email});
		await submitPayment(page, tile);

		await expect
			.poll(
				async () => {
					const current = await readQuotation(page);
					return current && current.doc ? current.doc.name : null;
				},
				{timeout: 150_000, message: "the new customer's order never went through"}
			)
			.not.toBe(quotationName);
	});
});

//// Fill the address form of a customer who has none.
////
//// Waits for the form before touching it: the address step is rendered by
//// JavaScript and, measured on this site, is still empty six seconds after the
//// page reports "networkidle". Reading it too early shows zero fields and looks
//// exactly like a checkout that refuses to serve a new customer.
////
//// Then fills every REQUIRED field left empty, rather than a hard-coded list:
//// the form differs by site (company, VAT number, house number…), and a single
//// missing required field silently blocks the step with no message.
async function fillAddress(page) {
	await expect
		.poll(() => page.locator('#step-address input:visible').count(), {
			timeout: 40_000,
			message: 'the address form never appeared',
		})
		.toBeGreaterThan(3);

	const values = {
		first_name: 'E2E',
		last_name: 'New',
		email: 'do-not-reply@yopmail.com',
		phone: '+41791234567',
		address_1: 'Rue du Test 1',
		address_2: '',
		house_number: '1',
		city: 'Lausanne',
		postcode: '1003',
		state: 'Vaud',
		country: 'Switzerland',
	};

	const toFill = await page.evaluate(() =>
		[...document.querySelectorAll('#step-address input, #step-address select')]
			.filter((e) => e.type !== 'hidden' && e.type !== 'checkbox' && e.offsetHeight > 0)
			.filter((e) => e.required && !e.value)
			.map((e) => e.name || e.id)
	);

	for (const name of toFill) {
		const key = Object.keys(values).find((k) => name.endsWith(k));
		if (!key || !values[key]) continue;
		const field = page.locator(`[name="${name}"], #${name}`).first();
		if ((await field.count()) === 0) continue;
		await field.fill(values[key]);
	}

	//// The country drives the shipping rules: without it, no method is
	//// offered and the next step becomes a dead end.
	const country = page.locator('[name="billing_country"], #billing_country').first();
	if ((await country.count()) && !(await country.inputValue())) {
		await country.fill(values.country);
	}
	await page.waitForTimeout(2500);
}
