//// //// Neoffice — added file (no upstream equivalent).
////
//// The gate before a shop is updated at a client's.
////
//// It has two halves on purpose, because they cannot be the same check:
////
////   --rehearsal <url>   runs EVERYTHING against an instance we own (osiris, or a
////                       restored copy of the client's data). The money paths place
////                       real orders, so this half never points at a client.
////   --client <url>      runs READ-ONLY probes against the client's live shop: the
////                       pages answer, the chrome is intact (header, its search,
////                       footer), the catalogue lists products, a product page
////                       prices and offers its buy button, and every text reads on
////                       its ground. Nothing is written, nothing is bought.
////
//// A shop update is safe when the first half is green on the code being shipped and
//// the second half says the client's chrome survives it — the rehearsal proves the
//// behaviour, the probes prove this particular site still renders.
import {spawnSync} from 'node:child_process';
import fs from 'node:fs';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));

//// The pages every shop has. The home page is the site's, not the shop's: it is
//// probed for its chrome but NOT audited for contrast — a Builder home keeps its
//// content outside `<main>`, so the audit reads nothing there and would call that
//// clean (measured 2026-09-22).
const CLIENT_PAGES = ['/', '/all-products', '/shop-by-category'];
const CONTRAST_PAGES = ['/all-products', '/shop-by-category'];

function usage() {
	console.error(
		'usage: node preflight.mjs --rehearsal <url>\n' +
			'       node preflight.mjs --client <url> [--snapshot facts.json] [--baseline facts.json]'
	);
	process.exit(2);
}

//// A step's verdict, printed as one line so the whole run reads at a glance.
const results = [];
function record(name, ok, detail) {
	results.push({name, ok, detail});
	console.log(`${ok ? 'OK  ' : 'FAIL'}  ${name}${detail ? ` — ${detail}` : ''}`);
}

function run(command, args, env = {}) {
	const out = spawnSync(command, args, {
		cwd: here,
		env: {...process.env, ...env},
		encoding: 'utf8',
		stdio: ['ignore', 'pipe', 'pipe'],
	});
	return {code: out.status, text: `${out.stdout || ''}${out.stderr || ''}`};
}

//// The whole browser suite, then the payments suite when it is reachable.
function rehearsal(url) {
	console.log(`\n== rehearsal on ${url} ==\n`);

	const suite = run('npm', ['test', '--', '--reporter=list'], {WEBSHOP_E2E_URL: url});
	const summary = (suite.text.match(/^\s*\d+ (passed|failed|flaky|skipped).*$/gim) || []).join(' · ');
	record('webshop browser suite', suite.code === 0, summary || `exit ${suite.code}`);
	//// A skipped test reads exactly like a passing one: print the count, always.
	const skipped = (suite.text.match(/(\d+) skipped/) || [])[1];
	if (skipped && Number(skipped) > 0) {
		console.log(`      ${skipped} skipped — read why before trusting this run`);
	}

	//// The gateways (TWINT, Stripe, Payrexx, Wallee, invoice) live in the payments
	//// repository's own Python suite. No workflow runs it; this is what runs it.
	const payments = process.env.PAYMENTS_E2E_DIR;
	if (!payments) {
		record('payment gateways', false, 'PAYMENTS_E2E_DIR not set — the gateways were NOT tested');
	} else {
		const python = process.env.PAYMENTS_E2E_PYTHON || 'python3';
		const psp = spawnSync(python, ['-m', 'pytest', '-q', '--timeout=300'], {
			cwd: payments,
			env: {...process.env, WEBSHOP_E2E_URL: url},
			encoding: 'utf8',
		});
		const line = ((psp.stdout || '').match(/^\d+ (passed|failed).*$/m) || [])[0];
		record('payment gateways', psp.status === 0, line || `exit ${psp.status}`);
	}
}

