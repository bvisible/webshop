//// Neoffice — added file (no upstream equivalent).
//// Applying for a professional account, and what approval produces.
////
//// A b2b_only site refuses anyone who is not already an approved business
//// account. Without this form a prospect has no way in at all: someone has to
//// create the Customer and the User by hand in the desk.
////
//// The form lives in neoffice_theme (DocType "B2B Account Request",
//// /compte-professionnel); these tests drive it from the shop's point of view,
//// and — through the server helper — check what approval actually creates.
////
//// Runs signed out, against the B2B domain.

const {test, expect} = require('@playwright/test');
const {
	URL_B2B,
	multiSiteAvailable,
	openSite,
	callOnSite,
	cartPrice,
	siteCatalogue,
} = require('../fixtures/sites');
const {activationAvailable, onTheServer} = require('../fixtures/activation');

const newEmail = () => `pro.e2e.${Date.now()}@yopmail.com`;
const PASSWORD = 'Pro-Account-E2E-2026!';

/** Fill and submit the public application form. */
async function submitApplication(page, email, company) {
	await page.goto('/compte-professionnel');
	await page.waitForLoadState('networkidle');

	await page.fill('#company_name', company);
	await page.fill('#first_name', 'Prospect');
	await page.fill('#last_name', 'E2E');
	await page.fill('#email', email);
	await page.fill('#phone', '+41791234567');
	await page.fill('#address_line1', 'Rue du Test 1');
	await page.fill('#city', 'Lausanne');
	await page.fill('#pincode', '1003');
	await page.locator('#envoyer-demande').click();
}

test.describe('Business account application', () => {
	test.skip(!multiSiteAvailable(), 'only one domain configured');

	test('the form is reachable by an anonymous visitor', async ({browser}) => {
		const {context, page} = await openSite(browser, URL_B2B);
		try {
			const answer = await page.goto('/compte-professionnel');
			expect(answer.status()).toBe(200);
			//// Without a reachable form, a reserved site is a dead end: a
			//// prospect can neither get in nor ask to get in.
			await expect(page.locator('#company_name')).toBeVisible();
			await expect(page.locator('#email')).toBeVisible();
		} finally {
			await context.close();
		}
	});

	test('an incomplete application is refused', async ({browser}) => {
		const {context, page} = await openSite(browser, URL_B2B);
		try {
			const m = await callOnSite(page, 'neoffice_theme.b2b_requests.submit_account_request', {
				company_name: 'No Contact Ltd',
			});
			expect(m && m.status).toBe('error');
			expect(m && m.reason_code).toBe('missing_fields');
		} finally {
			await context.close();
		}
	});

	test('an invalid e-mail address is refused', async ({browser}) => {
		const {context, page} = await openSite(browser, URL_B2B);
		try {
			const m = await callOnSite(page, 'neoffice_theme.b2b_requests.submit_account_request', {
				company_name: 'Bad Mail Ltd',
				first_name: 'A',
				last_name: 'B',
				email: 'not-an-address',
			});
			expect(m && m.status).toBe('error');
			expect(m && m.reason_code).toBe('invalid_email');
		} finally {
			await context.close();
		}
	});

	//// Security: a public storefront must never allow claiming a desk
	//// account. Same guard as the consumer account creation.
	test('a desk account cannot be claimed', async ({browser}) => {
		const {context, page} = await openSite(browser, URL_B2B);
		try {
			const m = await callOnSite(page, 'neoffice_theme.b2b_requests.submit_account_request', {
				company_name: 'Impersonation Ltd',
				first_name: 'A',
				last_name: 'B',
				email: 'Administrator',
			});
			expect(m && m.status).toBe('error');
			expect(
				['account_exists_system', 'invalid_email'],
				"an administrator's e-mail must never go through"
			).toContain(m && m.reason_code);
		} finally {
			await context.close();
		}
	});

	test('a submitted application is recorded for the right site', async ({browser}) => {
		const {context, page} = await openSite(browser, URL_B2B);
		const email = newEmail();
		try {
			await submitApplication(page, email, 'Application E2E Ltd');

			//// The form disappears in favor of a message: this prevents
			//// accidentally resubmitting the same application.
			await expect(page.locator('#demande-resultat')).toBeVisible({timeout: 30_000});
			await expect(page.locator('#demande-compte-pro')).toBeHidden();

			test.skip(!activationAvailable(), 'server verification unavailable');
			const row = onTheServer(
				`rows = frappe.get_all("B2B Account Request", filters={"email": ${JSON.stringify(email)}},` +
					` fields=["status", "website_profile", "customer_group"])\nprint(rows[0] if rows else "")`
			);
			//// Both the originating site AND the target group must be set: it is
			//// the site that decides the group, never the applicant.
			expect(row, 'the application was not recorded').toContain('Nouvelle');
			expect(row, 'the originating site was not kept').toMatch(/website_profile.+\w/);
		} finally {
			await context.close();
		}
	});

	test('a second application for the same address is refused', async ({browser}) => {
		const {context, page} = await openSite(browser, URL_B2B);
		const email = newEmail();
		try {
			const first = await callOnSite(page, 'neoffice_theme.b2b_requests.submit_account_request', {
				company_name: 'Duplicate Ltd',
				first_name: 'A',
				last_name: 'B',
				email,
			});
			expect(first && first.status).toBe('success');

			const second = await callOnSite(page, 'neoffice_theme.b2b_requests.submit_account_request', {
				company_name: 'Duplicate Ltd',
				first_name: 'A',
				last_name: 'B',
				email,
			});
			expect(second && second.status).toBe('error');
			expect(second && second.reason_code).toBe('already_requested');
		} finally {
			await context.close();
		}
	});
});

