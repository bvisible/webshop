//// Neoffice — added file (no upstream equivalent).
//// Shared helpers. Everything that is *not* the subject of a test happens
//// through the API here: signing in via the dialog is tested once, in
//// 01-authentication, and every other spec logs in through /api/method/login
//// so a broken dialog fails one test instead of the whole suite.

const {expect} = require('@playwright/test');

const CREDENTIALS = {
	user: process.env.WEBSHOP_E2E_USER,
	password: process.env.WEBSHOP_E2E_PASSWORD,
};

//// Signing in again when the stored session is already valid is what tripped
//// Frappe's rate limit and failed unrelated specs. Check first, sign in only
//// if needed.
async function signIn(page, credentials = CREDENTIALS) {
	if ((await currentUser(page)) === credentials.user) return;

	if (!credentials.user || !credentials.password) {
		throw new Error('WEBSHOP_E2E_USER / WEBSHOP_E2E_PASSWORD missing');
	}
	//// Three spaced-out tries: the site intermittently refuses (404, 417,
	//// timeout) when under load or when attempts follow each other closely. A
	//// failure here brings down a test that has nothing to do with signing in.
	let answer = null;
	for (let attempt = 1; attempt <= 3; attempt += 1) {
		try {
			answer = await page.request.post('/api/method/login', {
				form: {usr: credentials.user, pwd: credentials.password},
			});
			if (answer.ok()) return;
		} catch (error) {
			answer = null;
		}
		if (attempt < 3) await page.waitForTimeout(4000 * attempt);
	}
	expect(
		answer && answer.ok(),
		`sign-in refused (${answer ? answer.status() : 'no answer'}) after 3 attempts — ` +
			"server under load, or Frappe's attempt limit?"
	).toBeTruthy();
}

/** The logged-in user as the server sees it — the only trustworthy check. */
async function currentUser(page) {
	const r = await page.request.get('/api/method/frappe.auth.get_logged_user');
	if (!r.ok()) return 'Guest';
	const body = await r.json();
	return body.message || 'Guest';
}

/** Call a whitelisted method from the page's own session. */
async function callMethod(page, method, args = {}) {
	return page.evaluate(
		([m, a]) =>
			new Promise((res) =>
				frappe.call({method: m, args: a, callback: (r) => res(r.message), error: () => res(null)})
			),
		[method, args]
	);
}

//// Empty the cart so a spec never inherits the previous one's state.
////
//// Goes through page.request rather than page.evaluate + frappe.call: the same
//// endpoints, without a page load or a round trip through the DOM for each
//// line. Emptying a cart of a dozen lines used to blow the 90 s test budget.
async function emptyCart(page) {
	//// Several passes: one is not always enough. The cart can carry two lines
	//// of the same item (two warehouses), and an update_cart call that fails —
	//// the site intermittently refuses under load — used to leave lines
	//// behind. The next spec would then find a supposedly "empty" cart holding
	//// three items and blame the page.
	for (let pass = 1; pass <= 3; pass += 1) {
		const quotation = await readQuotation(page);
		const lines = (quotation && quotation.doc && quotation.doc.items) || [];
		if (lines.length === 0) return true;

		//// Deliberately sequential: two concurrent update_cart calls write to the
		//// same quotation and the last one overwrites the first.
		for (const line of lines) {
			await page.request.post('/api/method/webshop.webshop.shopping_cart.cart.update_cart', {
				form: {
					item_code: line.item_code,
					qty: 0,
					...(line.warehouse ? {warehouse: line.warehouse} : {}),
				},
			});
		}
		await page.waitForTimeout(1000);
	}

	const left = await readQuotation(page);
	return ((left && left.doc && left.doc.items) || []).length === 0;
}

/** The cart quotation, read over HTTP (no page needed). */
async function readQuotation(page) {
	return readJson(page, '/api/method/webshop.webshop.shopping_cart.cart.get_cart_quotation');
}

//// POST an endpoint and return its message, or null.
////
//// Never lets a non-JSON body throw: under load the site answers 200 with an
//// HTML error page, and `await r.json()` then dies with "Unexpected token '<'"
//// — an error that says nothing about what actually went wrong, three call
//// levels away from the test that will be blamed for it.
async function readJson(page, path, form = null) {
	let r;
	try {
		//// 45 s, not the suite's 20 s default: a shared server under load answers
		//// slowly but correctly, and a poll that gives up at 20 s turns a purchase
		//// that worked into "the checkout is broken".
		r = await page.request.post(path, {
			...(form ? {form} : {}),
			timeout: 45_000,
		});
	} catch (error) {
		return null;
	}
	if (!r.ok()) return null;
	const body = await r.text();
	try {
		return JSON.parse(body).message ?? null;
	} catch (error) {
		return null;
	}
}

/** The customer's address book, read over HTTP. */
async function readAddressBook(page) {
	return (
		(await readJson(page, '/api/method/webshop.webshop.shopping_cart.cart.get_customer_addresses')) ||
		[]
	);
}

