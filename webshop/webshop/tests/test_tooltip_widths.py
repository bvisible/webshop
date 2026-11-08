# //// Neoffice — added file (no upstream equivalent): a hidden tooltip must not widen the page.
"""The loyalty points tooltip sits hidden above its block until the pointer comes. Hidden, it is still laid out: written on one line and centred on its
block, a sentence of 448 px ran past the right edge of a 390 px phone, and the whole product page scrolled sideways, its fixed buy bar cut on the right
(2026-11-08). A tooltip wraps its sentence inside the screen."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHEETS = (ROOT / "public" / "scss" / "webshop_loyalty.scss", ROOT / "templates" / "includes" / "cart_component.css")


def tooltip_blocks(path: Path) -> list[str]:
	"""The declarations of every rule that places a loyalty tooltip, up to its first closing brace."""
	text = path.read_text(encoding="utf-8")
	blocks = [text[m.end() : text.index("}", m.end())] for m in re.finditer(r"\.loyalty-tooltip\s*\{", text)]
	return [block for block in blocks if "position: absolute" in block]


class TestATooltipStaysInsideTheScreen(unittest.TestCase):
	def test_every_sheet_places_a_tooltip(self):
		for path in SHEETS:
			self.assertTrue(tooltip_blocks(path), path.name)

	def test_a_tooltip_wraps_inside_the_screen(self):
		for path in SHEETS:
			for block in tooltip_blocks(path):
				self.assertNotIn("white-space: nowrap", block, path.name)
				self.assertIn("max-width: min(320px, calc(100vw - 32px))", block, path.name)
