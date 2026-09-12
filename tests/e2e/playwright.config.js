//// Neoffice — added file (no upstream equivalent).
//// Browser-level tests for the shop. The Python suite covers the endpoints;
//// this covers what the endpoints cannot: that the pages actually work in a
//// browser — sign-in, cart, and the four-step checkout — which until now was
//// only ever verified by hand, script by script, and therefore never replayed.

const fs = require('fs');
const os = require('os');
const path = require('path');
const {defineConfig, devices} = require('@playwright/test');

//// Credentials live outside the repository, in ~/.config/webshop-e2e.env
//// (chmod 600), never in git. Environment variables win, so CI can inject them.
function lireSecrets() {
	const fichier = path.join(os.homedir(), '.config', 'webshop-e2e.env');
	if (!fs.existsSync(fichier)) return;
	for (const ligne of fs.readFileSync(fichier, 'utf8').split('\n')) {
		const m = ligne.match(/^([A-Z0-9_]+)=(.*)$/);
		if (m && !process.env[m[1]]) process.env[m[1]] = m[2];
	}
}
lireSecrets();

//// Written by global-setup before any test runs; gitignored (they hold cookies).
const SESSION = path.join(__dirname, '.auth', 'session.json');
const SESSION_B2B = path.join(__dirname, '.auth', 'session-b2b.json');

if (!process.env.WEBSHOP_E2E_URL) {
	throw new Error(
		'WEBSHOP_E2E_URL manquant. Créez ~/.config/webshop-e2e.env (voir README.md).'
	);
}

module.exports = defineConfig({
	testDir: './specs',
	//// The target is a shared development site: tests must not race each other
	//// through the same cart. One worker, in file order.
	workers: 1,
	fullyParallel: false,
	//// A flaky test that passes on retry is still a signal, so retries are on
	//// but the report says "flaky" rather than "passed".
	retries: process.env.CI ? 2 : 1,
	timeout: 90_000,
	expect: {timeout: 20_000},
	reporter: process.env.CI ? [['github'], ['list']] : [['list']],
	use: {
		baseURL: process.env.WEBSHOP_E2E_URL,
		locale: 'fr-CH',
		//// Kept on failure only: a trace is heavy, but it is the difference
		//// between "the checkout broke" and knowing which call broke it.
		trace: 'retain-on-failure',
		screenshot: 'only-on-failure',
		video: 'retain-on-failure',
		actionTimeout: 20_000,
		navigationTimeout: 45_000,
	},
	globalSetup: require.resolve('./global-setup'),
	projects: [
		{
			//// Runs signed OUT: sign-in, account creation and what a visitor must
			//// not reach are precisely the subject here.
			name: 'invite',
			//// Neoffice — 08-assistant added: its signed-out tests (no first name in the
			//// greeting, the guest's email field on the team form) skipped forever, since
			//// this project never matched the file and a conditional skip reads as a pass.
			//// Neoffice — 11-contraste added: the public pages are audited signed out, the way a
			//// visitor of a client's shop sees them.
			testMatch: /(01-authentification|07-nouveau-client|08-assistant|10-quick-order|11-contraste)\.spec\.js/,
			use: {...devices['Desktop Chrome']},
		},
		{
			//// Everything else reuses the session opened once by global-setup,
			//// so Frappe's sign-in rate limit never fails an unrelated test.
			name: 'client',
			//// Neither authentication (which runs signed out) nor B2B (which has
			//// its own customer): leaving them here made eleven specs fail for the
			//// sole reason that the session wasn't the right one.
			testIgnore: /(01-authentification|06-checkout-b2b|07-nouveau-client|08-multi-site|09-demande-compte-pro)\.spec\.js/,
			use: {...devices['Desktop Chrome'], storageState: SESSION},
		},
		{
			//// B2B has its own tunnel, its own customer, and therefore its own
			//// session: an account whose group appears in the settings' « B2B
			//// Customer Group ».
			name: 'b2b',
			//// Neoffice — 10-quick-order added: the reseller's quick order needs the B2B session.
			testMatch: /(06-checkout-b2b|10-quick-order)\.spec\.js/,
			use: {...devices['Desktop Chrome'], storageState: SESSION_B2B},
		},
		{
			//// Drives BOTH domains from the same run, signed out: it's the
			//// boundary between the shops that is being tested, not their content.
			name: 'multi-site',
			testMatch: /(08-multi-site|09-demande-compte-pro)\.spec\.js/,
			use: {...devices['Desktop Chrome']},
		},
		{
			name: 'mobile',
			//// The mobile pass only re-runs what has a distinct mobile layout.
			testMatch: /(catalogue|panier)\.spec\.js/,
			use: {...devices['Pixel 7'], storageState: SESSION},
		},
	],
});
