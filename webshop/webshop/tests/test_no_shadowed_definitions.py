# //// Neoffice — added file (no upstream equivalent).
"""Two defects only the shape of a module betrays.

A name defined twice in a module: the second wins, and the first is dead code.
`shopping_cart/cart.py` carried two `process_gift_card_split`, 187 and 185 lines, with
different data shapes. The only caller built the shape the FIRST one read; the second —
the one Python actually runs — refused it as "Invalid gift card data" and returned
without splitting anything, so a gift card worth more than its order lost the remainder.
Found on 2026-09-22 while writing the money-path tests, present in every version since.

A name one function imports for itself and another uses bare: the second raises NameError
the day it runs. The `process_gift_card_split` that survived wrote « Amount adjusted on
{today()} » on the card with `today` imported nowhere in it (other functions of the file
import it locally): the split stopped on that line, after the new card was made and before
the original one was cut down (2026-11-04).

Nothing reads like these defects: the functions are complete, documented and correct on
their own terms.
"""

import ast
import builtins
import unittest
from collections import Counter
from pathlib import Path

APP = Path(__file__).resolve().parents[2]
IGNORE = ("__pycache__", "/node_modules/", "/dist/", "/.git/")


def _modules():
	for path in sorted(APP.rglob("*.py")):
		if not any(part in str(path) for part in IGNORE):
			yield path


def _tree(path: Path):
	try:
		return ast.parse(path.read_text(encoding="utf-8"))
	except SyntaxError:
		return None


def _names_bound_twice(path: Path):
	"""Every name this module binds twice at the same level."""
	tree = _tree(path)
	if tree is None:
		return []

	found = []

	def _level(body, prefix=""):
		count = Counter()
		for node in body:
			if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
				count[node.name] += 1
				if isinstance(node, ast.ClassDef):
					_level(node.body, f"{prefix}{node.name}.")
		found.extend(f"{prefix}{name}" for name, times in count.items() if times > 1)

	_level(tree.body)
	return found


def _imported(node):
	return {(alias.asname or alias.name).split(".")[0] for alias in node.names}


def _module_names(tree):
	"""What the module itself binds, at its top or under an if, a try or a with."""
	names = set(dir(builtins))
	for node in tree.body:
		for each in ast.walk(node) if isinstance(node, (ast.If, ast.Try, ast.With)) else [node]:
			if isinstance(each, (ast.Import, ast.ImportFrom)):
				names |= _imported(each)
			elif isinstance(each, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
				names.add(each.name)
			elif isinstance(each, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
				targets = each.targets if isinstance(each, ast.Assign) else [each.target]
				names |= {n.id for target in targets for n in ast.walk(target) if isinstance(n, ast.Name)}
			elif isinstance(each, ast.Name) and isinstance(each.ctx, ast.Store):
				names.add(each.id)
	return names


def _names_used_without_their_import(path: Path):
	"""Every name a function of this module uses bare while only other functions import it for themselves."""
	tree = _tree(path)
	if tree is None:
		return []
	functions = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
	functions += [
		m
		for c in tree.body
		if isinstance(c, ast.ClassDef)
		for m in c.body
		if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
	]
	imported_locally = {
		name for f in functions for n in ast.walk(f) if isinstance(n, ast.ImportFrom) for name in _imported(n)
	}
	module = _module_names(tree)
	found = []
	for function in functions:
		own = set()
		for n in ast.walk(function):
			if isinstance(n, (ast.Import, ast.ImportFrom)):
				own |= _imported(n)
			elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
				own.add(n.id)
			elif isinstance(n, ast.arg):
				own.add(n.arg)
			elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
				own.add(n.name)
		for n in ast.walk(function):
			if (
				isinstance(n, ast.Name)
				and isinstance(n.ctx, ast.Load)
				and n.id in imported_locally
				and n.id not in module
				and n.id not in own
			):
				found.append(f"line {n.lineno}, {function.name}(): {n.id}")
	return found


class TestNoShadowedDefinitions(unittest.TestCase):
	def test_no_name_is_defined_twice_in_a_module(self):
		offenders = [
			f"{path.relative_to(APP)}: {name}" for path in _modules() for name in _names_bound_twice(path)
		]
		self.assertEqual(
			offenders,
			[],
			"\ndefined twice in the same module, the second definition wins:\n" + "\n".join(offenders),
		)

	def test_no_function_uses_a_name_only_another_one_imports(self):
		offenders = [
			f"{path.relative_to(APP)}: {name}"
			for path in _modules()
			for name in _names_used_without_their_import(path)
		]
		self.assertEqual(
			offenders,
			[],
			"\nused without being imported (NameError the day it runs):\n" + "\n".join(offenders),
		)
