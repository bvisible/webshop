# //// Neoffice — added file (no upstream equivalent).
"""A name defined twice in a module: the second wins, and the first is dead code.

`shopping_cart/cart.py` carried two `process_gift_card_split`, 187 and 185 lines, with
different data shapes. The only caller built the shape the FIRST one read; the second —
the one Python actually runs — refused it as "Invalid gift card data" and returned
without splitting anything, so a gift card worth more than its order lost the remainder.
Found on 2026-09-22 while writing the money-path tests, present in every version since.

Nothing reads like this defect: both functions are complete, documented and correct on
their own terms. Only the file's shape betrays it.
"""

import ast
import unittest
from collections import Counter
from pathlib import Path

APP = Path(__file__).resolve().parents[2]
IGNORE = ("__pycache__", "/node_modules/", "/dist/", "/.git/")


def _noms_doubles(chemin: Path):
	"""Every name this module binds twice at the same level."""
	try:
		arbre = ast.parse(chemin.read_text(encoding="utf-8"))
	except SyntaxError:
		return []

	trouves = []

	def _niveau(corps, prefixe=""):
		compte = Counter()
		for noeud in corps:
			if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
				compte[noeud.name] += 1
				if isinstance(noeud, ast.ClassDef):
					_niveau(noeud.body, f"{prefixe}{noeud.name}.")
		trouves.extend(f"{prefixe}{nom}" for nom, fois in compte.items() if fois > 1)

	_niveau(arbre.body)
	return trouves


class TestNoShadowedDefinitions(unittest.TestCase):
	def test_no_name_is_defined_twice_in_a_module(self):
		fautifs = []
		for chemin in sorted(APP.rglob("*.py")):
			if any(part in str(chemin) for part in IGNORE):
				continue
			for nom in _noms_doubles(chemin):
				fautifs.append(f"{chemin.relative_to(APP)}: {nom}")
		self.assertEqual(
			fautifs,
			[],
			"\ndéfini deux fois dans le même module, la seconde définition gagne :\n" + "\n".join(fautifs),
		)
