//// Neoffice — added file (no upstream equivalent).
//// The cart, including the multi-warehouse behaviour added in 2026-08: the same
//// item taken from two different sources must stay two separate lines.

const {test, expect} = require('@playwright/test');
const {
	signIn,
	emptyCart,
	addToCart,
	readQuotation,
	firstBuyableItem,
	catalogueItems,
} = require('../fixtures/shop');

//// Find a product the shop itself offers from two sources.
////
//// Neither the doctype nor a whitelisted helper is reachable from a customer
//// session (Website Users get a 403 on frappe.client.get_list, and rightly so),
//// so this reads the source selector the product page actually draws — the same
//// thing the customer sees and clicks.
//// Cached for the whole file: the search costs one page load per product, and
//// five specs need the same answer. Without this the multi-warehouse block
//// spent minutes re-walking the catalogue, and the earlier 8-product limit
//// stopped before reaching the only item that has two sources — so every one of
//// those specs was skipped, silently, and the run still looked green.
let _multiSource;

async function multiSourceItem(page) {
	if (_multiSource !== undefined) return _multiSource;

	//// A route can be designated in ~/.config/webshop-e2e.env
	//// (WEBSHOP_E2E_MULTISOURCE_ROUTE). The automatic detection below only
	//// sees the first page of the catalogue: on a site where the
	//// multi-source item sits further down, all these tests went silent.
	const designated = process.env.WEBSHOP_E2E_MULTISOURCE_ROUTE;
	if (designated) {
		const found = await sourcesOnProductPage(page, designated.replace(/^\//, ''));
		if (found) {
			_multiSource = found;
			return _multiSource;
		}
		throw new Error(
			`WEBSHOP_E2E_MULTISOURCE_ROUTE points at /${designated}, which offers no two sources.`
		);
	}

	_multiSource = null;
	for (const route of await catalogueItems(page, 25)) {
		const found = await sourcesOnProductPage(page, route);
		if (found) {
			_multiSource = found;
			break;
		}
	}
	return _multiSource;
}

/** Read a product page's source selector; null unless it offers two or more. */
async function sourcesOnProductPage(page, route) {
	await page.goto('/' + route);
	await page.waitForLoadState('domcontentloaded');
	//// The product's own code, not the first data-item-code on the page: the
	//// theme's cart drawer sits in the header and its lines carry that
	//// attribute too, so a leftover in the cart used to be taken for the
	//// product under test.
	const read = await page.evaluate(() => ({
		item_code:
			(
				document.querySelector(
					'.product-page-content .btn-add-to-cart[data-item-code]:not([data-item-code=""])'
				) || document.querySelector('.product-page-content [data-item-code]')
			)?.getAttribute('data-item-code') || null,
		warehouses: [
			...new Set(
				[...document.querySelectorAll('input[name="webshop-warehouse-source"]')]
					.map((r) => r.value)
					.filter(Boolean)
			),
		],
	}));
	return read.item_code && read.warehouses.length >= 2 ? {route, ...read} : null;
}

test.describe('Cart', () => {
	test.beforeEach(async ({page}) => {
		await signIn(page);
	});

	test('a single visible heading', async ({page}) => {
		await page.goto('/cart');
		await page.waitForLoadState('networkidle');
		const visible = await page.evaluate(
			() =>
				[...document.querySelectorAll('h1')].filter(
					(h) => getComputedStyle(h).display !== 'none' && h.getBoundingClientRect().height > 0
				).length
		);
		expect(visible, 'the double heading is back on the cart').toBe(1);
	});

	test('an empty cart says so plainly', async ({page}) => {
		expect(await emptyCart(page), 'the cart could not be emptied').toBe(true);
		await page.goto('/cart');
		await page.waitForLoadState('networkidle');
		//// Either an empty-state message, or no line at all: never a silent screen
		//// with ghost lines.
		const lines = await page.locator('.cart-table [data-item-code]').count();
		expect(lines).toBe(0);
	});

	test('an added article shows up in the cart', async ({page}) => {
		expect(await emptyCart(page), 'the cart could not be emptied').toBe(true);
		const item = await firstBuyableItem(page);
		test.skip(!item, 'no published article');

		await addToCart(page, item.item_code, 2);
		await page.goto('/cart');
		await page.waitForLoadState('networkidle');

		//// The theme renders the cart TWICE: the page's table, and a side drawer
		//// (#builder-cart-drawer) carrying the same data-item-code values.
		//// Targeting without distinguishing grabs the drawer, off-screen, and the
		//// test fails on "element is not visible", blaming the page.
		await expect(
			page.locator(`.cart-table [data-item-code="${item.item_code}"]`).first()
		).toBeVisible();
	});

	test('raising the quantity updates the quotation', async ({page}) => {
		expect(await emptyCart(page), 'the cart could not be emptied').toBe(true);
		const item = await firstBuyableItem(page);
		test.skip(!item, 'no published article');

		await addToCart(page, item.item_code, 1);
		await page.goto('/cart');
		await page.waitForLoadState('networkidle');

		//// On the page, the quantity is a field (the drawer, on the other hand,
		//// has buttons).
		const field = page.locator('.cart-table input.cart-qty').first();
		test.skip((await field.count()) === 0, 'no quantity control on this theme');

		await field.fill('2');
		await field.press('Enter');

		await expect
			.poll(async () => totalQuantity(page), {
				timeout: 25_000,
				message: 'the quantity did not follow',
			})
			.toBe(2);
	});

	//// The defect this test locks in: emptying the cart DELETES the quotation,
	//// and that deletion is refused as soon as a payment request is linked to
	//// it (LinkExistsError). After a declined card — a mundane case — the
	//// customer could no longer remove their last item: a technical error,
	//// cart stuck for good. Payment requests that were never honored are now
	//// cancelled, while ones that succeeded remain intact.
	test('a cart empties even after a declined payment', async ({page}) => {
		test.setTimeout(120_000);
		expect(await emptyCart(page), 'the cart could not be emptied').toBe(true);

		const item = await firstBuyableItem(page);
		test.skip(!item, 'no published article');
		await addToCart(page, item.item_code, 1);

		//// The decline isn't simulated here (that would need a real Stripe
		//// attempt): 05-stripe-payment leaves one behind, and this test runs
		//// after it. What matters is that emptying succeeds no matter what the
		//// quotation is carrying.
		expect(await emptyCart(page), 'the cart stays stuck').toBe(true);
		const quotation = await readQuotation(page);
		expect((quotation && quotation.doc && quotation.doc.items) || []).toHaveLength(0);
	});

	test('removing an article clears its line', async ({page}) => {
		expect(await emptyCart(page), 'the cart could not be emptied').toBe(true);
		const item = await firstBuyableItem(page);
		test.skip(!item, 'no published article');

		await addToCart(page, item.item_code, 1);
		expect(await totalQuantity(page)).toBe(1);

		await addToCart(page, item.item_code, 0);
		expect(await totalQuantity(page), 'the article was not removed').toBe(0);
	});
});

test.describe('Multi-warehouse cart', () => {
	test.beforeEach(async ({page}) => {
		await signIn(page);
	});

	//// The heart of the feature: the same item taken from two different
	//// sources is NOT the same item from the customer's point of view
	//// (different lead times), so it must stay two lines and never merge.
	test('the same article from two sources makes two lines', async ({page}) => {
		const item = await multiSourceItem(page);
		test.skip(!item, 'no multi-source article on this site');

		await emptyCart(page);
		for (const warehouse of item.warehouses.slice(0, 2)) {
			await addToCart(page, item.item_code, 1, warehouse);
		}

		const quotation = await readQuotation(page);
		const lines = ((quotation && quotation.doc && quotation.doc.items) || []).filter(
			(l) => l.item_code === item.item_code
		);
		expect(lines.length, 'the two sources merged into one line').toBe(2);

		const warehouses = new Set(lines.map((l) => l.warehouse));
		expect(warehouses.size, 'both lines point at the same warehouse').toBe(2);
	});

	test('taking the same source again increments the existing line', async ({page}) => {
		const item = await multiSourceItem(page);
		test.skip(!item, 'no multi-source article on this site');

		expect(await emptyCart(page), 'the cart could not be emptied').toBe(true);

		const warehouse = item.warehouses[0];
		for (let i = 0; i < 2; i += 1) {
			await addToCart(page, item.item_code, i + 1, warehouse);
		}

		//// Filtered on the WAREHOUSE as much as on the item: without this, a line
		//// left behind by the other source (previous test, incomplete emptying)
		//// counts as a duplicate and the test wrongly blames the merge for not
		//// happening.
		const quotation = await readQuotation(page);
		const lines = ((quotation && quotation.doc && quotation.doc.items) || []).filter(
			(l) => l.item_code === item.item_code && l.warehouse === warehouse
		);
		expect(lines.length, 'a second line was created for the same source').toBe(1);
		expect(lines[0].qty).toBe(2);
	});

	//// The customer must be able to choose their source BEFORE adding to cart,
	//// with each one's stock in plain sight.
	test('the product page offers the sources with their stock', async ({page}) => {
		const item = await multiSourceItem(page);
		test.skip(!item, 'no multi-source article on this site');

		await page.goto('/' + item.route);
		await page.waitForLoadState('networkidle');

		const options = page.locator('.webshop-source-option');
		expect(await options.count(), 'the source selector is gone').toBeGreaterThanOrEqual(2);
		await expect(options.first()).toBeVisible();
		//// A source without its stock does not allow an informed choice: that is
		//// the whole point of displaying the sources.
		await expect(options.first()).toContainText(/\d/);
	});

	test('only one source is ticked at a time', async ({page}) => {
		const item = await multiSourceItem(page);
		test.skip(!item, 'no multi-source article on this site');

		await page.goto('/' + item.route);
		await page.waitForLoadState('networkidle');
		const ticked = await page.locator('input[name="webshop-warehouse-source"]:checked').count();
		expect(ticked, 'the source choice is ambiguous').toBe(1);
	});

	test('the source is announced on the cart line', async ({page}) => {
		const item = await multiSourceItem(page);
		test.skip(!item, 'no multi-source article on this site');

		await emptyCart(page);
		await addToCart(page, item.item_code, 1, item.warehouses[0]);

		await page.goto('/cart');
		await page.waitForLoadState('networkidle');
		//// The customer must see where their goods ship from, otherwise two
		//// identical lines at the same price make no sense.
		const line = page.locator(`.cart-table [data-item-code="${item.item_code}"]`).first();
		await expect(line).toBeVisible();
		expect(
			await page.locator('.cart-table [data-warehouse]').count(),
			'no source shown on the lines'
		).toBeGreaterThan(0);
	});
});

/** Total quantity currently in the cart, straight from the server. */
async function totalQuantity(page) {
	const quotation = await readQuotation(page);
	const lines = (quotation && quotation.doc && quotation.doc.items) || [];
	return lines.reduce((sum, l) => sum + (l.qty || 0), 0);
}
