//// Neoffice — added file (the quick order, no upstream equivalent).
//// The page as three people see it: a visitor is served where the shop sells to
//// visitors and sent to sign in elsewhere, a plain customer is served, a B2B
//// customer types a reference, fills a grid at the keyboard, loses the page,
//// finds the draft again and sends it to the cart.
const {test, expect} = require('@playwright/test');
const {emptyCart, readQuotation, readJson, currentUser} = require('../fixtures/shop');

const ROUTE = '/quick-order';

//// Neoffice — removed estRevendeur() (0928431668 "feat(quick-order): ouverte à tout le monde,
//// et un bouton par grille"): the page no longer gates on reseller status, so the helper that
//// read is_b2b_customer off the cart is gone.

/** A published model with variants, found through the page's own search endpoint. */
async function firstTemplate(page, keywords = ['chemise', 't-shirt', 'top', 'a']) {
	for (const word of keywords) {
		const results = await readJson(
			page,
			'/api/method/webshop.webshop.quick_order.api.search_references',
			{query: word}
		);
		const template = (results || []).find((r) => r.kind === 'template');
		if (template) return template;
	}
	return null;
}

/** The cart's lines as {item_code: qty}. */
async function cartLines(page) {
	const quotation = await readQuotation(page);
	return ((quotation && quotation.doc && quotation.doc.items) || []).reduce(
		(acc, l) => ({...acc, [l.item_code]: l.qty}),
		{}
	);
}

test.describe('Quick order — who gets in', () => {
	//// Neoffice — renamed and extended (0928431668 "feat(quick-order): ouverte à tout le monde,
	//// et un bouton par grille"): a visitor is now served where the shop sells to visitors, not
	//// just sent to sign in — hence the longer timeout below for the search-to-cart round trip.
	test('a visitor is served where the shop sells to visitors, and sent to sign in elsewhere', async ({
		page,
	}, testInfo) => {
		test.skip(testInfo.project.name !== 'guest', 'visitor project only');
		test.setTimeout(120_000);
		await page.goto(ROUTE);
		if (/\/login/.test(page.url())) {
			//// A shop with no guest cart, or a professional site: the visitor signs in first.
			await expect(page).toHaveURL(/\/login/);
			return;
		}
		await expect(page.locator('#wsh-qo')).toBeVisible();
		//// A visitor's cart is real too: a model, one cell, sent, found in the guest cart.
		const template = await firstTemplate(page);
		test.skip(!template, 'no published model with variants on this shop');
		const field = page.locator('.wsh-qo__input');
		await field.fill(template.name.slice(0, 12));
		await expect(
			page.locator('.wsh-qo-sugg', {hasText: template.item_code}).first()
		).toBeVisible({timeout: 15_000});
		await field.press('Enter');
		const grid = page.locator(`.wsh-qo-model[data-template="${template.item_code}"]`);
		await expect(grid).toBeVisible({timeout: 15_000});
		const cells = grid
			.locator('.wsh-qo-cell:not(.wsh-qo-cell--none)')
			.filter({has: page.locator('.wsh-qo-stock.has-stock, .wsh-qo-stock.is-unlimited')});
		test.skip((await cells.count()) === 0, 'no servable cell in the grid');
		const cell = cells.nth(0).locator('.wsh-qo-qty');
		await cell.focus();
		await page.keyboard.type('2');
		const code = await cell.getAttribute('data-item');
		//// The grid's own button: this model goes to the cart on its own.
		await grid.locator('.wsh-qo-model__add').click();
		await expect(page.locator('.wsh-qo__report-ok')).toBeVisible({timeout: 30_000});
		expect((await cartLines(page))[code]).toBe(2);
		await emptyCart(page);
	});

	//// Neoffice — renamed, and dropped the reseller check and its redirect to '/'
	//// (0928431668 "feat(quick-order): ouverte à tout le monde, et un bouton par grille"):
	//// any signed-in customer is served directly now, not just resellers.
	test('an ordinary customer is served, whatever their group', async ({page}, testInfo) => {
		test.skip(testInfo.project.name !== 'customer', 'customer project only');
		await page.goto(ROUTE);
		//// Neoffice — asserts the page and access are open (0928431668 "feat(quick-order):
		//// ouverte à tout le monde, et un bouton par grille"), not that a refusal is shown.
		await expect(page.locator('#wsh-qo')).toBeVisible();
		await expect(page.locator('.wsh-qo-refusal')).toHaveCount(0);
		const r = await page.request.post(
			'/api/method/webshop.webshop.quick_order.api.search_references',
			{form: {query: 'chemise'}}
		);
		//// Neoffice — expects 200, not 403 (0928431668 "feat(quick-order): ouverte à tout le
		//// monde, et un bouton par grille"): the endpoint now admits any signed-in customer.
		expect(r.status(), 'search_references refused a signed-in customer').toBe(200);
	});
});