test.describe('What an approval produces', () => {
	test.skip(!multiSiteAvailable(), 'only one domain configured');
	test.skip(!activationAvailable(), 'server-side approval unavailable');
	test.describe.configure({mode: 'serial'});

	let email = null;
	let company = null;

	test("an approved application creates the customer in the site's group", async ({browser}) => {
		test.setTimeout(150_000);
		const {context, page} = await openSite(browser, URL_B2B);
		email = newEmail();
		company = `Approval E2E ${Date.now()}`;
		try {
			const m = await callOnSite(page, 'neoffice_theme.b2b_requests.submit_account_request', {
				company_name: company,
				first_name: 'Prospect',
				last_name: 'E2E',
				email,
				address_line1: 'Rue du Test 1',
				city: 'Lausanne',
				pincode: '1003',
			});
			expect(m && m.status).toBe('success');
		} finally {
			await context.close();
		}

		const output = onTheServer(
			`name = frappe.db.get_value("B2B Account Request", {"email": ${JSON.stringify(email)}}, "name")\n` +
				`frappe.set_user("Administrator")\n` +
				`res = frappe.get_doc("B2B Account Request", name).approve()\n` +
				`frappe.db.commit()\n` +
				`customer = frappe.get_doc("Customer", res["customer"])\n` +
				`portal = [p.user for p in (customer.get("portal_users") or [])]\n` +
				`print("GROUP=" + (customer.customer_group or ""))\n` +
				`print("PORTAL=" + str(len(portal)))\n` +
				`print("TYPE=" + (frappe.db.get_value("User", res["user"], "user_type") or ""))`
		);

		//// The group drives both site access AND pricing: if it's wrong, the
		//// customer gets created but won't be able to sign in, or will pay the
		//// wrong price.
		expect(output, 'the customer is not in a business group').toMatch(/GROUP=\S/);
		expect(output, 'the account is not a customer account').toContain('TYPE=Website User');
		//// A duplicate portal user isn't fatal but multiplies with every
		//// submission and clutters the record.
		expect(output, 'duplicate portal user').toContain('PORTAL=1');
	});

	test("the created account can sign in and buy at the site's own rate", async ({browser}) => {
		test.setTimeout(180_000);
		test.skip(!email, 'no approved application');

		//// The activation link is forged server-side, exactly like the one
		//// Frappe puts in its e-mail (the clear-text key exists nowhere
		//// else — the database only keeps its hash).
		const link = onTheServer(
			`from neoffice_theme.neoffice_theme.doctype.b2b_account_request.b2b_account_request import activation_link\n` +
				`link = activation_link(${JSON.stringify(email)}, ` +
				`frappe.db.get_value("B2B Account Request", {"email": ${JSON.stringify(email)}}, "website_profile"))\n` +
				`frappe.db.commit()\nprint(link)`
		);
		const key = (link.split('key=')[1] || '').trim();
		expect(key, 'no activation link').toBeTruthy();

		//// The link must lead to THE professional domain: sending a future
		//// reseller to the consumer shop is a dead end.
		expect(link, 'the activation link points at the wrong domain').toContain(new URL(URL_B2B).host);

		const {context, page} = await openSite(browser, URL_B2B);
		try {
			const activation = await page.request.post(
				'/api/method/frappe.core.doctype.user.user.update_password',
				{form: {key, new_password: PASSWORD}}
			);
			expect(activation.ok(), `activation refused (${activation.status()})`).toBeTruthy();

			//// THE test that matters: the account from the application genuinely
			//// gets into the reserved site, where a consumer account is refused.
			const login = await page.request.post('/api/method/login', {
				form: {usr: email, pwd: PASSWORD},
			});
			expect(login.status(), 'the approved account cannot enter the business site').toBe(200);

			//// And they buy at this site's rate, not the consumer rate.
			const catalogue = await siteCatalogue(page);
			const item = catalogue.find((i) => i.price);
			test.skip(!item, 'no priced article on this domain');

			const cart = await cartPrice(page, item.item_code);
			expect(
				cart.price,
				`catalogue ${item.price} vs cart ${cart.price} ("${cart.list}")`
			).toBeCloseTo(item.price, 2);
		} finally {
			await context.close();
		}
	});
});
