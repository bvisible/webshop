//// Neoffice — added file (no upstream equivalent).
////
//// Signing in with a code, in a real browser (neoffice-maintenance#2192). The engine is the frappe fork's
//// `frappe.passwordless`: a 6-digit code AND a link in one mail, the same answer for every address, the link
//// signing in only through its button and only in the browser that asked, a customer never sent to the desk.
//// The mail is read from the server's queue (fixtures/code.js): a test needs no mailbox.
////
//// Runs signed out. Every address is a throwaway `e2e.<label>.<time>@yopmail.com` the cleanup helper may delete.
////
//// Needs WEBSHOP_E2E_SSH_HOST / WEBSHOP_E2E_SITE (the code is read on the server) and a site where the code is on:
//// the first test says so loudly, instead of letting the others fail for an unrelated reason.

const {test, expect} = require('@playwright/test');
const {CREDENTIALS} = require('../fixtures/shop');
const {throwawayAddress, askTheDialog, signedInAs} = require('../fixtures/account');
const {waitForSignInMail} = require('../fixtures/code');
const {activationAvailable, onTheServer, deleteAccount} = require('../fixtures/activation');

const created = [];
const track = (address) => {
	created.push(address);
	return address;
};

test.afterAll(() => {
	for (const address of created) {
		try {
			const report = deleteAccount(address);
			//// A throwaway account the cleanup could only disable stays on the instance, and tries to provision
			//// a mailbox that fails: say so, with the reason the server gave, instead of staying silent
			//// (neoffice-maintenance#2221: seventeen of them piled up unseen).
			if (report && /^disabled only/.test(report.account || '')) {
				console.warn(`[e2e] ${address} was disabled, not deleted: ${report.account}`);
			}
		} catch (error) {
			/* the next run's address is a new one */
		}
	}
});

//// A user made on the server, the way an administrator would make one: a customer or a member of staff.
function makeUser(address, role) {
	onTheServer(
		`u = frappe.get_doc({"doctype": "User", "email": ${JSON.stringify(address)}, "first_name": "E2E", ` +
			`"send_welcome_email": 0, "roles": [{"role": ${JSON.stringify(role)}}]})\n` +
			`u.flags.ignore_permissions = True\nu.insert()\nfrappe.db.commit()\nprint("made")`
	);
	track(address);
}

function userRecord(address) {
	const out = onTheServer(
		`import json\n` +
			`row = frappe.db.get_value("User", ${JSON.stringify(address)}, ["user_type", "enabled"], as_dict=True) or {}\n` +
			`row["roles"] = frappe.get_all("Has Role", filters={"parent": ${JSON.stringify(address)}}, pluck="role")\n` +
			`row["pending"] = frappe.db.get_value("User", ${JSON.stringify(address)}, "email_confirmation_pending")\n` +
			`print(json.dumps(row, default=str))`
	);
	return JSON.parse(out.split('\n').pop());
}

//// A browser made by hand starts as nobody. Playwright 1.62 hands it the project's saved session, so
//// under `customer` the "new browser" was already signed in as the test customer and never saw the dialog.
function anonymousContext(browser, options = {}) {
	return browser.newContext({
		baseURL: test.info().project.use.baseURL,
		storageState: {cookies: [], origins: []},
		...options,
	});
}

async function openDialog(page, path = '/all-products') {
	await page.goto(path);
	await page.waitForLoadState('domcontentloaded');
	await page.waitForFunction(() => typeof window.frappe !== 'undefined' && !!window.frappe.showLoginDialog, null, {
		timeout: 30_000,
	});
	await page.evaluate(() => frappe.showLoginDialog({}));
	await expect(page.locator('.login-dialog')).toBeVisible();
}

async function askForTheCode(page, address, path) {
	await openDialog(page, path);
	await page.fill('#login_email', address);
	await page.click('.btn-verify-email');
	await expect(page.locator('.code-section')).toBeVisible({timeout: 25_000});
}

