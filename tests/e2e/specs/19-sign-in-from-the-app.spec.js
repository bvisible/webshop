//// Neoffice — added file (no upstream equivalent).
////
//// The mobile app's door of the sign-in by code (neoffice-maintenance#2192, `frappe.passwordless.app_sign_in`), played
//// the way the phone plays it, from the outside: the app keeps a random verifier and sends only its SHA-256 (PKCE),
//// the mail carries the code AND a link, the link's page offers to open the app and signs nobody in, and the code (or
//// the link's token) with the verifier gives the OAuth bundle `mobile_auth` gives after a password. Then the bundle is
//// USED: the access token reads the session's user, the refresh token renews it. Nothing here mints or bypasses a code.
////
//// Needs WEBSHOP_E2E_SSH_HOST / WEBSHOP_E2E_SITE (the mail is read from the server's queue), like spec 18. Every
//// address is a throwaway the cleanup removes, tokens first.

const crypto = require('crypto');
const {test, expect} = require('@playwright/test');
const {throwawayAddress, signedInAs} = require('../fixtures/account');
const {waitForSignInMail, latestSignInMail} = require('../fixtures/code');
const {onTheServer, deleteAccount} = require('../fixtures/activation');

const SIGNED_OUT = {cookies: [], origins: []};
const created = [];

test.afterAll(() => {
	for (const address of created) {
		try {
			onTheServer(
				`frappe.db.delete("OAuth Bearer Token", {"user": ${JSON.stringify(address)}})\nfrappe.db.commit()\nprint("ok")`
			);
			deleteAccount(address);
		} catch (error) {
			/* the next run's address is a new one */
		}
	}
});

function makeUser(address, role) {
	onTheServer(
		`u = frappe.get_doc({"doctype": "User", "email": ${JSON.stringify(address)}, "first_name": "E2E", ` +
			`"send_welcome_email": 0, "roles": [{"role": ${JSON.stringify(role)}}]})\n` +
			`u.flags.ignore_permissions = True\nu.insert()\nfrappe.db.commit()\nprint("made")`
	);
	created.push(address);
}

//// The app's client: the one the app's own sign-in is configured with (Raven Settings points at it), else any.
function appClientId() {
	return onTheServer(
		`name = frappe.db.get_single_value("Raven Settings", "oauth_client") or frappe.db.get_value("OAuth Client", {}, "name")\n` +
			`print(frappe.db.get_value("OAuth Client", name, "client_id"))`
	)
		.split('\n')
		.pop()
		.trim();
}

//// RFC 7636: 32 random bytes, base64url without padding; the challenge is the SHA-256 of the verifier's text.
function pkce() {
	const verifier = crypto.randomBytes(32).toString('base64url');
	const challenge = crypto.createHash('sha256').update(verifier).digest('base64url');
	return {verifier, challenge};
}

