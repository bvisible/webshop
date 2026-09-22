//// Neoffice — added file (no upstream equivalent).
//// Sign-in and account creation, the two doors into the shop. Everything here
//// runs as a guest: the whole point is what an anonymous visitor can do, and
//// what they must not be able to do.

const {test, expect} = require('@playwright/test');
const {CREDENTIALS, currentUser} = require('../fixtures/shop');

//// Unique per run so a re-run never collides with the account the previous run
//// created. Cleanup: bench console, see README.md.
const THROWAWAY_PREFIX = 'e2e.auto.';
const throwawayEmail = () => `${THROWAWAY_PREFIX}${Date.now()}@example.test`;

async function callAsGuest(page, method, form) {
	const r = await page.request.post(`/api/method/${method}`, {form});
	return {status: r.status(), body: r.ok() ? await r.json() : null};
}

test.describe('E-mail address check', () => {
	test('an existing account is recognised', async ({page}) => {
		const {body} = await callAsGuest(page, 'webshop.webshop.auth.api.check_email', {
			email: CREDENTIALS.user,
		});
		expect(body.message.exists).toBe(true);
		expect(body.message.first_name, 'the first name personalises the dialog').toBeTruthy();
	});

	test('an unknown account opens the creation path', async ({page}) => {
		const {body} = await callAsGuest(page, 'webshop.webshop.auth.api.check_email', {
			email: 'e2e.unknown.zz@example.test',
		});
		expect(body.message.exists).toBe(false);
	});
});

test.describe('Account creation — the refusals it must make', () => {
	test('missing fields', async ({page}) => {
		const {body} = await callAsGuest(page, 'webshop.webshop.auth.api.create_account', {
			email: throwawayEmail(),
		});
		expect(body.message.message).toBe('error');
		expect(body.message.reason_code).toBe('missing_fields');
	});

	test('invalid e-mail address', async ({page}) => {
		const {body} = await callAsGuest(page, 'webshop.webshop.auth.api.create_account', {
			email: 'not-an-address',
			first_name: 'A',
			last_name: 'B',
		});
		expect(body.message.message).toBe('error');
		expect(body.message.reason_code).toBe('invalid_email');
	});

	test('an existing customer account is sent to sign in', async ({page}) => {
		const {body} = await callAsGuest(page, 'webshop.webshop.auth.api.create_account', {
			email: CREDENTIALS.user,
			first_name: 'A',
			last_name: 'B',
		});
		expect(body.message.message).toBe('error');
		expect(body.message.reason_code).toBe('account_exists_website');
	});

	//// Security: the shop must never be able to touch a desk account. Without
	//// this guard, creating an account with an administrator's e-mail would
	//// open a privilege confusion.
	test('a desk account cannot be taken over through the shop', async ({page}) => {
		const {body} = await callAsGuest(page, 'webshop.webshop.auth.api.create_account', {
			email: 'Administrator',
			first_name: 'A',
			last_name: 'B',
		});
		expect(body.message.message).toBe('error');
		expect(
			['account_exists_system', 'invalid_email'],
			"an administrator's e-mail must never end in a creation"
		).toContain(body.message.reason_code);
	});
});

test.describe('Account creation — the real journey', () => {
	test('a new visitor can create their account', async ({page}) => {
		const email = throwawayEmail();
		const {body} = await callAsGuest(page, 'webshop.webshop.auth.api.create_account', {
			email,
			first_name: 'E2E',
			last_name: 'Auto',
		});
		expect(body.message.message, `creation refused: ${body.message.reason || ''}`).not.toBe('error');

		//// The account must exist AND remain a customer account: never a desk role.
		const {body: check} = await callAsGuest(page, 'webshop.webshop.auth.api.check_email', {email});
		expect(check.message.exists, 'the account must exist right after its creation').toBe(true);
	});
});

test.describe('Sign-in', () => {
	test('the right password opens the session', async ({page}) => {
		const r = await page.request.post('/api/method/login', {
			form: {usr: CREDENTIALS.user, pwd: CREDENTIALS.password},
		});
		expect(r.ok()).toBeTruthy();
		expect(await currentUser(page)).toBe(CREDENTIALS.user);
	});

	test('a wrong password opens no session at all', async ({page}) => {
		const r = await page.request.post('/api/method/login', {
			form: {usr: CREDENTIALS.user, pwd: 'deliberately-wrong-password'},
		});
		expect(r.status(), 'a refusal must be a refusal, not a 200').toBeGreaterThanOrEqual(400);
		expect(await currentUser(page)).toBe('Guest');
	});

	test('the dialog asks for the e-mail, then the password', async ({page}) => {
		await page.goto('/all-products');
		await page.waitForLoadState('domcontentloaded');
		//// The bundles may still be loading: `frappe` is what opens the dialog.
		await page.waitForFunction(
			() => typeof window.frappe !== 'undefined' && !!window.frappe.showLoginDialog,
			null,
			{timeout: 30_000}
		);
		await page.evaluate(() => frappe.showLoginDialog({}));

		const dialog = page.locator('.login-dialog');
		await expect(dialog).toBeVisible();

		await page.fill('#login_email', CREDENTIALS.user);
		await page.click('.btn-verify-email');

		//// The password field only appears once the address is recognized: that's
		//// what distinguishes "I'm signing in" from "I'm creating an account".
		await expect(page.locator('.password-section')).toBeVisible();
		await expect(page.locator('.fullname-section')).toBeHidden();
	});

	test('the dialog asks for a name when the address is unknown', async ({page}) => {
		await page.goto('/all-products');
		await page.waitForLoadState('domcontentloaded');
		//// The bundles may still be loading: `frappe` is what opens the dialog.
		await page.waitForFunction(
			() => typeof window.frappe !== 'undefined' && !!window.frappe.showLoginDialog,
			null,
			{timeout: 30_000}
		);
		await page.evaluate(() => frappe.showLoginDialog({}));

		await page.fill('#login_email', throwawayEmail());
		await page.click('.btn-verify-email');

		await expect(page.locator('.fullname-section')).toBeVisible();
		await expect(page.locator('.password-section')).toBeHidden();
	});
});

test.describe('What an anonymous visitor is walled off from', () => {
	//// RULE #1b: what the guest must not reach is probed through the API, from
	//// THEIR OWN session. Hiding a button is not a permission.
	test('the shop settings are not readable', async ({page}) => {
		const r = await page.request.get(
			'/api/method/frappe.client.get_list?doctype=Webshop%20Settings&fields=["name"]'
		);
		expect(r.status(), 'Webshop Settings must be refused to a guest').toBeGreaterThanOrEqual(400);
	});

	test('the list of users is not readable', async ({page}) => {
		const r = await page.request.get(
			'/api/method/frappe.client.get_list?doctype=User&fields=["name","email"]'
		);
		expect(r.status(), 'the list of accounts must be refused').toBeGreaterThanOrEqual(400);
	});

	test('the addresses are not readable', async ({page}) => {
		const r = await page.request.get(
			'/api/method/frappe.client.get_list?doctype=Address&fields=["name","city"]'
		);
		expect(r.status(), 'customer addresses must be refused').toBeGreaterThanOrEqual(400);
	});
});
