//// //// Neoffice — added file (no upstream equivalent).
////
//// The whole life of a customer account: it is created through the shop's own
//// dialog, the shop knows it, it is deleted, and the address comes free again.
////
//// The last step is the one nobody tested. The suite's cleanup used to only set
//// `enabled = 0` under a name that said "delete", so every run left a disabled
//// account, a customer, a contact and a cart behind, and the same address could
//// never sign up again. A shop that cannot really close an account accumulates
//// them for ever — and a suite that cannot clean up after itself can only run
//// once per address.
const {test, expect} = require('@playwright/test');
const {throwawayAddress, askTheDialog, createAccountThroughDialog} = require('../fixtures/account');
const {activationAvailable, accountExists, deleteAccount} = require('../fixtures/activation');

test.describe('The life of a customer account', () => {
	test.describe.configure({mode: 'serial'});
	test.setTimeout(120_000);

	let email = null;

	test.afterAll(() => {
		//// Whatever the test did, the address must not survive it.
		if (email) deleteAccount(email);
	});

	test('an account is created through the shop, deleted, and its address comes free again', async ({
		page,
	}) => {
		test.skip(
			!activationAvailable(),
			'WEBSHOP_E2E_SSH_HOST / WEBSHOP_E2E_SITE missing: the deletion cannot be verified'
		);

		email = throwawayAddress('lifecycle');
		expect(accountExists(email), 'this address already exists before the test').toBe(false);

		await createAccountThroughDialog(page, email);
		expect(accountExists(email), 'the account was not created').toBe(true);
		//// The shop's own answer, not only the database's.
		expect(await askTheDialog(page, email), 'the shop does not recognise the account it created').toBe(
			'known'
		);

		const report = deleteAccount(email);
		expect(report, 'the deletion returned nothing').toBeTruthy();
		expect(report.refused, `the deletion refused the address: ${report.refused}`).toBeUndefined();
		//// A brand-new account carries no order, so it goes for good. An account
		//// that has bought cannot be deleted without rewriting the shop's books:
		//// there, freeing the address is the whole of what deletion may do.
		expect(report.account, 'the account was neither deleted nor freed').toMatch(/deleted|renamed/);

		expect(accountExists(email), 'the account is still there after deletion').toBe(false);
		expect(
			await askTheDialog(page, email),
			'the shop still knows a deleted address: it could never sign up again'
		).toBe('unknown');

		email = null; //// nothing left to clean up
	});
});