async function post(page, method, data) {
	const response = await page.request.post(`/api/method/${method}`, {data});
	let body = null;
	try {
		body = (await response.json()).message;
	} catch (error) {
		/* an error page */
	}
	return {status: response.status(), body, headers: response.headers()};
}

test.describe('Signing in with a code — what it must hold', () => {
	test.setTimeout(150_000);

	test('this site mails a code, and says the same to everybody', async ({page}) => {
		expect(activationAvailable(), 'WEBSHOP_E2E_SSH_HOST / WEBSHOP_E2E_SITE: the code is read on the server').toBe(
			true
		);
		const settings = await post(page, 'webshop.webshop.auth.api.get_auth_settings', {});
		expect(settings.body.passwordless, 'the site does not sign in with a code').toBe(true);

		//// A known address and one nobody holds: one answer, and the cookie that binds a link to this browser
		//// is set either way, so the headers do not tell them apart. The known one is a throwaway account: a
		//// code is limited to five mails an hour per address, and the shared test customer's allowance was
		//// spent by the second run of the hour.
		const knownAddress = throwawayAddress('known');
		makeUser(knownAddress, 'Customer');
		const known = await post(page, 'frappe.passwordless.request_code', {email: knownAddress});
		const stranger = await post(page, 'frappe.passwordless.request_code', {email: throwawayAddress('nobody')});
		expect(known.status).toBe(200);
		expect(known.body).toEqual(stranger.body);
		expect(known.body.ok).toBe(true);
		expect(known.headers['set-cookie'], 'the browser binding').toContain('pwl_nonce=');
		expect(stranger.headers['set-cookie']).toContain('pwl_nonce=');

		//// And no door answers "who is this": the address check tells nothing either.
		const checkKnown = await post(page, 'webshop.webshop.auth.api.check_email', {email: CREDENTIALS.user});
		const checkStranger = await post(page, 'webshop.webshop.auth.api.check_email', {email: 'zz@example.test'});
		expect(checkKnown.body).toEqual(checkStranger.body);
	});

	test('nothing that is not an address, and never a standard user', async ({page}) => {
		for (const email of ['Administrator', 'Guest', 'not an address', '', 'a@b']) {
			const answer = await post(page, 'frappe.passwordless.request_code', {email});
			expect(answer.body, JSON.stringify(email)).toEqual({ok: false, reason: 'invalid_address'});
		}
	});
});

