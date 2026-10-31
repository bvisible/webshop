# //// Neoffice — added file (no upstream equivalent). The checkout's confirmation of changes (#2057).
"""The words of the checkout's own dialogs reach the shopper, in the shopper's language.

Two defects of the first step's confirmation ("The following changes will be applied"), both found by buying in German
on osiris (2026-10-31, neoffice-maintenance#2057):

- `frappe.confirm(message, ifyes, ifno, primary_label, secondary_label)` takes two LABELS, strings. The checkout gave it
  an options object `{title, description}` as its fourth argument: the primary button printed nothing, in every
  language.
- `__('Error applying changes: {0}', [message])` printed "Error applying changes: {0}" in English with the `{0}` left
  in: a website page's `__()` knows only what the theme lists, and a failed call rejects with an xhr, which has no
  `message`.

A website page has no `__()` catalogue of its own: `checkout.html` seeds the sentences (`webshop_checkout_labels`) and the
script says them through `say()`. A key the script asks for and the page does not seed falls back to English without a
word, which is how the second defect went unseen. These tests read the two files: no site, no browser.
"""

import re
import unittest
from pathlib import Path

PAGES = Path(__file__).resolve().parents[2] / "templates" / "pages"
SCRIPT = (PAGES / "checkout.js").read_text(encoding="utf-8")
# the code of the script: a comment may name what it forbids (the `frappe.confirm(` of an explanation is no call)
CODE = "\n".join(line for line in SCRIPT.splitlines() if not line.lstrip().startswith("//"))
PAGE = (PAGES / "checkout.html").read_text(encoding="utf-8")


def seeded_labels():
	block = re.search(r"window\.webshop_checkout_labels\s*=\s*\{(.*?)\};", PAGE, re.S)
	assert block, "checkout.html no longer seeds window.webshop_checkout_labels"
	text = re.sub(r"\{#.*?#\}", "", block.group(1), flags=re.S)  # a Jinja comment may name a key
	return set(re.findall(r'^\s*"([a-z_]+)"\s*:', text, re.M))


def asked_labels():
	return set(re.findall(r"this\.say\(\s*'([a-z_]+)'", CODE))


def call_arguments(source, opening):
	"""The top-level arguments of the call whose `(` is at `opening`, comments and strings left alone."""
	lines = [line for line in source[opening:].splitlines() if not line.lstrip().startswith("//")]
	text = "\n".join(lines)
	arguments, depth, current, quote, i = [], 0, "", None, 0
	while i < len(text):
		char = text[i]
		if quote:
			current += char
			if char == "\\":
				current += text[i + 1]
				i += 1
			elif char == quote:
				quote = None
		elif char in "'\"`":
			quote = char
			current += char
		elif char in "([{":
			depth += 1
			if depth > 1:
				current += char
		elif char in ")]}":
			depth -= 1
			if depth == 0:
				arguments.append(current.strip())
				return arguments
			current += char
		elif char == "," and depth == 1:
			arguments.append(current.strip())
			current = ""
		else:
			current += char
		i += 1
	raise AssertionError("the call is never closed")


class TestTheCheckoutSaysItsOwnWords(unittest.TestCase):
	def test_every_label_the_script_asks_for_is_seeded_by_the_page(self):
		asked, seeded = asked_labels(), seeded_labels()
		self.assertTrue(asked, "the script no longer asks for any label: this test reads nothing")
		self.assertEqual(sorted(asked - seeded), [], "asked by checkout.js, never seeded by checkout.html")

	def test_the_confirmation_gets_two_labels_not_an_options_object(self):
		start = CODE.index("frappe.confirm(")
		arguments = call_arguments(CODE, start + len("frappe.confirm"))
		self.assertEqual(len(arguments), 5, arguments)
		primary, secondary = arguments[3], arguments[4]
		self.assertTrue(primary.startswith("this.say('yes'"), primary)
		self.assertTrue(secondary.startswith("this.say('no'"), secondary)
		self.assertNotIn("{", primary + secondary)

	def test_the_confirmation_is_the_only_one_of_the_page(self):
		self.assertEqual(CODE.count("frappe.confirm("), 1)

	def test_the_error_sentence_is_seeded_and_never_asked_of_the_catalogue(self):
		self.assertNotIn("__('Error applying changes", CODE)
		self.assertIn("error_applying_changes", seeded_labels())

	def test_the_parser_of_this_module_reads_what_it_claims_to(self):
		source = "x(a, {b: 1, c: [1, 2]}, ') ,', (d) => { return 1; }, 'e')"
		self.assertEqual(call_arguments(source, 1), ["a", "{b: 1, c: [1, 2]}", "') ,'", "(d) => { return 1; }", "'e'"])


if __name__ == "__main__":
	unittest.main()
