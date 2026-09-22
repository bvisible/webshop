//// Neoffice — added file (no upstream equivalent).
//// Signs in ONCE for the whole run and stores the session.
////
//// Why: Frappe rate-limits repeated sign-ins from the same address. With every
//// spec calling /api/method/login in its own beforeEach, the later specs were
//// refused and failed for a reason that had nothing to do with what they test.
//// The dialog and the login endpoint are still exercised for real — that is
//// 01-authentication's job, and it deliberately runs signed out.

const fs = require('fs');
const path = require('path');
const {request} = require('@playwright/test');

const SESSION_FILE = path.join(__dirname, '.auth', 'session.json');
const SESSION_FILE_B2B = path.join(__dirname, '.auth', 'session-b2b.json');

module.exports = async () => {
	const base = process.env.WEBSHOP_E2E_URL;
	await openSession(base, process.env.WEBSHOP_E2E_USER, SESSION_FILE, true);

	//// B2B has its own tunnel and therefore its own customer: an account whose
	//// group appears in the settings' "B2B Customer Group". Optional — without
	//// it, the B2B specs skip themselves and say so.
	if (process.env.WEBSHOP_E2E_B2B_USER) {
		await openSession(base, process.env.WEBSHOP_E2E_B2B_USER, SESSION_FILE_B2B, false);
	}
};

async function openSession(base, user, file, required) {
	const context = await request.newContext({baseURL: base, timeout: 60_000});

	//// Five spaced-out tries. The shared site intermittently answers 404 (yes,
	//// 404) on /api/method/login when it is under load — measured at load 6-8
	//// with 230 MB of free RAM, another service saturating the machine. The
	//// same call in curl answers 200 a second later. Without these retries, the
	//// ENTIRE suite falls before the first test, over a passing slowdown that
	//// has nothing to do with the shop.
	let answer = null;
	let lastError = null;
	for (let attempt = 1; attempt <= 5; attempt += 1) {
		try {
			answer = await context.post('/api/method/login', {
				form: {usr: user, pwd: process.env.WEBSHOP_E2E_PASSWORD},
			});
			if (answer.ok()) break;
			lastError = `HTTP ${answer.status()}`;
		} catch (error) {
			lastError = error.message.split('\n')[0];
		}
		if (attempt < 5) await new Promise((r) => setTimeout(r, 4000 * attempt));
	}
	if (!answer || !answer.ok()) {
		await context.dispose();
		if (!required) {
			//// A missing optional session must not bring down the suite: the specs
			//// that depend on it will see the missing file.
			console.warn(`[e2e] session ${user} unavailable — the specs that need it are skipped`);
			return;
		}
		throw new Error(
			`Could not sign in after 5 attempts (${lastError}) for ${user} on ${base}.\n` +
				'A 404 or a timeout on /api/method/login is most often an overloaded server,\n' +
				'not a wrong password: check `ssh osiris uptime` before ~/.config/webshop-e2e.env.'
		);
	}

	fs.mkdirSync(path.dirname(file), {recursive: true});
	await context.storageState({path: file});
	await context.dispose();
}

module.exports.SESSION_FILE = SESSION_FILE;
module.exports.SESSION_FILE_B2B = SESSION_FILE_B2B;