//// Neoffice — describe block renamed from "le revendeur" (0928431668 "feat(quick-order):
//// ouverte à tout le monde, et un bouton par grille"): these tests now cover the B2B-specific
//// path only, general access having moved to the "who gets in" describe above.
test.describe('Quick order — the B2B customer', () => {
	test.beforeEach(async ({page}, testInfo) => {
		test.skip(testInfo.project.name !== 'b2b', 'reseller project only');
		await page.goto('/');
		test.skip((await currentUser(page)) === 'Guest', 'no B2B session (WEBSHOP_E2E_B2B_USER missing?)');
		//// The cart must start empty, and say so when it cannot: a leftover line would
		//// add up with the quantities typed below and blame the page.
		test.skip(!(await emptyCart(page)), "the B2B account's cart will not empty");
		//// A draft from a previous run must not leak into this one.
		await page.goto(ROUTE);
		await page.evaluate(() => {
			Object.keys(localStorage)
				.filter((k) => k.startsWith('webshop:quick-order:'))
				.forEach((k) => localStorage.removeItem(k));
		});
	});

	test('the page opens on the search, and nothing more', async ({page}) => {
		await page.goto(ROUTE);
		await expect(page.locator('#wsh-qo')).toBeVisible();
		await expect(page.locator('.wsh-qo__input')).toBeFocused();
		await expect(page.locator('.wsh-qo__send')).toBeDisabled();
	});

	test('a typed reference opens the grid, quantities go in at the keyboard and reach the cart', async ({
		page,
	}) => {
		test.setTimeout(120_000);
		const template = await firstTemplate(page);
		test.skip(!template, 'no published model with variants on this shop');
		await page.goto(ROUTE);

		const field = page.locator('.wsh-qo__input');
		await field.fill(template.name.slice(0, 12));
		const suggestion = page.locator('.wsh-qo-sugg', {hasText: template.item_code}).first();
		await expect(suggestion).toBeVisible({timeout: 15_000});
		await field.press('Enter');

		const grid = page.locator(`.wsh-qo-model[data-template="${template.item_code}"]`);
		await expect(grid).toBeVisible({timeout: 15_000});
		//// Cells with stock, so the shop's rule lets them through.
		const cells = grid
			.locator('.wsh-qo-cell:not(.wsh-qo-cell--none)')
			.filter({has: page.locator('.wsh-qo-stock.has-stock, .wsh-qo-stock.is-unlimited')});
		expect(await cells.count(), 'no servable cell in the grid').toBeGreaterThan(1);

		const first = cells.nth(0).locator('.wsh-qo-qty');
		const second = cells.nth(1).locator('.wsh-qo-qty');
		await first.focus();
		await page.keyboard.type('2');
		await page.keyboard.press('Enter');
		//// Enter moves to the next cell of the grid, which may be a non-servable one:
		//// type into the second servable cell explicitly, the count is what matters.
		await second.focus();
		await page.keyboard.type('3');
		await expect(page.locator('.wsh-qo__pieces')).toHaveText('5');
		await expect(page.locator('.wsh-qo__lines')).toHaveText('2');
		await expect(page.locator('.wsh-qo__send')).toBeEnabled();

		const codes = [await first.getAttribute('data-item'), await second.getAttribute('data-item')];

		//// The page is lost and found again: the draft survives the reload.
		await page.reload();
		await expect(page.locator('.wsh-qo__resume')).toBeVisible();
		await page.locator('.wsh-qo__resume-yes').click();
		await expect(page.locator('.wsh-qo__pieces')).toHaveText('5', {timeout: 15_000});
		await expect(page.locator(`.wsh-qo-qty[data-item="${codes[0]}"]`)).toHaveValue('2');

		await page.locator('.wsh-qo__send').click();
		await expect(page.locator('.wsh-qo__report-ok')).toBeVisible({timeout: 30_000});
		const lines = await cartLines(page);
		expect(lines[codes[0]]).toBe(2);
		expect(lines[codes[1]]).toBe(3);
		await emptyCart(page);
	});

	test('an unknown code is named, not swallowed', async ({page}) => {
		await page.goto(ROUTE);
		const field = page.locator('.wsh-qo__input');
		await field.fill('CODE-THAT-DOES-NOT-EXIST-123');
		await field.press('Enter');
		await expect(page.locator('.wsh-qo__notice')).toContainText('CODE-THAT-DOES-NOT-EXIST-123');
		await expect(page.locator('.wsh-qo-model')).toHaveCount(0);
	});
});