test.describe('A new customer, then the same customer again', () => {
	test.describe.configure({mode: 'serial'});
	test.setTimeout(150_000);

	let address = null;

	test('email, code, name: the account opens already confirmed, on the page they were on', async ({page}) => {
		address = track(throwawayAddress('code-new'));
		await page.context().clearCookies();
		await askForTheCode(page, address, '/all-products');

		const mail = await waitForSignInMail(address);
		expect(mail.subject).toContain(mail.code);
		expect(mail.link, 'an address with no account gets no link: the code is how it opens one').toBeNull();

		await page.fill('#login_code', mail.code);
		await expect(page.locator('.fullname-section')).toBeVisible({timeout: 25_000});
		await expect(page.locator('#login_email')).toHaveValue(address);
		await page.fill('#first_name', 'Camille');
		await page.fill('#last_name', 'Code');
		await page.locator('.btn-submit').click();

		await expect.poll(() => signedInAs(page), {timeout: 40_000}).toBe(address);
		expect(new URL(page.url()).pathname, 'the buyer stays on the page they were on').toBe('/all-products');

		const record = userRecord(address);
		expect(record.user_type).toBe('Website User');
		//// Other apps of the instance add their own portal roles (a course student, a suite user): never a desk one.
		expect(record.roles).toContain('Customer');
		expect(record.roles).not.toContain('System Manager');
		expect(record.pending, 'the code proved the address: nothing is left to confirm').toBeFalsy();
	});

	test('the same customer signs in again: a wrong code is refused, the right one opens the session', async ({
		page,
	}) => {
		test.skip(!address, 'the account was not created');
		await page.context().clearCookies();
		await askForTheCode(page, address, '/all-products');
		const mail = await waitForSignInMail(address);
		expect(mail.link, 'an account gets the link beside the code').toContain('/login-link?token=');

		const wrong = mail.code === '000000' ? '111111' : '000000';
		await page.fill('#login_code', wrong);
		await expect(page.locator('#alert-container, .alert-message').first()).toContainText(/not valid|n'est pas valable/i);
		expect(await signedInAs(page), 'a wrong code signs nobody in').toBe('Guest');
		await expect(page.locator('.code-section')).toBeVisible();

		await page.fill('#login_code', mail.code);
		await expect.poll(() => signedInAs(page), {timeout: 40_000}).toBe(address);
		await expect(page.locator('.fullname-section')).toBeHidden();
	});

	test('the password is still there for whoever has one', async ({page}) => {
		await page.context().clearCookies();
		//// What this proves is the link to the password on the code step, not the mail. It used to ask the engine
		//// for a real code for the shared test customer, in each project and at each retry, and the engine sends
		//// five mails an hour per address: the second series of the hour got "too many requests", the dialog
		//// went to the password by itself and the code step never showed (neoffice-maintenance#2221). The
		//// engine's answer is given at the network instead: nothing is mailed and nothing is counted.
		let answered = 0;
		await page.route('**/api/method/frappe.passwordless.request_code', (route) => {
			answered += 1;
			return route.fulfill({
				status: 200,
				contentType: 'application/json',
				body: JSON.stringify({message: {ok: true, resend_in: 30}}),
			});
		});
		await askForTheCode(page, CREDENTIALS.user, '/all-products');
		expect(answered, 'the dialog asked for the code once, and the answer was ours').toBe(1);
		await page.locator('.code-use-password').click();
		await expect(page.locator('.password-section')).toBeVisible();
		await expect(page.locator('.code-section')).toBeHidden();
		await page.fill('#login_password', CREDENTIALS.password);
		await page.locator('.btn-submit').click();
		await expect.poll(() => signedInAs(page), {timeout: 40_000}).toBe(CREDENTIALS.user);
	});

	test('a field losing the focus mails nobody', async ({page}) => {
		const stranger = throwawayAddress('blur');
		await page.context().clearCookies();
		await openDialog(page);
		await page.fill('#login_email', stranger);
		await page.locator('.login-dialog-header').click(); //// the field loses the focus
		await page.waitForTimeout(3000);
		await expect(page.locator('.code-section')).toBeHidden();
		const { latestSignInMail } = require('../fixtures/code');
		expect(latestSignInMail(stranger), 'a blur must not send a mail').toBeNull();
	});
});

test.describe('The link in the mail', () => {
	test.describe.configure({mode: 'serial'});
	test.setTimeout(180_000);

	test('opening it changes nothing; only its button signs in, once, in the browser that asked', async ({
		browser,
	}) => {
		const address = throwawayAddress('code-link');
		makeUser(address, 'Customer');
		const context = await anonymousContext(browser, {locale: 'fr-CH'});
		const page = await context.newPage();

		await askForTheCode(page, address, '/all-products');
		const mail = await waitForSignInMail(address);
		const link = mail.link;
		expect(link).toContain('/login-link?token=');

		//// A scanner opens the link before the person does, as often as it likes.
		for (let i = 0; i < 2; i += 1) {
			await page.goto(link);
			await expect(page.locator('form[action*="sign_in_with_link"] button[type=submit]')).toBeVisible();
			expect(await signedInAs(page), 'opening the link must sign nobody in').toBe('Guest');
		}

		//// The button signs in and sends the browser to the page it was on.
		await page.locator('form[action*="sign_in_with_link"] button[type=submit]').click();
		await expect.poll(() => signedInAs(page), {timeout: 40_000}).toBe(address);
		expect(new URL(page.url()).pathname).toBe('/all-products');

		//// Once.
		const other = await anonymousContext(browser);
		const otherPage = await other.newPage();
		await otherPage.goto(link);
		await expect(otherPage.locator('form[action*="sign_in_with_link"]')).toHaveCount(0);
		await expect(otherPage.locator('body')).toContainText(/invalid|expired|invalide|expir/i);
		await context.close();
		await other.close();
	});

	test('opened on another device it signs nobody in and points to the code', async ({browser}) => {
		const address = throwawayAddress('code-device');
		makeUser(address, 'Customer');
		const asker = await anonymousContext(browser);
		const askerPage = await asker.newPage();
		await askForTheCode(askerPage, address, '/all-products');
		const mail = await waitForSignInMail(address);

		//// The phone's mail app: no cookie, so no button, and nothing signed in.
		const phone = await anonymousContext(browser);
		const phonePage = await phone.newPage();
		await phonePage.goto(mail.link);
		await expect(phonePage.locator('form[action*="sign_in_with_link"]')).toHaveCount(0);
		await expect(phonePage.locator('body')).toContainText(/code/i);
		expect(await signedInAs(phonePage)).toBe('Guest');

		//// And a request for the button from there is refused all the same (the page is only the polite half).
		const token = mail.link.split('token=')[1];
		const forged = await phonePage.request.post('/api/method/frappe.passwordless.sign_in_with_link', {
			form: {token},
		});
		expect(forged.status()).toBe(403);
		expect(await signedInAs(phonePage)).toBe('Guest');

		//// The code still works from the first browser.
		await askerPage.fill('#login_code', mail.code);
		await expect.poll(() => signedInAs(askerPage), {timeout: 40_000}).toBe(address);
		await asker.close();
		await phone.close();
	});
});

//// A mail that does not come must never lock anybody out (decision of 2026-11-04: the code is the default way in on
//// every site, and the password stays whatever happens). The failures are the real ones, simulated at the network:
//// nothing is mailed, so these tests spend none of the hourly allowance of the code.
test.describe('The password is always in reach', () => {
	test.setTimeout(120_000);

	test.beforeEach(async ({page}) => {
		await page.context().clearCookies(); //// the `customer` project starts signed in
	});

	async function signInWithThePassword(page) {
		await expect(page.locator('.password-section')).toBeVisible();
		await page.fill('#login_password', CREDENTIALS.password);
		await page.locator('.btn-submit').click();
		await expect.poll(() => signedInAs(page), {timeout: 40_000}).toBe(CREDENTIALS.user);
	}

	test('from the first step, with no mail asked for', async ({page}) => {
		const asked = [];
		page.on('request', (request) => {
			if (request.url().includes('frappe.passwordless.request_code')) asked.push(request.url());
		});
		await openDialog(page);
		await expect(page.locator('.email-use-password')).toBeVisible({timeout: 15_000});

		//// no address yet: it says so, and nothing opens
		await page.locator('.email-use-password').click();
		await expect(page.locator('.password-section')).toBeHidden();

		await page.fill('#login_email', CREDENTIALS.user);
		await page.locator('.email-use-password').click();
		await expect(page.locator('.code-section')).toBeHidden();
		await expect(page.locator('.email-use-password')).toBeHidden();
		await signInWithThePassword(page);
		expect(asked, 'the password path must not mail anything').toEqual([]);
	});

	const failures = [
		['a request the site refuses (429)', (route) =>
			route.fulfill({status: 429, contentType: 'application/json', body: JSON.stringify({exc_type: 'TooManyRequestsError'})})],
		['a server error (500)', (route) => route.fulfill({status: 500, contentType: 'text/html', body: 'Internal Server Error'})],
		['a network that fails', (route) => route.abort('failed')],
		['a code the site could not start', (route) =>
			route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({message: {ok: false, reason: 'error'}})})],
		//// A site that stopped offering the code also answers the ordinary address check again (it tells a known
		//// address from an unknown one): the dialog falls back to it and asks for the password of a known address.
		['a site that stopped offering the code', (route) =>
			route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({message: {ok: false, reason: 'disabled'}})}),
		async (page) => {
			await page.route('**/', (route) => {
				const request = route.request();
				if (request.method() === 'POST' && (request.postData() || '').includes('auth.api.check_email')) {
					return route.fulfill({
						status: 200,
						contentType: 'application/json',
						body: JSON.stringify({message: {exists: true, first_name: 'E2E', login_with_email_link: false}}),
					});
				}
				return route.continue();
			});
		}],
	];

	for (const [label, answer, alsoAnswer] of failures) {
		test(`${label} leaves the password in reach`, async ({page}) => {
			await page.route('**/api/method/frappe.passwordless.request_code', answer);
			if (alsoAnswer) await alsoAnswer(page);
			await openDialog(page);
			await page.fill('#login_email', CREDENTIALS.user);
			await page.click('.btn-verify-email');
			await expect(page.locator('.password-section')).toBeVisible({timeout: 20_000});
			await expect(page.locator('.code-section')).toBeHidden();
			await signInWithThePassword(page);
		});
	}
});

