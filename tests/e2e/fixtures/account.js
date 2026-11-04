//// //// Neoffice — added file (no upstream equivalent).
////
//// The shop's own front door: creating an account through the sign-in dialog,
//// and asking the dialog whether it still knows an address.
////
//// The dialog is the only place that answers "do you know me?" the way a
//// visitor experiences it: it asks for a PASSWORD when the address is known and
//// for a NAME when it is not. That single reading serves both creating an
//// account and proving a deleted one is really gone — a `User` row missing from
//// the database is the server's opinion; this is the shop's.
const {test, expect, request: playwrightRequest} = require('@playwright/test');
const {waitForSignInMail} = require('./code');

//// Neoffice — the dialog signs in with a code where the site runs the frappe fork's `frappe.passwordless`
//// (neoffice-maintenance#2192): an address is never looked up, the code is mailed and typed. The two helpers
//// below read the page and follow whichever dialog it is, so the specs that use them say the same on both.

//// A throwaway address the cleanup helper is allowed to remove: the guard in
//// fixtures/activation.js accepts `e2e.<something>@yopmail.com` and nothing else,
//// so an address minted any other way can never be deleted by the suite.
const throwawayAddress = (label = 'account') => `e2e.${label}.${Date.now()}@yopmail.com`;

//// Open the dialog on an address and answer what the shop knows about it.
//// 'known' when it asks for a password, 'unknown' when it asks for a name.
async function askTheDialog(page, email) {
	//// As a visitor: an account created through the dialog is signed in at once (decision D-9,
	//// #691), and a signed-in page answers "you are already logged in" instead of asking.
	await page.context().clearCookies();
	await page.goto('/all-products');
	await page.waitForLoadState('domcontentloaded');
	//// Wait for frappe itself, not just for the DOM: the dialog is opened through
	//// `frappe.showLoginDialog`, and a page that has parsed its HTML has not
	//// necessarily run its bundles — one run died on "frappe is not defined" and
	//// passed on the retry, which is the definition of a flaky test.
	await page.waitForFunction(() => typeof window.frappe !== 'undefined' && !!window.frappe.showLoginDialog, null, {
		timeout: 30_000,
	});
	await page.evaluate(() => frappe.showLoginDialog({}));
	await expect(page.locator('.login-dialog')).toBeVisible();

	await page.fill('#login_email', email);
	await page.click('.btn-verify-email');

	const nameAsked = page.locator('.fullname-section');
	const passwordAsked = page.locator('.password-section');
	const codeAsked = page.locator('.code-section');
	await expect
		.poll(
			async () =>
				(await nameAsked.isVisible()) || (await passwordAsked.isVisible()) || (await codeAsked.isVisible()),
			{
				timeout: 25_000,
				message: 'the dialog says neither "I know you" nor "I do not know you" nor "I sent a code"',
			}
		)
		.toBe(true);

	if (await codeAsked.isVisible()) {
		//// A code was mailed to everybody. Typing it answers the question: a known address is signed in
		//// (the page reloads), an unknown one is asked for its name.
		const mail = await waitForSignInMail(email);
		await page.fill('#login_code', mail.code);
		await expect
			.poll(
				async () => {
					if (await nameAsked.isVisible().catch(() => false)) return 'unknown';
					return (await signedInAs(page)) === email ? 'known' : null;
				},
				{timeout: 40_000, message: 'the code was typed and the dialog neither signed in nor asked a name'}
			)
			.not.toBeNull();
		return (await nameAsked.isVisible().catch(() => false)) ? 'unknown' : 'known';
	}

	return (await passwordAsked.isVisible()) ? 'known' : 'unknown';
}

//// Who the page is signed in as, surviving the reload that follows a sign-in.
////
//// Asked through a context of its own, seeded with the page's cookies and thrown away: frappe answers a visitor
//// with `Set-Cookie: sid=Guest`, and a question put through the page's own cookie jar, while the sign-in's response
//// was still on its way, had its "visitor" answer land AFTER the sign-in's and overwrite the session the page had
//// just been given. The page then reloaded as a guest and the test read "Guest" from a sign-in that had worked
//// (a flake of the whole suite, found on 2026-11-04 in the trace of a session that existed on the server and had
//// never been used).
async function signedInAs(page) {
	try {
		const url = page.url();
		const baseURL = /^https?:/.test(url) ? new URL(url).origin : test.info().project.use.baseURL;
		const api = await playwrightRequest.newContext({baseURL, storageState: await page.context().storageState()});
		try {
			const r = await api.get('/api/method/frappe.auth.get_logged_user');
			return r.ok() ? (await r.json()).message || 'Guest' : 'Guest';
		} finally {
			await api.dispose();
		}
	} catch (error) {
		return 'Guest';
	}
}

/** Create an account through the shop's own dialog, as a visitor does. */
async function createAccountThroughDialog(page, email, {firstName = 'E2E', lastName = 'New'} = {}) {
	const knowledge = await askTheDialog(page, email);
	expect(knowledge, `the shop already knows ${email}`).toBe('unknown');

	await page.fill('#first_name', firstName);
	await page.fill('#last_name', lastName);
	await page.locator('.btn-submit').click();
	//// Signed in at once (D-9, and the code's proof of the mailbox): the page reloads as the new customer.
	await expect.poll(() => signedInAs(page), {timeout: 40_000, message: 'the new account is not signed in'}).toBe(email);
}

module.exports = {throwawayAddress, askTheDialog, createAccountThroughDialog, signedInAs};