//// Neoffice — added describe block (eb91b0ba75 "fix(quick-order): un article sans prix ou épuisé
//// n'est pas commandable, quantité plafonnée au stock"): what the grid must refuse to let anyone
//// type. A cell with no price on the customer's list, or nothing left in stock, carries no input
//// at all; a cell with a finite stock caps the quantity at what the shop can actually serve.
test.describe('Quick order — stock and price', () => {
	/** A published model whose grid holds both a non-orderable cell and a capped one. */
	async function templateWithUnorderableCells(page) {
		const seen = new Set();
		for (const word of ['chemise', 't-shirt', 'top', 'a', 'e']) {
			const results = await readJson(
				page,
				'/api/method/webshop.webshop.quick_order.api.search_references',
				{query: word}
			);
			for (const r of results || []) {
				const code = r.kind === 'template' ? r.item_code : r.template;
				if (!code || seen.has(code)) continue;
				seen.add(code);
				const grid = await readJson(
					page,
					'/api/method/webshop.webshop.quick_order.api.get_matrix',
					{template: code}
				);
				const variants = (grid && grid.variants) || [];
				const off = variants.filter((v) => v.price === null || v.stock === 0);
				const capped = variants.filter((v) => v.price !== null && v.stock !== null && v.stock > 0);
				if (off.length && capped.length) return {code, off, capped};
			}
		}
		return null;
	}

	test.beforeEach(async ({page}, testInfo) => {
		test.skip(
			!['customer', 'b2b'].includes(testInfo.project.name),
			'customer and reseller projects only'
		);
		await page.goto(ROUTE);
		test.skip((await currentUser(page)) === 'Guest', 'no session');
	});

	test('a cell with no price, or sold out, cannot be typed into', async ({page}) => {
		test.setTimeout(120_000);
		const template = await templateWithUnorderableCells(page);
		test.skip(!template, 'no model with an unorderable cell on this shop');

		await page.goto(ROUTE);
		const field = page.locator('.wsh-qo__input');
		await field.fill(template.code);
		await field.press('Enter');
		const grid = page.locator(`.wsh-qo-model[data-template="${template.code}"]`);
		await expect(grid).toBeVisible({timeout: 15_000});

		//// Every non-orderable cell says why, and carries no quantity field.
		const unorderable = grid.locator('.wsh-qo-cell--off');
		expect(await unorderable.count(), 'no unorderable cell was rendered').toBeGreaterThan(0);
		expect(
			await unorderable.locator('.wsh-qo-qty').count(),
			'an unorderable cell carries an input'
		).toBe(0);
		//// The reasons are the shop's own UI text, which the fleet serves in French.
		const reasons = await unorderable.locator('.wsh-qo-off').allTextContents();
		expect(
			reasons.every((m) => /Prix sur demande|Épuisé/.test(m)),
			`unexpected reasons: ${reasons}`
		).toBe(true);
	});

	test('the quantity never goes above the available stock', async ({page}) => {
		test.setTimeout(120_000);
		const template = await templateWithUnorderableCells(page);
		test.skip(!template, 'no usable model on this shop');
		const target = template.capped[0];

		await page.goto(ROUTE);
		const field = page.locator('.wsh-qo__input');
		await field.fill(template.code);
		await field.press('Enter');
		const grid = page.locator(`.wsh-qo-model[data-template="${template.code}"]`);
		await expect(grid).toBeVisible({timeout: 15_000});

		const input = grid.locator(`.wsh-qo-qty[data-item="${target.item_code}"]`);
		await expect(input).toHaveAttribute('max', String(target.stock));

		//// Typing far more than the shop can serve is brought back to the stock.
		await input.fill(String(target.stock + 50));
		await input.dispatchEvent('input');
		await expect(input).toHaveValue(String(target.stock), {timeout: 10_000});

		//// And the + stepper stops there too.
		await grid.locator(`.wsh-qo-cell[data-item="${target.item_code}"] .wsh-qo-plus`).click();
		await expect(input).toHaveValue(String(target.stock));

		//// The − stepper walks back down, and never below zero.
		await grid.locator(`.wsh-qo-cell[data-item="${target.item_code}"] .wsh-qo-minus`).click();
		await expect(input).toHaveValue(String(target.stock - 1));
		await input.fill('0');
		await input.dispatchEvent('input');
		await grid.locator(`.wsh-qo-cell[data-item="${target.item_code}"] .wsh-qo-minus`).click();
		await expect(input).not.toHaveValue('-1');
	});

	//// Neoffice — added (42c10358d1 "fix(quick-order): produits simples tarifés par le serveur,
	//// steppers, plein écran"): a wide grid is unreadable in the page's column, so the page can
	//// take the whole screen. The button must both go in and come back out.
	test('the grid goes full screen and comes back', async ({page}) => {
		test.setTimeout(120_000);
		const template = await firstTemplate(page);
		test.skip(!template, 'no published model with variants on this shop');

		await page.goto(ROUTE);
		const field = page.locator('.wsh-qo__input');
		await field.fill(template.item_code);
		await field.press('Enter');
		await expect(page.locator(`.wsh-qo-model[data-template="${template.item_code}"]`)).toBeVisible({
			timeout: 15_000,
		});

		const button = page.locator('.wsh-qo__fullscreen');
		await expect(button).toBeVisible();
		await button.click();
		//// Native fullscreen is refused without a user gesture in some headless runs; the
		//// CSS fallback class is what the page always sets, so that is what we assert.
		await expect(page.locator('#wsh-qo')).toHaveClass(/is-fullscreen/, {timeout: 10_000});
		await button.click();
		await expect(page.locator('#wsh-qo')).not.toHaveClass(/is-fullscreen/, {timeout: 10_000});
	});

	test('the server refuses what the grid will not let anyone type either', async ({page}) => {
		test.setTimeout(120_000);
		const template = await templateWithUnorderableCells(page);
		test.skip(!template, 'no usable model on this shop');
		const forbidden = template.off[0];

		//// The browser is not the guard: posting the line straight to the endpoint
		//// must be refused, and the cart must stay as it was.
		const before = await readQuotation(page);
		const linesBefore = ((before && before.doc && before.doc.items) || []).length;
		const out = await readJson(page, '/api/method/webshop.webshop.quick_order.api.add_lines', {
			lines: JSON.stringify([{item_code: forbidden.item_code, qty: 1}]),
		});
		expect(out, 'add_lines returned nothing').toBeTruthy();
		expect(out.added, `${forbidden.item_code} was added although it should not be`).toEqual([]);
		expect((out.refused || []).length, 'no refusal reported').toBeGreaterThan(0);
		const after = await readQuotation(page);
		expect(((after && after.doc && after.doc.items) || []).length).toBe(linesBefore);
	});
});
