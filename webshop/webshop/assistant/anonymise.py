# //// Neoffice — added file (shop assistant, no upstream equivalent).
"""Removing from a visitor's words what names a person, before they are kept as a sample (lot E of the 2026-10-30 audit).

A replacement says what was there (`[email]`, `[phone]`, `[document]`, `[iban]`, `[number]`, `[name]`), so a sample still reads as
a question and an answer. It is a net, not a guarantee: after it, `looks_clean` refuses a text that still holds an address sign
or a long run of digits, and the sample is left out. Names are the weak point: a name nobody introduced ("Dupont a commandé")
cannot be told from a word, so only the names a visitor gave about themselves, and the ones the caller knows, are removed.
"""

import re

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,4})?\b")
DOCUMENT = re.compile(r"\b[A-Z]{2,6}(?:-[A-Z]{2,6})*-\d{4}-\d{3,6}\b")
# a card number: 13 to 19 digits, in groups
LONG_NUMBER = re.compile(r"\b\d(?:[ -]?\d){12,18}\b")
PHONE = re.compile(
	r"(?<![\w.])(?:"
	r"(?:\+|00)\d{1,3}(?:[\s.-]?\d{1,4}){3,5}"  # international: +41 79 123 45 67, +33 6 12 34 56 78
	r"|0\d{2}[\s.]?\d{3}[\s.]?\d{2}[\s.]?\d{2}"  # Swiss: 079 123 45 67, 0791234567
	r"|0\d(?:[\s.]?\d{2}){4}"  # French: 06 12 34 56 78
	r")(?!\w)"
)
# "my name is Jean Dupont": the introduction is read in any case, the name itself starts with capitals
_INTRO = (
	r"(?i:je\s+m['’]appelle|mon\s+nom\s+est|my\s+name\s+is|i['’]m\s+called|ich\s+hei[ßs]e|mein\s+name\s+ist"
	r"|mi\s+chiamo|il\s+mio\s+nome\s+è)"
)
_NAME = r"[A-ZÀ-ÝŒ][\w'’-]+(?:\s+[A-ZÀ-ÝŒ][\w'’-]+)?"
INTRODUCED = re.compile(rf"(?P<intro>{_INTRO})\s+(?P<name>{_NAME})")

_REPEATED_NAME = re.compile(r"\[name\](?:\s+\[name\])+")


def names_in(text):
	"""The names a visitor gave about themselves ("je m'appelle Jean Dupont")."""
	return [match.group("name") for match in INTRODUCED.finditer(text or "")]


def clean(text, names=()):
	"""`text` without emails, bank and card numbers, document numbers, phone numbers and names.

	`names` are people the caller knows to be in the conversation (a full name; each of its words is removed too).
	"""
	text = text or ""
	# what has a shape first: a name replaced inside an address ("jean@example.com") would leave an address nobody can read
	text = EMAIL.sub("[email]", text)
	text = IBAN.sub("[iban]", text)
	text = DOCUMENT.sub("[document]", text)
	text = LONG_NUMBER.sub("[number]", text)
	text = PHONE.sub("[phone]", text)
	text = INTRODUCED.sub(lambda match: f"{match.group('intro')} [name]", text)
	for known in names:
		for word in {known, *[part for part in re.split(r"\s+", known) if len(part) >= 3]}:
			text = re.sub(rf"(?i)(?<!\w){re.escape(word)}(?!\w)", "[name]", text)
	return _REPEATED_NAME.sub("[name]", text)


def looks_clean(text):
	"""False when the text still holds an address sign or a run of eight digits: not worth the risk of keeping it."""
	text = text or ""
	return "@" not in text and not re.search(r"\d{8,}", text)
