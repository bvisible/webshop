//// Neoffice — added file (no upstream equivalent).
////
//// The sign-in code a visitor receives by e-mail, read from the server.
////
//// A test cannot open a mailbox, and must not need one: the mail is queued by Frappe before it leaves, so the
//// queue row holds exactly what the mailbox would (the code in the subject, the link in the body). This reads
//// the newest one for an address. The same door the shop uses (`frappe.passwordless`, neoffice-maintenance#2192)
//// is driven from the outside; nothing here mints or bypasses a code.
////
//// Needs WEBSHOP_E2E_SSH_HOST and WEBSHOP_E2E_SITE, like the activation helper.

const {onTheServer} = require('./activation');

const lastRead = new Map();

//// The subject starts with the six digits whatever the language the mail is written in ("123456 is your sign-in code
//// for …", "123456 est votre code de connexion pour …"), and the link is the one address that ends in /login-link:
//// neither depends on the words, which the translations change.
const READ_LATEST = (address) =>
	`import re, json, email as em\n` +
	`from email.header import decode_header, make_header\n` +
	`rows = frappe.db.sql("""select q.message from \`tabEmail Queue\` q\n` +
	`  join \`tabEmail Queue Recipient\` r on r.parent = q.name\n` +
	`  where r.recipient = %s order by q.creation desc limit 8""", (${JSON.stringify(address)},))\n` +
	`found = None\n` +
	`for (raw,) in rows:\n` +
	`    msg = em.message_from_string(raw)\n` +
	`    subject = str(make_header(decode_header(msg["Subject"] or "")))\n` +
	`    code = re.match(r"\\s*(\\d{6})\\b", subject)\n` +
	`    if not code:\n` +
	`        continue\n` +
	`    html = ""\n` +
	`    for part in msg.walk():\n` +
	`        if part.get_content_type() == "text/html":\n` +
	`            html = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")\n` +
	`    link = re.search(r'href="([^"]*login-link\\?token=[^"]+)"', html)\n` +
	`    found = {"code": code.group(1), "link": link.group(1) if link else None, "subject": subject}\n` +
	`    break\n` +
	`print(json.dumps(found) if found else "none")\n`;

/** The newest sign-in mail for `address`: {code, link, subject}, or null when none was queued. */
function latestSignInMail(address) {
	const out = onTheServer(READ_LATEST(address)).split('\n').pop().trim();
	return out === 'none' ? null : JSON.parse(out);
}

/**
 * Wait for a sign-in mail to `address` that is not `previousCode`'s, and return it. A test that asks for a second
 * code passes the first one so it cannot read the old mail.
 */
async function waitForSignInMail(address, {previousCode = null, timeout = 60_000} = {}) {
	const deadline = Date.now() + timeout;
	//// The code this process read last for the address is never read again: a second request a few seconds after the
	//// first would otherwise be answered with the first mail while the new one is still on its way.
	const skip = previousCode || lastRead.get(address) || null;
	let last = null;
	while (Date.now() < deadline) {
		last = latestSignInMail(address);
		if (last && last.code && last.code !== skip) {
			lastRead.set(address, last.code);
			return last;
		}
		await new Promise((resolve) => setTimeout(resolve, 2500));
	}
	throw new Error(`no new sign-in mail for ${address} after ${timeout / 1000}s (last: ${JSON.stringify(last)})`);
}

module.exports = {latestSignInMail, waitForSignInMail};