test.describe('The mobile app signs in with a code or a link', () => {
	test.describe.configure({mode: 'serial'});
	test.setTimeout(180_000);

	let api;
	let clientId;

	test.beforeAll(async ({playwright}, workerInfo) => {
		api = await playwright.request.newContext({
			baseURL: workerInfo.project.use.baseURL,
			storageState: SIGNED_OUT,
		});
		clientId = appClientId();
	});

	test.afterAll(async () => {
		await api.dispose();
	});

	async function call(method, data, headers = {}) {
		const response = await api.post(`/api/method/${method}`, {data, headers});
		let body = null;
		try {
			body = (await response.json()).message;
		} catch (error) {
			/* an error page */
		}
		return {status: response.status(), body};
	}

	test('this server knows the app, and says so before the app shows a button', async () => {
		const response = await api.get('/api/method/frappe.passwordless.status');
		expect(response.status()).toBe(200);
		const status = (await response.json()).message;
		expect(status.enabled, 'the site does not offer the code').toBe(true);
		expect(status.app, 'an older server has no such key').toBe(true);
		expect(clientId, 'no OAuth client to sign the app in with').toBeTruthy();
	});

	test('the code, with the verifier, gives a session that works and renews', async () => {
		const address = throwawayAddress('app-code');
		makeUser(address, 'Desk User');
		const {verifier, challenge} = pkce();

		const asked = await call('frappe.passwordless.request_code', {email: address, app_challenge: challenge});
		expect(asked.body.ok, JSON.stringify(asked)).toBe(true);
		const mail = await waitForSignInMail(address);
		expect(mail.link, 'the mail carries the link').toContain('/login-link?token=');

		//// A device without the verifier: the right code is not enough, and it is not burnt either.
		const stranger = pkce();
		const refused = await call('frappe.passwordless.app_sign_in', {
			client_id: clientId,
			verifier: stranger.verifier,
			email: address,
			code: mail.code,
		});
		expect(refused.body).toEqual({ok: false, reason: 'invalid'});

		const signedIn = await call('frappe.passwordless.app_sign_in', {
			client_id: clientId,
			verifier,
			email: address,
			code: mail.code,
		});
		expect(signedIn.body.ok, JSON.stringify(signedIn)).toBe(true);
		const bundle = signedIn.body;
		for (const key of ['access_token', 'refresh_token', 'expires_in', 'token_type', 'sid', 'user', 'full_name']) {
			expect(bundle, `the bundle lacks ${key}`).toHaveProperty(key);
		}
		expect([bundle.token_type, bundle.user]).toEqual(['Bearer', address]);

		//// The bundle is USED: this is what the app does with it all day.
		const who = await api.get('/api/method/frappe.auth.get_logged_user', {
			headers: {Authorization: `Bearer ${bundle.access_token}`},
		});
		expect((await who.json()).message).toBe(address);

		//// And renewed: the app's refresh, the way `mobile_refresh_token` hands out a new access token.
		const renewed = await call('neoffice_theme.mobile.mobile_refresh_token', {refresh_token: bundle.refresh_token});
		expect(renewed.body.access_token, JSON.stringify(renewed)).toBeTruthy();
		const again = await api.get('/api/method/frappe.auth.get_logged_user', {
			headers: {Authorization: `Bearer ${renewed.body.access_token}`},
		});
		expect((await again.json()).message).toBe(address);

		//// Once.
		const replay = await call('frappe.passwordless.app_sign_in', {
			client_id: clientId,
			verifier,
			email: address,
			code: mail.code,
		});
		expect(replay.body).toEqual({ok: false, reason: 'invalid'});
	});

	test('the link reopens the app, signs nobody in on the web, and signs the app in once', async ({browser}) => {
		const address = throwawayAddress('app-link');
		makeUser(address, 'Customer');
		const {verifier, challenge} = pkce();

		const asked = await call('frappe.passwordless.request_code', {email: address, app_challenge: challenge});
		expect(asked.body.ok).toBe(true);
		const mail = await waitForSignInMail(address);
		const token = new URL(mail.link).searchParams.get('token');

		//// What the person sees when they tap the link in their mail: a button that opens the app, and nobody signed in.
		const context = await browser.newContext({
			baseURL: test.info().project.use.baseURL,
			storageState: SIGNED_OUT,
		});
		const page = await context.newPage();
		await page.goto(mail.link);
		const open = page.locator('#open-the-app');
		await expect(open).toBeVisible();
		const href = await open.getAttribute('href');
		const deep = new URL(href);
		expect(`${deep.protocol}//${deep.hostname}${deep.pathname}`).toBe('neoffice://sign-in');
		expect(deep.searchParams.get('token')).toBe(token);
		expect(deep.searchParams.get('site')).toBe(new URL(test.info().project.use.baseURL).host);
		expect(await signedInAs(page), 'opening the link must sign nobody in').toBe('Guest');
		await expect(page.locator('form[action*="sign_in_with_link"]')).toHaveCount(0);

		//// The web's own door refuses this link, with the cookie of the browser that asked or without.
		const web = await page.request.post('/api/method/frappe.passwordless.sign_in_with_link', {form: {token}});
		expect(web.status()).toBe(403);
		await context.close();

		//// The app: another verifier is refused and burns nothing; the right one signs in, once.
		const wrong = await call('frappe.passwordless.app_sign_in', {
			client_id: clientId,
			verifier: pkce().verifier,
			token,
		});
		expect(wrong.body).toEqual({ok: false, reason: 'invalid'});
		const right = await call('frappe.passwordless.app_sign_in', {client_id: clientId, verifier, token});
		expect(right.body.ok, JSON.stringify(right)).toBe(true);
		expect(right.body.user).toBe(address);
		const replay = await call('frappe.passwordless.app_sign_in', {client_id: clientId, verifier, token});
		expect(replay.body).toEqual({ok: false, reason: 'invalid'});
	});

	test('an address with no account is answered like any other and mailed nothing', async () => {
		const stranger = throwawayAddress('app-nobody');
		const {challenge} = pkce();
		const asked = await call('frappe.passwordless.request_code', {email: stranger, app_challenge: challenge});
		expect(asked.body.ok).toBe(true);
		expect(asked.body.resend_in).toBeGreaterThan(0);
		await new Promise((resolve) => setTimeout(resolve, 4000));
		expect(latestSignInMail(stranger), 'an app cannot open an account: nothing may be mailed').toBeNull();
	});

	test('a malformed challenge is refused, never mailed', async () => {
		const address = throwawayAddress('app-malformed');
		makeUser(address, 'Customer');
		const asked = await call('frappe.passwordless.request_code', {email: address, app_challenge: 'short'});
		expect(asked.body).toEqual({ok: false, reason: 'invalid_request'});
		await new Promise((resolve) => setTimeout(resolve, 3000));
		expect(latestSignInMail(address)).toBeNull();
	});
});
