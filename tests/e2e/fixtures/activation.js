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

let lastReason = '';
const HOST = process.env.WEBSHOP_E2E_SSH_HOST;
const SITE = process.env.WEBSHOP_E2E_SITE;

/** Can this run reach the server to activate an account? */
function activationAvailable() {
	return Boolean(HOST && SITE);
}

//// Run a snippet inside the site's Python environment and return its stdout.
//// Kept to single-purpose read/delete helpers — never a general escape hatch.
////
//// The script travels on STDIN, not as a `python -c "…"` argument: quoting a
//// multi-line Python snippet through a shell, through ssh, through
//// execFileSync is three levels of escaping and it broke on the first one.
function onTheServer(snippet) {
	const script = `import frappe\nfrappe.init(site="${SITE}")\nfrappe.connect()\n${snippet}\n`;
	return execFileSync('ssh', [HOST, 'cd /home/neoffice/frappe-bench/sites && ../env/bin/python -'], {
		input: script,
		encoding: 'utf8',
		timeout: 60_000,
	}).trim();
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
function activationKey(email) {
	const output = onTheServer(
		`from frappe.utils import random_string, now_datetime\n` +
			`from frappe.utils import sha256_hash\n` +
			`key = random_string(32)\n` +
			`frappe.db.set_value("User", ${JSON.stringify(email)}, {\n` +
			`    "reset_password_key": sha256_hash(key),\n` +
			`    "last_reset_password_key_generated_on": now_datetime(),\n` +
			`}, update_modified=False)\n` +
			`frappe.db.commit()\n` +
			`print(key)`
	);
	return output.split('\n').pop().trim();
}

//// Walk the activation link and set a password — the customer's own path.
//// Returns true once the account can be signed into.
async function activateAccount(page, email, password) {
	const key = activationKey(email);
	if (!key) return false;

	//// The link must lead to a REAL password-setup page: that is what the
	//// customer receives, and a dead link would show up here.
	await page.goto(`/update-password?key=${key}`);
	await page.waitForLoadState('domcontentloaded');
	const newPassword = page.locator('#new_password');
	if ((await newPassword.count()) === 0) {
		lastReason = 'the activation page exposes no password field';
		return false;
	}

	//// The password is then set by the endpoint the form itself calls, rather
	//// than by driving the form.
	////
	//// Driving the form works, but depends on three fragile details at once:
	//// filling ONLY #new_password and #confirm_password (a hidden #old_password
	//// lurks in the page), typing the keys one by one (the strength gauge
	//// listens to keystrokes, fill() doesn't trigger anything and the button
	//// stays locked), and waiting for the confirm button to become enabled.
	//// Three ways to fail for a step that is not the subject of the test.
	const r = await page.request.post('/api/method/frappe.core.doctype.user.user.update_password', {
		form: {key, new_password: password},
	});
	if (!r.ok()) {
		let detail = '';
		try {
			detail = (await r.text()).replace(/\s+/g, ' ').slice(0, 200);
		} catch (error) {
			detail = '(body unreadable)';
		}
		lastReason = `update_password refused (${r.status()}): ${detail}`;
		return false;
	}

	//// The proof isn't the screen but the session: attempt a sign-in.
	//// Several tries: under load, this login returns 404 or throws, exactly
	//// like everywhere else on this site.
	for (let attempt = 1; attempt <= 3; attempt += 1) {
		try {
			const login = await page.request.post('/api/method/login', {form: {usr: email, pwd: password}});
			if (login.ok()) return true;
			lastReason = `login refused (${login.status()})`;
		} catch (error) {
			lastReason = `login unreachable (${error.message.split('\n')[0]})`;
		}
		await page.waitForTimeout(3000 * attempt);
	}

	//// What the page says about the failure: a link already consumed, a
	//// password deemed too weak… that's where the reason lives, not in the
	//// boolean.
	const messages = await page.evaluate(() =>
		[...document.querySelectorAll('.alert, .msgprint, .page-card-head, .text-danger')]
			.map((e) => e.textContent.trim().slice(0, 90))
			.filter(Boolean)
			.slice(0, 3)
	);
	if (messages.length) lastReason += ` — page: ${messages.join(' | ')}`;
	return false;
}

//// Why the last activateAccount() failed, for the test to report.
function activationFailureReason() {
	return lastReason || '(reason unknown)';
}

//// Remove a throwaway account, and everything it created.
////
//// This used to only set `enabled = 0`, under a name that said "delete": the
//// address stayed taken for ever, so the same account could never sign up
//// again, and each run left a customer, a contact and a cart behind on the
//// instance. What a shop calls "deleting my account" is exactly this: the
//// history that must stay stays, the address comes free.
////
//// NOTHING here deletes with force=True, and nothing ever should. That is what
//// a cleanup script reaches for, and it caused real damage: other apps attach
//// every new User to their own records (Drive adds one to a team, Activity Log
//// keeps a trace), and force-deleting leaves those rows pointing at nothing.
//// Frappe then raises LinkValidationError from an unrelated app on the NEXT
//// account's activation — 39 orphan rows had piled up before the cause was
//// found, and the error accused a completely different feature. Without force,
//// a link that must survive simply refuses the deletion, which is the point.
////
//// It refuses any address that is not one of the suite's own throwaways
//// (`e2e.…@yopmail.com`). A cleanup helper that can be pointed at a real
//// customer is a loaded gun in a test suite.
////
//// Answers a small report, or null when the server cannot be reached.
function deleteAccount(email) {
	if (!activationAvailable()) return null;
	try {
		const output = onTheServer(`
import json, re

email = ${JSON.stringify(email)}
report = {"email": email, "steps": []}

if not re.match(r"^e2e[.\\-][^@]*@yopmail\\.com$", email or "", re.I):
    report["refused"] = "not one of the suite's throwaway addresses"
    print(json.dumps(report))
    raise SystemExit(0)

def attempt(label, action):
    try:
        action()
        report["steps"].append(label)
    except Exception as error:
        report["steps"].append(label + ": " + type(error).__name__)

def erase(doctype, name):
    frappe.delete_doc(doctype, name, ignore_permissions=True, delete_permanently=True)

for name in frappe.get_all("Quotation", filters={"contact_email": email, "docstatus": 0}, pluck="name"):
    attempt("quotation " + name, lambda name=name: erase("Quotation", name))

contacts = set(frappe.get_all("Contact Email", filters={"email_id": email}, pluck="parent"))
customers, addresses = set(), set()
for contact in contacts:
    for link in frappe.get_all("Dynamic Link", filters={"parent": contact}, fields=["link_doctype", "link_name"]):
        if link.link_doctype == "Customer":
            customers.add(link.link_name)
for customer in customers:
    for link in frappe.get_all("Dynamic Link", filters={"link_doctype": "Customer", "link_name": customer, "parenttype": "Address"}, pluck="parent"):
        addresses.add(link)
for contact in contacts:
    attempt("contact " + contact, lambda c=contact: erase("Contact", c))
for address in addresses:
    attempt("address " + address, lambda a=address: erase("Address", a))
for customer in customers:
    attempt("customer " + customer, lambda c=customer: erase("Customer", c))

try:
    erase("User", email)
    report["account"] = "deleted"
except Exception as error:
    # An account that carries orders cannot be deleted, and must not be: the
    # shop's books are not the test's to rewrite. Freeing the address is
    # enough for the suite to run again, and it is what anonymisation does.
    freed = "deleted-" + frappe.utils.now_datetime().strftime("%Y%m%d%H%M%S") + "-" + email
    frappe.db.set_value("User", email, "enabled", 0, update_modified=False)
    try:
        frappe.rename_doc("User", email, freed, force=True, ignore_permissions=True)
        report["account"] = "renamed (" + type(error).__name__ + ")"
    except Exception as second:
        report["account"] = "disabled only (" + type(second).__name__ + ")"

frappe.db.commit()
print(json.dumps(report))
`);
		return JSON.parse(output.trim().split('\n').pop());
	} catch (error) {
		//// Cleanup must never make a test that succeeded fail.
		console.warn(`[e2e] could not delete ${email}: ${error.message.split('\n')[0]}`);
		return null;
	}
}

//// Does the shop still know this address? The lifecycle spec reads it to prove
//// a deleted account is really gone, and not merely switched off.
function accountExists(email) {
	if (!activationAvailable()) return null;
	const output = onTheServer(
		`print("yes" if frappe.db.exists("User", ${JSON.stringify(email)}) else "no")`
	);
	return output.trim().split('\n').pop() === 'yes';
}

module.exports = {
	activationAvailable,
	accountExists,
	onTheServer,
	activateAccount,
	activationKey,
	activationFailureReason,
	deleteAccount,
};
