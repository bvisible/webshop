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

module.exports = async () => {
	const base = process.env.WEBSHOP_E2E_URL;
	const contexte = await request.newContext({baseURL: base, timeout: 60_000});

	//// Le site partagé connaît des pics à 6-7 s par requête. Un échec ici fait
	//// tomber TOUTE la suite avant le premier test, pour une lenteur passagère:
	//// trois essais espacés valent mieux qu'un abandon.
	let reponse = null;
	for (let essai = 1; essai <= 3; essai += 1) {
		try {
			reponse = await contexte.post('/api/method/login', {
				form: {usr: process.env.WEBSHOP_E2E_USER, pwd: process.env.WEBSHOP_E2E_PASSWORD},
			});
			if (reponse.ok()) break;
		} catch (err) {
			if (essai === 3) throw err;
		}
		await new Promise((r) => setTimeout(r, 5000 * essai));
	}
	if (!reponse || !reponse.ok()) {
		throw new Error(
			`Connexion impossible (${reponse ? reponse.status() : 'aucune réponse'}). Vérifiez ` +
				`~/.config/webshop-e2e.env et que le compte existe sur ${base}`
		);
	}

	fs.mkdirSync(path.dirname(FICHIER_SESSION), {recursive: true});
	await contexte.storageState({path: FICHIER_SESSION});
	await contexte.dispose();
};

module.exports.FICHIER_SESSION = FICHIER_SESSION;
