//// Neoffice — added file (no upstream equivalent).
//// Activating a freshly created account, the way a real customer does.
////
//// create_account() creates the User WITHOUT a password and sends a welcome
//// e-mail carrying an activation link. The customer clicks that link, chooses a
//// password, and only then can sign in. A test that wants to go from "I create
//// my account" to "I paid" therefore has to walk through that link.
////
//// Reading the e-mail itself is not an option here: this site's default
//// outgoing account is `_Test Comm Account 1` (test_comm@example.com) and its
//// mail queue is in error — nothing ever leaves, so no inbox (Yopmail or
//// otherwise) would ever receive anything. The link is read from the User
//// record instead, which is the same value the e-mail would carry.
////
//// Requires WEBSHOP_E2E_SSH_HOST and WEBSHOP_E2E_SITE. Without them, the
//// scenarios that need activation skip themselves and say so.

const {execFileSync} = require('child_process');
const {expect} = require('@playwright/test');

let derniereRaison = '';
const HOTE = process.env.WEBSHOP_E2E_SSH_HOST;
const SITE = process.env.WEBSHOP_E2E_SITE;

/** Can this run reach the server to activate an account? */
function activationDisponible() {
	return Boolean(HOTE && SITE);
}

//// Run a snippet inside the site's Python environment and return its stdout.
//// Kept to single-purpose read/delete helpers — never a general escape hatch.
////
//// The script travels on STDIN, not as a `python -c "…"` argument: quoting a
//// multi-line Python snippet through a shell, through ssh, through
//// execFileSync is three levels of escaping and it broke on the first one.
function surLeServeur(extrait) {
	const script = `import frappe\nfrappe.init(site="${SITE}")\nfrappe.connect()\n${extrait}\n`;
	return execFileSync(
		'ssh',
		[HOTE, 'cd /home/neoffice/frappe-bench/sites && ../env/bin/python -'],
		{input: script, encoding: 'utf8', timeout: 60_000}
	).trim();
}

//// Produce a usable activation link for this account.
////
//// The obvious version read `reset_password_key` off the User and put it in the
//// URL. It always failed with "this link has already been used or is invalid",
//// because Frappe stores the SHA-256 HASH of the key, never the key itself:
//// the clear-text value exists only inside the e-mail. Reading the column and
//// using it as the key means handing the server sha256(hash), which matches
//// nothing. That is the mechanism working as designed, not a bug.
////
//// So this does what Frappe does when it composes the mail: mint a key, store
//// its hash, and hand back the clear text. It is the same door the customer
//// walks through, opened from the other side.
function cleActivation(email) {
	const sortie = surLeServeur(
		`from frappe.utils import random_string, now_datetime\n` +
			`from frappe.utils.password import get_decrypted_password\n` +
			`from frappe.utils import sha256_hash\n` +
			`cle = random_string(32)\n` +
			`frappe.db.set_value("User", ${JSON.stringify(email)}, {\n` +
			`    "reset_password_key": sha256_hash(cle),\n` +
			`    "last_reset_password_key_generated_on": now_datetime(),\n` +
			`}, update_modified=False)\n` +
			`frappe.db.commit()\n` +
			`print(cle)`
	);
	return sortie.split('\n').pop().trim();
}

//// Walk the activation link and set a password — the customer's own path.
//// Returns true once the account can be signed into.
async function activerCompte(page, email, motDePasse) {
	const cle = cleActivation(email);
	if (!cle) return false;

	//// Le lien doit mener à une VRAIE page de définition de mot de passe: c'est
	//// ce que le client reçoit, et un lien mort se verrait ici.
	await page.goto(`/update-password?key=${cle}`);
	await page.waitForLoadState('domcontentloaded');
	const nouveau = page.locator('#new_password');
	if ((await nouveau.count()) === 0) {
		derniereRaison = "la page d'activation n'expose pas de champ de mot de passe";
		return false;
	}

	//// Le mot de passe est ensuite posé par l'endpoint que le formulaire appelle
	//// lui-même, plutôt qu'en pilotant le formulaire.
	////
	//// Piloter le formulaire marche, mais dépend de trois détails fragiles à la
	//// fois: ne remplir QUE #new_password et #confirm_password (un #old_password
	//// caché traîne dans la page), frapper les touches une à une (la jauge de
	//// force écoute la saisie, fill() ne déclenche rien et le bouton reste
	//// verrouillé), et attendre que « Confirmer » se libère. Trois façons
	//// d'échouer pour une étape qui n'est pas le sujet du test.
	const r = await page.request.post(
		'/api/method/frappe.core.doctype.user.user.update_password',
		{form: {key: cle, new_password: motDePasse}}
	);
	if (!r.ok()) {
		let detail = '';
		try {
			detail = (await r.text()).replace(/\s+/g, ' ').slice(0, 200);
		} catch (err) {
			detail = '(corps illisible)';
		}
		derniereRaison = `update_password refusé (${r.status()}) : ${detail}`;
		return false;
	}

	//// La preuve n'est pas l'écran mais la session: on tente une connexion.
	//// Plusieurs essais: sous charge, ce login répond 404 ou lève, exactement
	//// comme ailleurs sur ce site.
	for (let essai = 1; essai <= 3; essai += 1) {
		try {
			const r = await page.request.post('/api/method/login', {
				form: {usr: email, pwd: motDePasse},
			});
			if (r.ok()) return true;
			derniereRaison = `login refusé (${r.status()})`;
		} catch (err) {
			derniereRaison = `login injoignable (${err.message.split('\n')[0]})`;
		}
		await page.waitForTimeout(3000 * essai);
	}

	//// Ce que la page dit de l'échec: un lien déjà consommé, un mot de passe
	//// jugé trop faible… c'est là que se trouve la raison, pas dans le booléen.
	const messages = await page.evaluate(() =>
		[...document.querySelectorAll('.alert, .msgprint, .page-card-head, .text-danger')]
			.map((e) => e.textContent.trim().slice(0, 90))
			.filter(Boolean)
			.slice(0, 3)
	);
	if (messages.length) derniereRaison += ` — page: ${messages.join(' | ')}`;
	return false;
}

//// Why the last activerCompte() failed, for the test to report.
function raisonEchecActivation() {
	return derniereRaison || '(raison inconnue)';
}

//// Retire a throwaway account — by DISABLING it, not deleting it.
////
//// Deleting with force=True is what a cleanup script reaches for, and it caused
//// real damage here: other apps rattach every new User to their own records
//// (Drive adds one to a team, Activity Log keeps a trace), and force-deleting
//// leaves those rows pointing at nothing. Frappe then raises LinkValidationError
//// from an unrelated app on the NEXT account's activation — 39 orphan rows had
//// piled up before the cause was found, and the error accused a completely
//// different feature.
////
//// A disabled account leaves nothing dangling, cannot sign in, and is trivial to
//// spot and purge properly later (see README.md).
function supprimerCompte(email) {
	if (!activationDisponible()) return;
	try {
		surLeServeur(
			`nom = ${JSON.stringify(email)}\n` +
				`if frappe.db.exists("User", nom):\n` +
				`    frappe.db.set_value("User", nom, "enabled", 0, update_modified=False)\n` +
				`    frappe.db.commit()\n` +
				`print("ok")`
		);
	} catch (err) {
		//// Le nettoyage ne doit jamais faire échouer un test qui a réussi.
		console.warn(`[e2e] désactivation de ${email} impossible: ${err.message.split('\n')[0]}`);
	}
}

module.exports = {
	activationDisponible,
	activerCompte,
	cleActivation,
	raisonEchecActivation,
	supprimerCompte,
};
