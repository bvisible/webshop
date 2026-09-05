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
			testMatch: /(01-authentification|07-nouveau-client|08-assistant)\.spec\.js/,
			use: {...devices['Desktop Chrome']},
		},
		{
			//// Everything else reuses the session opened once by global-setup,
			//// so Frappe's sign-in rate limit never fails an unrelated test.
			name: 'client',
			//// Ni l'authentification (qui tourne déconnectée), ni le B2B (qui a
			//// son propre client): les y laisser faisait échouer onze specs pour
			//// la seule raison que la session n'était pas la bonne.
			testIgnore: /(01-authentification|06-checkout-b2b|07-nouveau-client|08-multi-site|09-demande-compte-pro)\.spec\.js/,
			use: {...devices['Desktop Chrome'], storageState: SESSION},
		},
		{
			//// Le B2B a son propre tunnel, son propre client, et donc sa propre
			//// session: un compte dont le groupe figure dans les « B2B Customer
			//// Group » des réglages.
			name: 'b2b',
			testMatch: /06-checkout-b2b\.spec\.js/,
			use: {...devices['Desktop Chrome'], storageState: SESSION_B2B},
		},
		{
			//// Pilote les DEUX domaines depuis le même run, déconnecté: c'est la
			//// frontière entre les boutiques qui est éprouvée, pas leur contenu.
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
