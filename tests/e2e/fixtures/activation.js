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

	await page.goto(`/update-password?key=${cle}`);
	await page.waitForLoadState('networkidle');

	//// La page porte TROIS champs mot de passe: #old_password, #new_password et
	//// #confirm_password. Remplir les trois — ce que fait une boucle naïve sur
	//// `input[type=password]` — renseigne un « ancien mot de passe » que ce
	//// compte n'a pas, et l'activation échoue.
	const nouveau = page.locator('#new_password');
	const confirmation = page.locator('#confirm_password');
	if ((await nouveau.count()) === 0) return false;

	//// Frappé caractère par caractère, pas fill(): la jauge de force et le
	//// contrôle de concordance écoutent la SAISIE. Avec fill(), les deux champs
	//// se remplissent, aucune validation ne se déclenche, et « Confirmer » reste
	//// verrouillé pour toujours — un test qui ressemble à un bug applicatif.
	await nouveau.pressSequentially(motDePasse, {delay: 40});
	if (await confirmation.count()) {
		await confirmation.pressSequentially(motDePasse, {delay: 40});
	}

	//// Le bouton part `disabled` et n'est libéré qu'une fois les deux champs
	//// concordants et le mot de passe jugé assez solide: on attend, on ne force
	//// pas — un bouton qui reste verrouillé est une information, pas un obstacle.
	const valider = page.locator('#update, button[type="submit"].btn-update').first();
	if ((await valider.count()) === 0) return false;
	await expect(valider, 'le bouton de confirmation est resté verrouillé').toBeEnabled({
		timeout: 20_000,
	});
	await valider.click();
	await page.waitForTimeout(5000);

	//// La preuve n'est pas l'écran mais la session: on tente une connexion.
	const r = await page.request.post('/api/method/login', {form: {usr: email, pwd: motDePasse}});
	return r.ok();
}

/** Remove a throwaway account created by a test. */
function supprimerCompte(email) {
	if (!activationDisponible()) return;
	try {
		surLeServeur(
			`\nif frappe.db.exists("User", ${JSON.stringify(email)}):\n` +
				`    frappe.delete_doc("User", ${JSON.stringify(email)}, force=True, ignore_permissions=True)\n` +
				`    frappe.db.commit()\nprint("ok")`
		);
	} catch (err) {
		//// Le nettoyage ne doit jamais faire échouer un test qui a réussi.
		console.warn(`[e2e] suppression de ${email} impossible: ${err.message.split('\n')[0]}`);
	}
}

module.exports = {activationDisponible, activerCompte, cleActivation, supprimerCompte};
