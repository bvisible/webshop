//// Neoffice — added file (no upstream equivalent).
//// The B2B checkout, which is a different page with different rules.
////
//// Unlike the B2C tunnel, /checkout_b2b is a SINGLE page — company, address,
//// shipping, "Place Order" — with no payment step at all: a B2B customer
//// orders now and is billed according to their account terms. So the assertion
//// that matters is not "was it paid", it is "was an order created, and could
//// only the right people create it".
////
//// Runs under the `b2b` project, whose session belongs to a customer whose
//// group is listed in Webshop Settings → B2B Customer Group.

const {test, expect} = require('@playwright/test');
const {
	emptyCart,
	addToCart,
	readQuotation,
	readJson,
	firstBuyableItem,
	currentUser,
} = require('../fixtures/shop');

const B2B_ROUTE = '/checkout_b2b';

/** Is this session actually recognised as a B2B customer? */
async function isB2BCustomer(page) {
	const cart = await readJson(
		page,
		'/api/method/webshop.webshop.shopping_cart.cart.get_cart_quotation'
	);
	return !!(cart && cart.is_b2b_customer);
}

async function filledCart(page) {
	const quotation = await readQuotation(page);
	if (quotation && quotation.doc && (quotation.doc.items || []).length) return true;
	const item = await firstBuyableItem(page);
	if (!item) return false;
	await addToCart(page, item.item_code, 1);
	const after = await readQuotation(page);
	return !!(after && after.doc && (after.doc.items || []).length);
}

test.describe('Recognising the B2B customer', () => {
	test('the test session really is a B2B customer', async ({page}) => {
		await page.goto('/');
		const user = await currentUser(page);
		test.skip(user === 'Guest', 'no B2B session (WEBSHOP_E2E_B2B_USER missing?)');
		expect(await isB2BCustomer(page), `${user} is not recognised as a B2B customer`).toBe(true);
	});

	//// The bug this test locks in: B2B recognition looked up Customer by its
	//// LABEL (customer_name) instead of its identifier. The two coincide as
	//// long as a customer is named after themselves; as soon as a homonym
	//// forces a series ("… - 2"), the lookup found nothing and the customer was
	//// sent back to the B2C tunnel without a word.
	test('a customer whose name differs from its label stays recognised', async ({page}) => {
		await page.goto('/');
		test.skip((await currentUser(page)) === 'Guest', 'no B2B session');

		const cart = await readJson(
			page,
			'/api/method/webshop.webshop.shopping_cart.cart.get_cart_quotation'
		);
		const info = cart && cart.customer_info;
		expect(info, 'the customer could not be resolved').toBeTruthy();

		const quotation = cart && cart.doc;
		if (
			quotation &&
			quotation.party_name &&
			quotation.customer_name &&
			quotation.party_name !== quotation.customer_name
		) {
			//// This is precisely the faulty case: verify that it passes.
			expect(info.name, "the resolved customer is not the quotation's").toBe(quotation.party_name);
		}
		expect(cart.is_b2b_customer).toBe(true);
	});
});

test.describe('Reaching the B2B tunnel', () => {
	test('a B2B customer reaches the page', async ({page}) => {
		test.skip(!(await filledCart(page)), 'the cart could not be filled');
		await page.goto(B2B_ROUTE);
		await expect(page.locator('#b2b-checkout')).toBeVisible({timeout: 30_000});
	});

	test("the page heading does not repeat a step's name", async ({page}) => {
		test.skip(!(await filledCart(page)), 'the cart could not be filled');
		await page.goto(B2B_ROUTE);
		const heading = (await page.locator('h1').first().textContent()).trim();
		expect(heading.toLowerCase()).not.toBe('paiement');
	});

	//// This test verifies it is the RIGHT company, not merely that there is one.
	////
	//// The weak version — "the page isn't empty" — passed green while the page
	//// showed one test account's company on another's quotation: one company's
	//// name shown to another, on the screen where they confirm an order billed
	//// to their own account. A test that asserts nothing protects nothing.
	test("the company shown is the customer's own", async ({page}) => {
		test.skip(!(await filledCart(page)), 'the cart could not be filled');

		const cart = await readJson(
			page,
			'/api/method/webshop.webshop.shopping_cart.cart.get_cart_quotation'
		);
		const expected = cart && cart.doc ? cart.doc.customer_name : null;
		test.skip(!expected, 'the quotation has no customer');

		await page.goto(B2B_ROUTE);
		await expect(page.locator('#b2b-checkout')).toBeVisible({timeout: 30_000});
		await expect(
			page.locator('#b2b-checkout'),
			"the B2B page announces a company other than the quotation's"
		).toContainText(expected);
	});

	test('an empty cart does not lead to the B2B tunnel', async ({page}) => {
		await emptyCart(page);
		await page.goto(B2B_ROUTE);
		//// Placing an order with an empty cart makes no sense: the page must redirect.
		await expect
			.poll(() => page.url(), {
				timeout: 30_000,
				message: 'stays on the B2B tunnel with an empty cart',
			})
			.not.toContain('checkout_b2b');
	});
});

