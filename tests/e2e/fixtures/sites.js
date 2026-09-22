//// Neoffice — added file (no upstream equivalent).
//// Helpers for the multi-site (multi-domain) setup.
////
//// One Frappe site serves several shops, one per domain, described by the
//// "Website Profile" doctype (neoffice_theme): its own home page, its own
//// price list, its own catalogue subset, and — for a professional shop — a
//// b2b_only flag restricting who may sign in.
////
//// These helpers reach BOTH domains from the same run, so a test can assert
//// what separates them. Playwright pins one baseURL per project, hence the
//// explicit contexts here.

const URL_B2C = process.env.WEBSHOP_E2E_URL;
const URL_B2B = process.env.WEBSHOP_E2E_B2B_URL;

/** Is a second domain configured for this run? */
function multiSiteAvailable() {
	return Boolean(URL_B2C && URL_B2B && URL_B2C !== URL_B2B);
}

/** A fresh, signed-out context pinned to one domain. */
async function openSite(browser, url) {
	const context = await browser.newContext({baseURL: url, locale: 'fr-CH'});
	return {context, page: await context.newPage()};
}

//// Sign in on this domain with the account that is allowed there.
////
//// A b2b_only site has no anonymous cart at all: update_cart answers 403 and
//// /cart redirects. Anything that needs a cart there must therefore sign in —
//// with the B2B account, since the consumer one is refused at the door.
async function signInOnSite(page, url) {
	const isB2B = URL_B2B && url === URL_B2B;
	const user = isB2B
		? process.env.WEBSHOP_E2E_B2B_USER || process.env.WEBSHOP_E2E_USER
		: process.env.WEBSHOP_E2E_USER;
	if (!user) return false;

	const r = await page.request.post('/api/method/login', {
		form: {usr: user, pwd: process.env.WEBSHOP_E2E_PASSWORD},
	});
	return r.ok();
}

/** POST a whitelisted method on a given domain and return its message. */
async function callOnSite(page, method, form = null) {
	let r;
	try {
		r = await page.request.post(`/api/method/${method}`, form ? {form} : undefined);
	} catch (error) {
		return null;
	}
	if (!r.ok()) return null;
	try {
		return JSON.parse(await r.text()).message ?? null;
	} catch (error) {
		return null;
	}
}

//// The catalogue as this domain serves it: item codes and their prices.
//// Goes through the shop's own listing endpoint — the one the storefront uses —
//// so the test sees what a shopper sees, not what the database holds.
async function siteCatalogue(page, search = null) {
	const r = await page.request.post('/api/method/webshop.webshop.api.get_product_filter_data', {
		headers: {'Content-Type': 'application/json'},
		data: {
			query_args: {
				start: 0,
				field_filters: {},
				attribute_filters: {},
				...(search ? {search} : {}),
			},
		},
	});
	if (!r.ok()) return [];
	try {
		const message = JSON.parse(await r.text()).message || {};
		return (message.items || []).map((i) => ({
			item_code: i.item_code,
			price: i.price_list_rate,
			route: i.route || null,
		}));
	} catch (error) {
		return [];
	}
}

/** Price this domain quotes for one item in the SEARCH results. */
async function searchPrice(page, itemCode) {
	const message = await callOnSite(page, 'webshop.webshop.api.get_product_price_info', {
		items: JSON.stringify([itemCode]),
	});
	const info = message && message[itemCode];
	return info ? info.price_list_rate : null;
}

//// Price this domain actually CHARGES: empty the cart, add the item, read the
//// quotation back. This is the number that matters — the other two are
//// promises, this one is the bill.
async function cartPrice(page, itemCode) {
	const quotation = await callOnSite(page, 'webshop.webshop.shopping_cart.cart.get_cart_quotation');
	for (const line of (quotation && quotation.doc && quotation.doc.items) || []) {
		await callOnSite(page, 'webshop.webshop.shopping_cart.cart.update_cart', {
			item_code: line.item_code,
			qty: 0,
			...(line.warehouse ? {warehouse: line.warehouse} : {}),
		});
	}
	await callOnSite(page, 'webshop.webshop.shopping_cart.cart.update_cart', {
		item_code: itemCode,
		qty: 1,
	});
	const after = await callOnSite(page, 'webshop.webshop.shopping_cart.cart.get_cart_quotation');
	const doc = (after && after.doc) || {};
	const line = (doc.items || []).find((l) => l.item_code === itemCode);
	return {
		list: doc.selling_price_list || null,
		price: line ? line.rate : null,
	};
}

module.exports = {
	URL_B2C,
	URL_B2B,
	multiSiteAvailable,
	openSite,
	signInOnSite,
	callOnSite,
	siteCatalogue,
	searchPrice,
	cartPrice,
};
