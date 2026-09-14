# //// Neoffice — added file (no upstream equivalent).
"""A block the shop paints with the text colour, or its muted or faint tint, writes with the
ground's colour.

`--wsh-text` follows the site: dark on a light site, light on a dark one. A chip, a badge
or a tooltip painted with it therefore inverts with the site, and so must its ink: that is
`--wsh-bg`. White (`--wsh-on-ink`, or the `#fff` a Bootstrap badge carries) only reads
while the site is light. On a dark reseller site the active-filter chip read 1.09:1, and
the second-hand badge and the loyalty tooltips were just as blank; no audit had caught it,
because the chip only exists once a filter is on (2026-09-14).
"""

import re
import unittest
from pathlib import Path

STYLESHEETS = Path(__file__).resolve().parents[2] / "public" / "scss"
TEXT_GROUND = re.compile(r"background(?:-color)?\s*:\s*var\(--wsh-(?:text|muted|faint)\)")
INK = re.compile(r"(?:^|[;\s])color\s*:\s*([^;]+)")
# components that carry a text or an icon: painting one without naming its ink leaves the
# ink its framework gives it, which is white
CARRIES_INK = re.compile(r"\.badge|\.btn|chip|tooltip|__play")


def own_declarations(source):
	"""(selector, the block's own declarations) for every block, nested blocks included."""
	blocks, stack, chunk = [], [], ""
	for char in source:
		if char == "{":
			head, _, selector = chunk.rpartition(";")
			if stack:
				stack[-1][1] += head + ";"
			stack.append([selector.strip(), ""])
			chunk = ""
		elif char == "}":
			if stack:
				selector, own = stack.pop()
				blocks.append((selector, own + chunk))
			chunk = ""
		else:
			chunk += char
	return blocks


def text_painted_offenders():
	offenders = []
	for sheet in sorted(STYLESHEETS.glob("*.scss")):
		source = re.sub(r"/\*.*?\*/", "", sheet.read_text(), flags=re.S)
		source = re.sub(r"(?m)(^|[ \t])//.*$", r"\1", source)
		source = re.sub(r"#\{[^}]*\}", "_", source)
		for selector, own in own_declarations(source):
			if not TEXT_GROUND.search(own):
				continue
			inks = [ink.replace("!important", "").strip() for ink in INK.findall(own)]
			if any(ink != "var(--wsh-bg)" for ink in inks) or (not inks and CARRIES_INK.search(selector)):
				offenders.append(f"{sheet.name}: {' '.join(selector.split())} -> {inks or 'no colour'}")
	return offenders


class TestTextPaintedBlocks(unittest.TestCase):
	def test_a_block_painted_with_the_text_colour_writes_with_the_ground(self):
		offenders = text_painted_offenders()
		self.assertEqual(offenders, [], "\n" + "\n".join(offenders))

	def test_the_reader_sees_nested_blocks_and_their_own_declarations(self):
		blocks = dict(own_declarations(".a { color: red; .b { background: var(--wsh-text); } padding: 0; }"))
		self.assertIn("background: var(--wsh-text)", blocks[".b"])
		self.assertNotIn("background", blocks[".a"])
		self.assertIn("padding: 0", blocks[".a"])
