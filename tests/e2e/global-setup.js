//// Neoffice — added file (no upstream equivalent).
//// Signs in ONCE for the whole run and stores the session.
////
//// Why: Frappe rate-limits repeated sign-ins from the same address. With every
//// spec calling /api/method/login in its own beforeEach, the later specs were
//// refused and failed for a reason that had nothing to do with what they test.
//// The dialog and the login endpoint are still exercised for real — that is
//// 01-authentification's job, and it deliberately runs signed out.

const fs = require('fs');
const path = require('path');
const {request} = require('@playwright/test');

const FICHIER_SESSION = path.join(__dirname, '.auth', 'session.json');
const FICHIER_SESSION_B2B = path.join(__dirname, '.auth', 'session-b2b.json');

module.exports = async () => {
	const base = process.env.WEBSHOP_E2E_URL;
	await ouvrirSession(base, process.env.WEBSHOP_E2E_USER, FICHIER_SESSION, true);

	//// B2B has its own tunnel and therefore its own customer: an account whose
	//// group appears in the settings' « B2B Customer Group ». Optional —
	//// without it, the B2B specs skip themselves and say so.
	if (process.env.WEBSHOP_E2E_B2B_USER) {
		await ouvrirSession(base, process.env.WEBSHOP_E2E_B2B_USER, FICHIER_SESSION_B2B, false);
	}
};

async function ouvrirSession(base, utilisateur, fichier, obligatoire) {
	const contexte = await request.newContext({baseURL: base, timeout: 60_000});

	//// The shared site sees spikes of 6-7 s per request. A failure here brings
	//// down the ENTIRE suite before the first test, for a passing slowdown:
	//// three spaced-out tries beat giving up.
	//// Five spaced-out tries. The shared site intermittently answers 404 (yes,
	//// 404) on /api/method/login when it is under load — measured at load 6-8
	//// with 230 MB of free RAM, another service saturating the machine. The
	//// same call in curl answers 200 a second later. Without these retries, the
	//// ENTIRE suite falls before the first test, over a passing slowdown that
	//// has nothing to do with the shop.
	let reponse = null;
	let derniereErreur = null;
	for (let essai = 1; essai <= 5; essai += 1) {
		try {
			reponse = await contexte.post('/api/method/login', {
				form: {usr: utilisateur, pwd: process.env.WEBSHOP_E2E_PASSWORD},
			});
			if (reponse.ok()) break;
			derniereErreur = `HTTP ${reponse.status()}`;
		} catch (err) {
			derniereErreur = err.message.split('\n')[0];
		}
		if (essai < 5) await new Promise((r) => setTimeout(r, 4000 * essai));
	}
	if (!reponse || !reponse.ok()) {
		await contexte.dispose();
		if (!obligatoire) {
			//// A missing optional session must not bring down the suite: the specs
			//// that depend on it will see the missing file.
			console.warn(`[e2e] session ${utilisateur} indisponible — specs associées ignorées`);
			return;
		}
		throw new Error(
			`Connexion impossible après 5 essais (${derniereErreur}) pour ${utilisateur} sur ${base}.\n` +
				'Un 404 ou un délai dépassé sur /api/method/login est le plus souvent un serveur\n' +
				'surchargé, pas un mauvais mot de passe : vérifiez `ssh osiris uptime` avant\n' +
				'~/.config/webshop-e2e.env.'
		);
	}

	fs.mkdirSync(path.dirname(fichier), {recursive: true});
	await contexte.storageState({path: fichier});
	await contexte.dispose();
}

module.exports.FICHIER_SESSION = FICHIER_SESSION;
module.exports.FICHIER_SESSION_B2B = FICHIER_SESSION_B2B;