/** Add an item to the cart, optionally from a given warehouse. */
async function addToCart(page, itemCode, qty = 1, warehouse = null) {
	const r = await page.request.post('/api/method/webshop.webshop.shopping_cart.cart.update_cart', {
		form: {item_code: itemCode, qty, ...(warehouse ? {warehouse} : {})},
	});
	return r.ok();
}

/** Count the XHR/fetch calls a block of work triggers. */
async function countRequests(page, work) {
	const before = await page.evaluate(
		() =>
			performance.getEntriesByType('resource').filter((r) => /xmlhttprequest|fetch/.test(r.initiatorType))
				.length
	);
	await work();
	return (
		(await page.evaluate(
			() =>
				performance
					.getEntriesByType('resource')
					.filter((r) => /xmlhttprequest|fetch/.test(r.initiatorType)).length
		)) - before
	);
}

//// The shipping radios carry class "hide": the visible, clickable thing is the
//// styled label. Clicking the input itself is what a script would do; clicking
//// the label is what a customer does — and only the latter is possible.
async function chooseShipping(page, index = 0) {
	const radios = page.locator('#step-shipping input[type=radio]');
	if ((await radios.count()) === 0) return null;

	const radio = radios.nth(index);
	//// Choosing is not the same as having chosen. The shipping block is redrawn
	//// when the server recomputes the rules for the address just entered, and a
	//// click that lands during that redraw is wiped: the step then refuses to
	//// advance, asking again for a shipping method, and the failure surfaces
	//// three helpers away, on `#step-payment` (measured 2026-09-22).
	for (let attempt = 1; attempt <= 3 && !(await radio.isChecked()); attempt++) {
		const id = await radio.getAttribute('id');
		const label = id ? page.locator(`label[for="${cssEscape(id)}"]`) : null;
		if (label && (await label.count()) && (await label.first().isVisible())) {
			await label
				.first()
				.click()
				.catch(() => {});
		} else {
			//// Fallback: the design does not expose a clickable label.
			await radio.check({force: true}).catch(() => {});
			await radio.dispatchEvent('change').catch(() => {});
		}
		await expect(radio)
			.toBeChecked({timeout: 10_000})
			.catch(() => {});
	}
	await expect(radio, 'the shipping method does not stay selected').toBeChecked({timeout: 10_000});
	await page.waitForTimeout(1500);
	return radio.getAttribute('value');
}

//// Walk a filled cart from /checkout to the payment step.
//// Shared by every payment scenario so the journey is written once.
async function goToPaymentStep(page) {
	//// Do NOT reload if already on the tunnel: a goto wipes out an address
	//// form that was just filled in, and the next step then stays
	//// unreachable — a failure that blames checkout when it actually comes
	//// from the helper.
	if (!page.url().includes('/checkout')) {
		await page.goto('/checkout');
		await page.waitForLoadState('networkidle');
	}
	await expect(page.locator('#step-address')).toHaveClass(/active/, {timeout: 40_000});

	//// Filling in an address opens a confirmation dialog ("save these details?").
	//// It must be accepted, like a customer would: without that, the step never
	//// advances and the test concludes the tunnel is blocked.
	await advanceToStep(page, '#step-address .next-step', '#step-shipping');

	if ((await page.locator('#step-shipping input[type=radio]').count()) === 0) return false;
	await chooseShipping(page);

	await advanceToStep(page, '#step-shipping .next-step', '#step-payment');
	await expect
		.poll(() => page.locator('.payment-method-item').count(), {timeout: 40_000})
		.toBeGreaterThan(0);
	return true;
}

//// Ask for the next step until it opens, rather than wait 45 s on one click.
////
//// A click that lands before the step's own script is bound does nothing at all,
//// and the wait that follows blames the checkout for a click it never received:
//// two runs died on `#step-address` and `#step-shipping` this way (2026-09-22),
//// on a tunnel a customer walks through without noticing. Pressing again is what
//// a customer does too.
////
//// A step that genuinely refuses to open must FAIL, never answer false: the
//// callers turn a false into a skip ("no shipping method offered"), and a
//// blocked tunnel would report itself green.
async function advanceToStep(page, trigger, step, attempts = 3) {
	const target = page.locator(step);
	for (let attempt = 1; attempt <= attempts; attempt++) {
		//// Never press again while the previous press is still in flight. Pressing
		//// twice sends two writes to the SAME quotation, and MariaDB answers with a
		//// deadlock: the checkout then shows "error updating the address" and the
		//// step never opens — the retry causing the very failure it was added to
		//// survive (measured 2026-09-22, Error Log: QueryDeadlockError).
		if (attempt > 1) {
			await page.waitForLoadState('networkidle', {timeout: 15_000}).catch(() => {});
			await page.waitForTimeout(3_000);
		}
		await page
			.locator(trigger)
			.click({timeout: 15_000})
			.catch(() => {});
		await confirmDialog(page);
		try {
			await expect(target).toHaveClass(/active/, {timeout: attempt === attempts ? 45_000 : 20_000});
			return;
		} catch (error) {
			if (attempt === attempts) throw error;
		}
	}
}