//// Read-only probes. Everything here is a GET a visitor would make.
////
//// What matters at a client's is not whether a feature exists — shops differ, and
//// a chrome with no header search is a choice, not a defect — but whether the
//// update TOOK SOMETHING AWAY. So the probes record facts, and a run compares them
//// with the facts recorded before the update. Absolute assertions cried wolf on
//// the first site they met (2026-09-22: "no search field in the header", on a shop
//// whose header never had one).
async function client(url, {baseline = null, snapshot = null} = {}) {
	console.log(`\n== client probes on ${url} (read-only) ==\n`);
	const {chromium} = await import('playwright');
	const browser = await chromium.launch({headless: true});
	const page = await browser.newPage({baseURL: url, locale: 'fr-CH'});
	const facts = {};

	try {
		for (const route of CLIENT_PAGES) {
			const answer = await page.goto(route, {waitUntil: 'domcontentloaded'}).catch(() => null);
			const status = answer ? answer.status() : 0;
			//// A page that does not answer is a failure on its own, baseline or not.
			record(`page ${route}`, status === 200, `HTTP ${status || 'unreachable'}`);
			if (status !== 200) continue;

			//// Wait for the chrome before judging it. It is drawn by the site's own
			//// script, so reading right after `domcontentloaded` answers whatever the
			//// race happened to produce — one run reported the header present and its
			//// search missing, while a second reading of the same page found no header
			//// at all. A probe that depends on timing proves nothing.
			await page.waitForSelector('header, .site-header, #header', {timeout: 20_000}).catch(() => {});
			await page.waitForLoadState('networkidle').catch(() => {});
			Object.assign(facts, await chromeFacts(page, route));
		}

		//// The catalogue must list, and a product page must price and offer its button.
		await page.goto('/all-products', {waitUntil: 'networkidle'}).catch(() => {});
		await page.waitForSelector('a[href*="/products/"]', {timeout: 30_000}).catch(() => {});
		facts['catalogue.tiles'] = await page.locator('a[href*="/products/"]').count();
		record('catalogue lists products', facts['catalogue.tiles'] > 0, `${facts['catalogue.tiles']} links`);

		if (facts['catalogue.tiles'] > 0) {
			const route = await page.locator('a[href*="/products/"]').first().getAttribute('href');
			const answer = await page.goto(route, {waitUntil: 'domcontentloaded'}).catch(() => null);
			await page.waitForSelector('[data-item-code]', {timeout: 20_000}).catch(() => {});
			const shape = await page.evaluate(() => ({
				code: document.querySelector('[data-item-code]')?.getAttribute('data-item-code') || null,
				price: !!document.querySelector('.product-price, [itemprop="price"]'),
				buy: !!document.querySelector('.btn-add-to-cart'),
			}));
			record(
				'product page',
				(answer ? answer.status() : 0) === 200 && !!shape.code,
				shape.code || 'no item code'
			);
			facts['product.price'] = shape.price;
			facts['product.buy'] = shape.buy;
			//// A product page is where the shop draws the most: audit the real one.
			if (route) CONTRAST_PAGES.push(route.startsWith('/') ? route : `/${route}`);
		}
	} finally {
		await browser.close();
	}

	//// And the ink: the shop draws with the site's tokens, so its colours only
	//// exist once THIS chrome renders them.
	const contrast = run('node', ['visual/contrast.mjs', ...CONTRAST_PAGES], {WEBSHOP_E2E_URL: url});
	//// A page audited with nothing read proves nothing — the same trap as a skipped
	//// test reading like a passing one. A Builder home page with no <main> answers
	//// "0 elements read" and would otherwise count as clean (measured 2026-09-22).
	const mute = [...contrast.text.matchAll(/([^\s]+)\s+0 elements read/g)].map((m) => m[1]);
	const lastLine = contrast.text.trim().split('\n').filter(Boolean).pop() || '';
	record(
		'contrast audit',
		contrast.code === 0 && mute.length === 0,
		mute.length ? `nothing read on ${mute.join(', ')}` : contrast.code === 0 ? 'clean' : lastLine.slice(0, 90)
	);

	compareWithBaseline(facts, baseline);
	if (snapshot) {
		fs.writeFileSync(snapshot, JSON.stringify({url, at: new Date().toISOString(), facts}, null, 2));
		console.log(`\n      facts written to ${snapshot} — pass it as --baseline after the update`);
	}
}

/** What the site's chrome offers on this page. Facts, not judgements. */
async function chromeFacts(page, route) {
	const seen = await page.evaluate(() => {
		const head = document.querySelector('header, .site-header, #header');
		const looksLikeSearch = (el) =>
			/search|recherch/i.test(
				`${el.className || ''} ${el.getAttribute('aria-label') || ''} ${el.id || ''} ${el.name || ''}`
			);
		return {
			header: !!head,
			//// A field, or the button that opens one: both are a search to a customer,
			//// and chromes differ on which they draw.
			search: head
				? !!head.querySelector('input[type="search"], [role="search"] input') ||
					[...head.querySelectorAll('input, button, a')].some(looksLikeSearch)
				: false,
			links: head ? head.querySelectorAll('a').length : 0,
			footer: !!document.querySelector('footer, .site-footer'),
		};
	});
	console.log(
		`      ${route}: header ${seen.header ? 'yes' : 'NO'}, search ${seen.search ? 'yes' : 'no'}, ` +
			`${seen.links} header links, footer ${seen.footer ? 'yes' : 'NO'}`
	);
	return {
		[`${route}.header`]: seen.header,
		[`${route}.search`]: seen.search,
		[`${route}.links`]: seen.links,
		[`${route}.footer`]: seen.footer,
	};
}

//// A regression is something that WAS there and is not any more. Without a
//// baseline there is nothing to regress from, and the facts are printed for the
//// next run to compare against.
function compareWithBaseline(facts, baselinePath) {
	if (!baselinePath) {
		console.log('\n      no --baseline given: the facts above are the reference for next time');
		return;
	}
	const before = JSON.parse(fs.readFileSync(baselinePath, 'utf8')).facts || {};
	for (const [key, was] of Object.entries(before)) {
		const now = facts[key];
		if (now === undefined) {
			record(`baseline ${key}`, false, 'not measured this time');
		} else if (typeof was === 'boolean') {
			record(`baseline ${key}`, !(was && !now), was && !now ? 'was there before the update, gone now' : '');
		} else if (typeof was === 'number') {
			//// A tenth fewer links or tiles is noise; a third fewer is a chrome that
			//// lost a menu, or a catalogue that lost a facet.
			record(`baseline ${key}`, now >= was * 0.8, `${was} → ${now}`);
		}
	}
}

const args = process.argv.slice(2);
if (args.length === 0) usage();

const options = {baseline: null, snapshot: null};
for (let i = 0; i < args.length; i += 2) {
	if (args[i] === '--baseline') options.baseline = args[i + 1];
	if (args[i] === '--snapshot') options.snapshot = args[i + 1];
}
for (let i = 0; i < args.length; i += 2) {
	const flag = args[i];
	const value = args[i + 1];
	if (!value) usage();
	if (flag === '--rehearsal') rehearsal(value);
	else if (flag === '--client') await client(value, options);
	else if (flag !== '--baseline' && flag !== '--snapshot') usage();
}

const failed = results.filter((r) => !r.ok);
console.log(`\n${failed.length === 0 ? 'GO' : 'NO-GO'} — ${results.length - failed.length}/${results.length} checks passed`);
if (failed.length) {
	console.log(failed.map((f) => `  · ${f.name}${f.detail ? ` — ${f.detail}` : ''}`).join('\n'));
	process.exit(1);
}
