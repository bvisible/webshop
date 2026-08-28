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

const {expect} = require('@playwright/test');

const URL_B2C = process.env.WEBSHOP_E2E_URL;
const URL_B2B = process.env.WEBSHOP_E2E_B2B_URL;

/** Is a second domain configured for this run? */
function multiSiteDisponible() {
	return Boolean(URL_B2C && URL_B2B && URL_B2C !== URL_B2B);
}

/** A fresh, signed-out context pinned to one domain. */
async function ouvrirSite(browser, url) {
	const contexte = await browser.newContext({baseURL: url, locale: 'fr-CH'});
	return {contexte, page: await contexte.newPage()};
}

//// Sign in on this domain with the account that is allowed there.
////
//// A b2b_only site has no anonymous cart at all: update_cart answers 403 and
//// /cart redirects. Anything that needs a cart there must therefore sign in —
//// with the B2B account, since the consumer one is refused at the door.
async function connecterSurSite(page, url) {
	const estB2B = URL_B2B && url === URL_B2B;
	const utilisateur = estB2B
		? process.env.WEBSHOP_E2E_B2B_USER || process.env.WEBSHOP_E2E_USER
		: process.env.WEBSHOP_E2E_USER;
	if (!utilisateur) return false;

	const r = await page.request.post('/api/method/login', {
		form: {usr: utilisateur, pwd: process.env.WEBSHOP_E2E_PASSWORD},
	});
	return r.ok();
}

/** POST a whitelisted method on a given domain and return its message. */
async function appelSite(page, methode, donnees = null) {
	let r;
	try {
		r = await page.request.post(`/api/method/${methode}`, donnees ? {form: donnees} : undefined);
	} catch (err) {
		return null;
	}
	if (!r.ok()) return null;
	try {
		return JSON.parse(await r.text()).message ?? null;
	} catch (err) {
		return null;
	}
}

//// The catalogue as this domain serves it: item codes and their prices.
//// Goes through the shop's own listing endpoint — the one the storefront uses —
//// so the test sees what a shopper sees, not what the database holds.
async function catalogueDuSite(page, recherche = null) {
	const r = await page.request.post(
		'/api/method/webshop.webshop.api.get_product_filter_data',
		{
			headers: {'Content-Type': 'application/json'},
			data: {
				query_args: {
					start: 0,
					field_filters: {},
					attribute_filters: {},
					...(recherche ? {search: recherche} : {}),
				},
			},
		}
	);
	if (!r.ok()) return [];
	try {
		const message = JSON.parse(await r.text()).message || {};
		return (message.items || []).map((i) => ({
			item_code: i.item_code,
			prix: i.price_list_rate,
				route: i.route || null,
		}));
	} catch (err) {
		return [];
	}
}

/** Price this domain quotes for one item in the SEARCH results. */
async function prixRecherche(page, itemCode) {
	const message = await appelSite(page, 'webshop.webshop.api.get_product_price_info', {
		items: JSON.stringify([itemCode]),
	});
	const info = message && message[itemCode];
	return info ? info.price_list_rate : null;
}

//// Price this domain actually CHARGES: empty the cart, add the item, read the
//// quotation back. This is the number that matters — the other two are
//// promises, this one is the bill.
async function prixPanier(page, itemCode) {
	const devis = await appelSite(page, 'webshop.webshop.shopping_cart.cart.get_cart_quotation');
	for (const ligne of (devis && devis.doc && devis.doc.items) || []) {
		await appelSite(page, 'webshop.webshop.shopping_cart.cart.update_cart', {
			item_code: ligne.item_code,
			qty: 0,
			...(ligne.warehouse ? {warehouse: ligne.warehouse} : {}),
		});
	}
	await appelSite(page, 'webshop.webshop.shopping_cart.cart.update_cart', {
		item_code: itemCode,
		qty: 1,
	});
	const apres = await appelSite(page, 'webshop.webshop.shopping_cart.cart.get_cart_quotation');
	const doc = (apres && apres.doc) || {};
	const ligne = (doc.items || []).find((l) => l.item_code === itemCode);
	return {
		liste: doc.selling_price_list || null,
		prix: ligne ? ligne.rate : null,
	};
}

module.exports = {
	URL_B2C,
	URL_B2B,
	multiSiteDisponible,
	ouvrirSite,
	connecterSurSite,
	appelSite,
	catalogueDuSite,
	prixRecherche,
	prixPanier,
};
