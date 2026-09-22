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
const {expect} = require('@playwright/test');

//// A throwaway address the cleanup helper is allowed to remove: the guard in
//// fixtures/activation.js accepts `e2e.<something>@yopmail.com` and nothing else,
//// so an address minted any other way can never be deleted by the suite.
const throwawayAddress = (label = 'account') => `e2e.${label}.${Date.now()}@yopmail.com`;

//// Open the dialog on an address and answer what the shop knows about it.
//// 'known' when it asks for a password, 'unknown' when it asks for a name.
async function askTheDialog(page, email) {
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
	await expect
		.poll(async () => (await nameAsked.isVisible()) || (await passwordAsked.isVisible()), {
			timeout: 25_000,
			message: 'the dialog says neither "I know you" nor "I do not know you"',
		})
		.toBe(true);

	return (await passwordAsked.isVisible()) ? 'known' : 'unknown';
}

/** Create an account through the shop's own dialog, as a visitor does. */
async function createAccountThroughDialog(page, email, {firstName = 'E2E', lastName = 'New'} = {}) {
	const knowledge = await askTheDialog(page, email);
	expect(knowledge, `the shop already knows ${email}`).toBe('unknown');

	await page.fill('#first_name', firstName);
	await page.fill('#last_name', lastName);
	await page.locator('.btn-submit').click();
	await page.waitForTimeout(6000);
}

module.exports = {throwawayAddress, askTheDialog, createAccountThroughDialog};