//// Accept the address-confirmation dialog, if one opened.
////
//// Only appears when the form actually changed — a returning customer who picks
//// a saved card never sees it, a first-time buyer typing their address always
//// does. Silent no-op when there is no dialog.
async function confirmDialog(page) {
	const modal = page.locator('.modal.show, .modal.in').first();
	try {
		await modal.waitFor({state: 'visible', timeout: 8000});
	} catch (error) {
		return false; // no dialog: nothing to confirm
	}

	//// The pattern carries the shop's own button labels, which are what a
	//// customer reads: the fleet runs in French, so the French words have to be
	//// in here for the click to land. Everything else in this file is English.
	const button = modal
		.locator('button.btn-primary, .btn-modal-primary, button')
		.filter({hasText: /confirmer|valider|oui|continuer|confirm|yes|continue|ok/i})
		.first();
	if ((await button.count()) === 0) return false;

	await button.click();
	await modal.waitFor({state: 'hidden', timeout: 30_000}).catch(() => {});
	await page.waitForTimeout(2500);
	return true;
}

/** Escape a value for use inside a CSS attribute selector. */
function cssEscape(value) {
	return value.replace(/["\\]/g, '\\$&');
}

//// Read the catalogue the way a customer does — from the shop pages.
////
//// The obvious version asked frappe.client.get_list for Website Items and got a
//// clean 403: a Website User is not allowed to list doctypes through the
//// generic API, which is exactly right (see 01-authentication). Every spec
//// that depended on it was silently skipped, and the run still reported
//// "18 passed" — a green suite that tested almost nothing.
async function firstBuyableItem(page) {
	//// Several candidates: the newest product often is a second-hand unit
	//// (one of a kind, one in stock), which no test can buy twice or keep in
	//// its cart once somebody else has ordered it.
	for (const route of await catalogueItems(page, 6)) {
		const code = await itemCodeOnPage(page, route);
		if (!code || /-USED-\d+$/.test(code)) continue;
		//// Only the product's own condition block: since the recommendations carousel
		//// badges its used items too, a page-wide count rejected every product whose
		//// neighbours included one, and the whole suite skipped itself.
		if (await page.locator('.product-condition, .wsp-buy .condition-badge, .condition-info').count())
			continue;
		//// Neither a template (its buy button waits for a choice of variant and the code
		//// read above is the template's, off the wishlist heart) nor a gift card (no price
		//// line, an amount to pick): the specs want an ordinary article.
		if (await page.locator('.variant-selection-section, .btn-add-to-cart.is-gift-card').count()) continue;
		return {route, item_code: code};
	}
	return null;
}

//// Routes only — one page load, no matter how many are asked for.
//// Resolving every item_code up front meant navigating to each product page,
//// so asking for 25 candidates cost 26 navigations before a single assertion.
async function catalogueItems(page, howMany = 8) {
	await page.goto('/all-products');
	await page.waitForLoadState('networkidle');
	//// The tiles are drawn by the listing's own script, which can land after the
	//// page reports itself idle: reading the links right then answers "no product",
	//// and every spec that needs one fails on a catalogue that is perfectly fine
	//// (measured 2026-09-22, flaky on the first attempt, green on the retry).
	await page.waitForSelector('a[href*="/products/"]', {timeout: 30_000}).catch(() => {});

	return page.evaluate((max) => {
		const seen = new Set();
		for (const a of document.querySelectorAll('a[href*="/products/"]')) {
			const path = new URL(a.href, location.origin).pathname.replace(/^\//, '');
			if (path.startsWith('products/')) seen.add(path);
			if (seen.size >= max) break;
		}
		return [...seen];
	}, howMany);
}

/** Navigate to a product page and read the item code it carries. */
async function itemCodeOnPage(page, route) {
	await page.goto('/' + route);
	await page.waitForLoadState('domcontentloaded');
	//// Wait for the buy column to exist before reading its code. Parsed HTML is not
	//// a rendered page: read too early, every candidate answers "no code", the
	//// helper says "no buyable article in the catalogue", and the blame lands on a
	//// catalogue that is perfectly fine (measured 2026-09-22 — flaky, green on the
	//// retry, which is the worst kind of green).
	await page
		.waitForSelector('.product-page-content [data-item-code], [data-item-code]', {timeout: 20_000})
		.catch(() => {});
	//// The buy button first: the theme's cart drawer lives in the header and
	//// its lines carry data-item-code too.
	return page.evaluate(() => {
		const e =
			document.querySelector(
				'.product-page-content .btn-add-to-cart[data-item-code]:not([data-item-code=""])'
			) ||
			document.querySelector('.product-page-content [data-item-code]') ||
			document.querySelector('[data-item-code]');
		return e ? e.getAttribute('data-item-code') : null;
	});
}

module.exports = {
	CREDENTIALS,
	signIn,
	currentUser,
	callMethod,
	emptyCart,
	countRequests,
	chooseShipping,
	goToPaymentStep,
	confirmDialog,
	firstBuyableItem,
	catalogueItems,
	itemCodeOnPage,
	readQuotation,
	readJson,
	readAddressBook,
	addToCart,
};