test.describe('B2B order', () => {
	test.describe.configure({mode: 'serial'});

	test('the order button stays locked while the shipping is missing', async ({page}) => {
		test.skip(!(await filledCart(page)), 'the cart could not be filled');
		await page.goto(B2B_ROUTE);
		await expect(page.locator('#b2b-checkout')).toBeVisible({timeout: 30_000});

		const button = page.locator('.btn-place-order');
		await expect(button).toHaveCount(1);
		//// Placing an order without a shipping method produces an incomplete
		//// order that someone will have to fix by hand.
		await expect(button, 'ordering is possible with no shipping method').toBeDisabled();
	});

	test('choosing a shipping method unlocks the order', async ({page}) => {
		test.setTimeout(150_000);
		test.skip(!(await filledCart(page)), 'the cart could not be filled');
		await page.goto(B2B_ROUTE);
		await expect(page.locator('#b2b-checkout')).toBeVisible({timeout: 30_000});

		const options = page.locator('#shipping-methods-container input[type=radio]');
		await expect
			.poll(() => options.count(), {timeout: 40_000, message: 'no shipping method offered'})
			.toBeGreaterThan(0);

		await chooseB2BShipping(page);
		await expect(page.locator('.btn-place-order')).toBeEnabled({timeout: 30_000});
	});

	test('placing the order creates an order and empties the cart', async ({page}) => {
		test.setTimeout(180_000);
		test.skip(!(await filledCart(page)), 'the cart could not be filled');

		const before = await readQuotation(page);
		const quotationName = before && before.doc ? before.doc.name : null;
		test.skip(!quotationName, 'no current quotation');

		await page.goto(B2B_ROUTE);
		await expect(page.locator('#b2b-checkout')).toBeVisible({timeout: 30_000});

		const options = page.locator('#shipping-methods-container input[type=radio]');
		await expect.poll(() => options.count(), {timeout: 40_000}).toBeGreaterThan(0);
		await chooseB2BShipping(page);

		const button = page.locator('.btn-place-order');
		await expect(button).toBeEnabled({timeout: 30_000});
		await button.click();

		//// The proof is server-side: the original quotation must no longer be
		//// the current cart. An on-screen message proves nothing.
		await expect
			.poll(
				async () => {
					const quotation = await readQuotation(page);
					return quotation && quotation.doc ? quotation.doc.name : null;
				},
				{timeout: 120_000, message: 'the quotation never became an order'}
			)
			.not.toBe(quotationName);
	});
});

//// The B2B shipping radios sit in their own container and, like the B2C ones,
//// may be hidden behind a styled label.
async function chooseB2BShipping(page) {
	const options = page.locator('#shipping-methods-container input[type=radio]');
	if ((await options.count()) === 0) return;
	if (await options.first().isChecked()) return;

	const id = await options.first().getAttribute('id');
	const label = id ? page.locator(`label[for="${id.replace(/"/g, '\\"')}"]`) : null;
	if (label && (await label.count()) && (await label.first().isVisible())) {
		await label.first().click();
	} else {
		await options.first().check({force: true});
		await options.first().dispatchEvent('change');
	}
	await page.waitForTimeout(4000);
}

test.describe('What the B2B tunnel is walled off from', () => {
	//// An ordinary customer must not be able to order under B2B terms
	//// (deferred payment, reseller pricing). This test runs under the B2C
	//// session, not the B2B one.
	test('a non-B2B customer is refused', async ({browser}) => {
		//// Hard-coded path, NOT require('../global-setup'): the config already
		//// imports that module, and Playwright then refuses to load the spec
		//// ("test.describe() called in a file imported by the configuration"),
		//// which makes the ENTIRE suite fail to load.
		const context = await browser.newContext({
			storageState: require('path').join(__dirname, '..', '.auth', 'session.json'),
		});
		const page = await context.newPage();
		try {
			await page.goto('/');
			test.skip((await currentUser(page)) === 'Guest', 'B2C session unavailable');
			test.skip(await isB2BCustomer(page), 'the B2C account is also B2B on this site');

			await page.goto(B2B_ROUTE);
			await expect
				.poll(() => page.url(), {
					timeout: 30_000,
					message: 'a non-B2B customer reaches the B2B tunnel',
				})
				.not.toContain('checkout_b2b');
		} finally {
			await context.close();
		}
	});

	test('an anonymous visitor is sent back to sign in', async ({browser}) => {
		const context = await browser.newContext();
		const page = await context.newPage();
		try {
			await page.goto(B2B_ROUTE);
			await page.waitForLoadState('domcontentloaded');

			//// What matters is what the guest SEES, not the displayed URL.
			//// The URL may remain the one requested depending on how the
			//// redirect is served; the tunnel itself must never be shown.
			await expect(page.locator('#b2b-checkout'), 'a guest sees the B2B tunnel').toHaveCount(0);

			//// Never to /app: a portal customer has no desk access, sending them
			//// there is a dead end.
			expect(page.url(), 'a guest is sent to the desk').not.toContain('/app');
		} finally {
			await context.close();
		}
	});
});