test.describe("The desk's own sign-in page", () => {
	test.describe.configure({mode: 'serial'});
	test.setTimeout(150_000);

	//// Staff may sign in with a code only where the site says so (System Settings, "Staff can sign in with the
	//// emailed code"). That value is a site setting and other work on the instance can reset it: this test states
	//// its own precondition instead of trusting what a previous run left.
	test.beforeAll(() => {
		onTheServer(
			`frappe.db.set_single_value("System Settings", "login_with_email_link", 1)\n` +
				`frappe.db.set_single_value("System Settings", "login_code_system_users", 1)\n` +
				`frappe.db.commit()\nfrappe.clear_document_cache("System Settings", "System Settings")\nprint("set")`
		);
	});

	test('staff sign in to the desk with a code', async ({page}) => {
		const address = throwawayAddress('code-staff');
		makeUser(address, 'Desk User');
		expect(userRecord(address).user_type, 'the fixture must be a member of staff').toBe('System User');

		await page.context().clearCookies();
		await page.goto('/login#login-with-email-link');
		await page.fill('#login_with_email_link_email', address);
		await page.locator('.btn-login-with-email-link').last().click();
		await expect(page.locator('.form-login-code')).toBeVisible({timeout: 25_000});

		const mail = await waitForSignInMail(address);
		await page.fill('#login_code', mail.code);
		await page.locator('.btn-login-code').click();
		await expect.poll(() => signedInAs(page), {timeout: 40_000}).toBe(address);
		await expect(page).not.toHaveURL(/\/login/);
	});

	test('a customer is never sent to the desk, whatever the link they followed says', async ({page}) => {
		const address = throwawayAddress('code-portal');
		makeUser(address, 'Customer');
		await page.context().clearCookies();
		await page.goto('/login?redirect-to=/app/todo#login-with-email-link');
		await page.fill('#login_with_email_link_email', address);
		await page.locator('.btn-login-with-email-link').last().click();
		await expect(page.locator('.form-login-code')).toBeVisible({timeout: 25_000});

		const mail = await waitForSignInMail(address);
		await page.fill('#login_code', mail.code);
		await page.locator('.btn-login-code').click();
		await expect.poll(() => signedInAs(page), {timeout: 40_000}).toBe(address);
		await page.waitForLoadState('domcontentloaded');
		expect(new URL(page.url()).pathname, 'a customer has nothing at the desk').not.toMatch(/^\/app/);
	});
});
