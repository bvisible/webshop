# //// Neoffice — added file (shop assistant, no upstream equivalent).
"""What is written beside each message of the log, so that a conversation can be found later (lot D of the 2026-10-30 audit).

The flags are signals for the person who reads the log, not verdicts: a message flagged `injection_suspected` is one worth
reading, not one that was dangerous (the model's rules and the quality battery are what hold the line). The wordings are
the ones shop visitors and the model really used (the battery's cases, `quality/real_outputs.json`), in French, English,
German and Italian, the languages the shops are written to in.
"""

import hashlib
import hmac
import re

import frappe
from frappe.utils import nowdate

from webshop.webshop.assistant import prompt
from webshop.webshop.assistant.quality import classify
from webshop.webshop.utils import throttle

# A visitor asking the assistant to forget its rules, to take another role, to reveal its prompt, or hiding a request in a
# long encoded blob (forty characters of base64 with both cases: a link, a hash or a word never has them). `DAN` is the one
# word written in capitals only: Dan is a first name.
INJECTION = re.compile(
	r"""(?ix)
	\b(ignore|ignorez|ignorer|oublie|oubliez|disregard|forget)\b[^.\n]{0,40}\b(instructions?|r[èe]gles?|consignes?|rules|prompt)\b
	| \[\s*(system|syst[èe]me|admin|developer)\s*\]
	| \bsystem\s+prompt\b | \b(prompt|message)\s+syst[èe]me\b
	| \b(mode|modus)\s+(d[ée]veloppeur|developer|dev|admin|sans\s+restriction)\b
	| \b(tu\s+es|vous\s+[êe]tes|you\s+are|du\s+bist)\s+(maintenant|now|jetzt)\b
	| (?-i:\bDAN\b) | \bjailbreak\b
	| \b(r[ée]p[èe]te|r[ée]v[èe]le|affiche|montre|print|reveal|show|repeat|liste)\b[^.\n]{0,40}\b(ton|tes|ta|your)\s+(prompt|instructions|r[èe]gles|rules)\b
	| \b(ignoriere|vergiss)\b[^.\n]{0,40}\b(anweisungen|regeln)\b
	| \b(ignora|dimentica)\b[^.\n]{0,40}\b(istruzioni|regole)\b
	| (?-i:(?=[A-Za-z0-9+/]*[A-Z])(?=[A-Za-z0-9+/]*[a-z])[A-Za-z0-9+/]{40,}={0,2})
	"""
)

# The assistant says it does not know, or cannot find: the shop's knowledge or catalogue did not hold the answer.
UNANSWERED = re.compile(
	r"""(?ix)
	je\s+ne\s+sais\s+pas | je\s+n['’]ai\s+pas\s+(cette\s+|l['’])?information | je\s+ne\s+trouve\s+pas
	| je\s+ne\s+dispose\s+pas | aucune\s+information | je\s+n['’]ai\s+(pas|rien)\s+trouv\w*
	| i\s+(don['’]?t|do\s+not)\s+know | i\s+(couldn['’]?t|could\s+not|can['’]?t|cannot)\s+find
	| i\s+don['’]?t\s+have\s+(that|this)\s+information | i\s+(didn['’]?t|did\s+not)\s+find
	| wei[ßs]s?\s+ich\s+(leider\s+)?nicht | ich\s+finde\s+(keine|nichts) | ich\s+habe\s+(keine|nichts)\s+gefunden
	| non\s+lo\s+so | non\s+(ho|trovo)\s+(questa\s+)?informazion\w* | non\s+riesco\s+a\s+trovare | non\s+ho\s+trovato
	"""
)


def user_flags(text):
	"""Flags of what the visitor wrote."""
	return ["injection_suspected"] if INJECTION.search(text or "") else []


def reply_flags(reply, escalated=False):
	"""Flags of what the assistant answered; `escalated` when this turn handed the visitor to the team."""
	from webshop.webshop.assistant import engine  # engine imports this module

	found = []
	if classify.off_domain(reply or ""):
		found.append("off_topic_refused")
	if (reply or "").strip() == engine.FALLBACK or UNANSWERED.search(reply or ""):
		found.append("unanswered")
	if escalated:
		found.append("escalated")
	return found


def pack(found):
	"""Flags as they are stored: between commas, so that `like '%,unanswered,%'` finds a whole word and nothing longer."""
	return f",{','.join(found)}," if found else ""


def language_of(text):
	"""'en', 'de' or 'it' when the visitor clearly wrote in that language, else 'fr' (the shops' own)."""
	return prompt.visitor_language(text) or "fr"


def ip_hash(day=None):
	"""A hash of the peer's address that is the same all day and different the next, '' outside a request.

	It lets a person reading the log see that fifty messages came from one source, without the log holding an address:
	the hash cannot be followed from one day to the next, and it cannot be reversed without the site's key.
	"""
	if not getattr(frappe.local, "request", None):
		return ""
	key = (frappe.local.conf.get("encryption_key") or frappe.local.site or "").encode()
	message = f"{day or nowdate()}:{throttle.peer_ip()}".encode()
	return hmac.new(key, message, hashlib.sha256).hexdigest()[:16]
