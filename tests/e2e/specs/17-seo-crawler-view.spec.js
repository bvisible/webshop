//// Neoffice — added file (no upstream equivalent).
//// The shop as a crawler reads it: raw HTML, no JavaScript. That is exactly what the
//// AI crawlers (GPTBot, ClaudeBot, PerplexityBot…) receive, and what Google Shopping
//// compares a feed with. Every assertion pins a defect measured on 2026-09-24
//// (neoffice-maintenance#691): a second Product in microdata carrying the prices of
//// other products, og:site_name "ERPNext", a robots.txt with no sitemap, a sitemap
//// with no product, listings with no canonical, a search page answering 417.

const {test, expect} = require('@playwright/test');

const CRAWLER = 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)';

async function fetchRaw(request, url, options = {}) {
	const response = await request.get(url, {headers: {'User-Agent': CRAWLER}, ...options});
	return {status: response.status(), headers: response.headers(), body: await response.text()};
}

function jsonLdBlocks(html) {
	return [...html.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)].map((match) =>
		JSON.parse(match[1])
	);
}

function metaContent(html, name) {
	const match = html.match(new RegExp(`<meta (?:name|property)="${name}" content="([^"]*)"`));
	return match ? match[1] : null;
}

function firstLoc(xml) {
	const match = xml.match(/<loc>([^<]+)<\/loc>/);
	return match ? match[1].replace(/&amp;/g, '&') : null;
}

test.describe('The shop as a crawler reads it', () => {
	test('robots.txt names the sitemap and /sitemap.xml lists the products', async ({request}) => {
		const robots = await fetchRaw(request, '/robots.txt');
		expect(robots.status).toBe(200);
		expect(robots.body).toMatch(/^Sitemap: https?:\/\/\S+$/m);

		const index = await fetchRaw(request, '/sitemap.xml');
		expect(index.status).toBe(200);
		expect(index.body).toContain('<sitemapindex');
		expect(index.body).toContain('sitemap_products.xml');

		const products = await fetchRaw(request, '/sitemap_products.xml');
		expect(products.status).toBe(200);
		expect(products.body).toContain('<url>');
		expect(products.body).not.toContain('<priority>');

		const pages = await fetchRaw(request, '/sitemap_pages.xml');
		expect(pages.status, 'the pages sitemap must never answer 500').toBe(200);
	});

	test('a product page carries one Product, in JSON-LD, at the price it shows', async ({request}) => {
		const products = await fetchRaw(request, '/sitemap_products.xml');
		const urls = [...products.body.matchAll(/<url>\s*<loc>([^<]+)<\/loc>/g)]
			.map((match) => match[1].replace(/&amp;/g, '&'))
			.slice(0, 5);
		test.skip(!urls.length, 'no product published on this site');

		for (const url of urls) {
			const page = await fetchRaw(request, url);
			expect(page.status, url).toBe(200);
			expect(page.body, `${url}: microdata is gone from the shop`).not.toMatch(/\bitemscope\b/);
			expect(metaContent(page.body, 'og:site_name'), url).not.toBe('ERPNext');
			expect(page.body, url).toMatch(/<link rel="canonical" href="https?:\/\/[^"]+">/);

			const productNodes = jsonLdBlocks(page.body).filter((node) =>
				['Product', 'ProductGroup'].includes(node['@type'])
			);
			expect(productNodes, `${url}: exactly one product entity`).toHaveLength(1);
			const offer = productNodes[0].offers;
			if (!offer) continue;
			expect(offer['@type'], url).toBe('Offer');
			expect(offer.priceCurrency, url).toMatch(/^[A-Z]{3}$/);
			expect(Number(offer.price), url).toBeGreaterThan(0);
			expect(offer.availability, url).toMatch(
				/^https:\/\/schema\.org\/(InStock|OutOfStock|BackOrder|PreOrder)$/
			);
			//// The price declared is a price the page prints (Google compares them).
			const shown = [...page.body.matchAll(/(\d[\d'’ ]*[.,]\d{2})/g)].map((m) =>
				Number(m[1].replace(/['’ ]/g, '').replace(',', '.'))
			);
			expect(shown, `${url}: the JSON-LD price ${offer.price} appears on the page`).toContain(
				Number(offer.price)
			);
			//// A struck price is declared only when the page strikes it (seo/facts.py, lot 1).
			const struck = offer.priceSpecification;
			if (struck) {
				expect(struck.priceType, url).toBe('https://schema.org/StrikethroughPrice');
				expect(Number(struck.price), url).toBeGreaterThan(Number(offer.price));
				expect(page.body, `${url}: the struck price is struck on the page`).toMatch(/<s>[^<]*\d/);
				expect(shown, `${url}: the struck price ${struck.price} appears on the page`).toContain(
					Number(struck.price)
				);
			}
			expect(offer.priceType, `${url}: the active price carries no priceType`).toBeUndefined();
			expect((productNodes[0].description || '').length, url).toBeLessThanOrEqual(5000);
		}
	});

	test('a category page says what it holds and names its address', async ({request}) => {
		const categories = await fetchRaw(request, '/sitemap_categories.xml');
		const url = firstLoc(categories.body);
		test.skip(!url, 'no category holds a product on this site');

		const page = await fetchRaw(request, url);
		expect(page.status).toBe(200);
		expect(page.body).not.toMatch(/\bitemscope\b/);
		expect(page.body).toMatch(/<link rel="canonical" href="https?:\/\/[^"]+">/);
		expect(metaContent(page.body, 'description')).toBeTruthy();
		const types = jsonLdBlocks(page.body).map((node) => node['@type']);
		expect(types, 'a list of products is not a Product').not.toContain('Product');
	});

	test('the listings name one reference address', async ({request}) => {
		for (const path of ['/all-products', '/shop-by-category']) {
			const page = await fetchRaw(request, path);
			expect(page.status, path).toBe(200);
			expect(page.body, path).toMatch(/<link rel="canonical" href="https?:\/\/[^"]+">/);
		}
		const searched = await fetchRaw(request, '/all-products?search=a');
		expect(metaContent(searched.body, 'robots')).toBe('noindex, follow');
	});

	test('private pages are not indexed, and the dead search page redirects', async ({request}) => {
		const cart = await fetchRaw(request, '/cart');
		expect(metaContent(cart.body, 'robots')).toBe('noindex, follow');

		const search = await fetchRaw(request, '/product_search?search=trail', {maxRedirects: 0});
		expect(search.status).toBe(301);
		expect(search.headers.location).toMatch(/\/all-products\?search=trail$/);
	});
});
